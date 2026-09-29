# Factored-Record Migration Plan

Status: **DRAFT for review** (2026-08-24). Companion to
[VERDICT_REPRESENTATION.md](VERDICT_REPRESENTATION.md) — that doc argues *why* the single verdict
token is thin-and-lying and specifies the factored typed record + the six moves + the scorecard.
**This doc is the executable plan**: it expands the four-step §6 strangler-fig into PR-sized units
across the three repos, tied to acceptance gates, with a status ledger for what the incremental
moves already shipped and what the record-introduction still owes.

The invariant that makes the whole migration safe: **the legacy token is a pure rendering
`ρ(record)` of the record**, so every step is byte-for-byte golden-preserving until we *deliberately*
rebless one axis at a time.

---

## 0. Where we actually are (status ledger)

The six moves were partially executed *ahead of* the record, as standalone slices against the
existing token/resolver machinery. That was the right call (each was independently valuable and
shippable), but it means the moves are **not** the record — they are behaviours the record must
preserve and then subsume. Current state:

| Move (from VERDICT_REPRESENTATION §4) | Shipped? | What landed | What the record still owes |
|---|---|---|---|
| #1 Wire killer/opposing signals | **Partial** | Safety WT-loss now routes through `verdict_by_modality` (Layers 0–3). | General signal-sink: ~0/32 non-safety `(channel,value)` pairs still consumed. Record's `Fold` is where they get consumed structurally. |
| #2 Availability open- vs closed-world | **Partial** | `acquisition_backlog` facet emits open-world gaps as ACQUIRE actions; `no_data` treated gate-inert in the de-dup facet. | The *record-level* `availability` enum + the validation invariant (open-world ⇒ `finding.state=unknown`, no `direction`). Resolvers still fold no-data into `insufficient` on most axes. |
| #3 Certainty coordinate, all axes | **Done** | `(strength, certainty)` sidecar on dependency, tumor-selectivity, genomic-alteration, surface-modality-fit, tumor-presence, differentiation; safety/tractability read `unmeasured` where no disjoint corroborator exists. `CERTAINTY_MODEL.md` + disjointness validator (`validate_certainty_disjointness.py`, no-resolver-aware). | Fold `certainty` into the record as a first-class coordinate (currently a parallel sidecar dict, not part of a unified `Claim`). |
| #4 `verdict_by_modality` vector | **Done for the justified split** | Safety emits per-channel via `modality_safety.py`; `wt_engagement` property on `modality.enum`; role-proxy downgrade rungs deleted. I5 measured: SM-vs-biologics diverges 25/36 (build it), ADC-vs-TCE 3/36 (skip). | Generalize the vector beyond safety into the record's `modality_scope` for every axis that can diverge (surface already modality-specific; others default single-channel). |
| #5 Coarsen magnitude / demote inert rules | **Not started** | — | The record's `finding.magnitude` (ordinal level + retained raw value + distance-to-cut); demote the 273 inert rules to a display channel; kill the `ratio == 1.0` fabrication. |
| #6 De-bias composition | **Partial** | `_cross_gate_shared_evidence` facet flags the 6 shared cards + pseudo-replication so corroboration isn't summed naively. | Match-all-then-reduce **Fold** replacing first-match precedence (removes order-bias structurally, not just as a flag). |

**Read of the ledger:** certainty and the safety-modality vector are genuinely done. Everything
else is a *behavioural down-payment* against the record — the flag, facet, or sidecar exists, but
the underlying scalar/first-match machinery is still the source of truth. The migration below is
what turns those down-payments into the record and retires the ladder.

---

## 1. Design deltas since VERDICT_REPRESENTATION §3

Two things the parent doc assumed are now settled by data or by shipped work — fold them in:

1. **`modality_scope` is a 2-channel base, not 5.** I5 (Phase-0b, n=36) says only SM-vs-biologics
   earns a distinct action (69% divergence); ADC/TCE sub-split is 8% — carry it as a *refinement*
   channel only where a named discriminator fires (endocytosis, antigen-escape), never as a default
   axis. This shrinks the record and the golden surface.
2. **`certainty` already has a shipped schema** (`CERTAINTY_MODEL.md`: `{level, coverage,
   corroboration, unknown_mass}` + `strength`). The record must **adopt this verbatim** as its
   `certainty` coordinate rather than re-inventing the parent doc's
   `{provenance_class, corroboration, directness}` — the shipped one is what 6 axes and the
   disjointness validator already speak. Reconcile the parent doc's `certainty` block to match
   (a one-line errata PR against VERDICT_REPRESENTATION §3).

---

## 2. The record schema (M0 deliverable)

Introduce **one** contract, consumed by nobody at first:
`schemas/claim_record.schema.json` + a rendered example per axis under `docs/design/examples/`.

```yaml
Claim(axis):
  finding:
    state:        <closed per-axis enum>            # reuse each resolver's existing verdict enum as v1
    direction:    supports | opposes | neutral
    magnitude:    { level: none|weak|moderate|strong, value: <num|null>,
                    scale: <unit|null>, distance_to_cut: <num|null> }
    availability: not_wired | data_blocked | read_error | insufficient
                | measured_negative | measured_positive | out_of_scope
  mechanism:      { classes: set<MoAClass>, role: GoF|LoF|DN|mixed|unknown }
  modality_scope: { small_molecule, biologics: favorable|unfavorable|na,   # 2-channel base (I5)
                    _refinements: { adc?, bite_tce?, degrader? } }         # only when a named discriminator fires
  certainty:      { level, coverage, corroboration, unknown_mass, strength }   # == CERTAINTY_MODEL.md, verbatim
  provenance:     { fired_rule_ids, cards, source_product_ids, versions }      # composition-INERT audit sidecar
```

**Validation invariants** (new validator `validators/validate_claim_record.py`, wired into
`contracts-validate`):
- open-world `availability` (`not_wired|data_blocked|read_error`) ⇒ `finding.state == unknown`
  and `finding.direction == neutral` (a `not_wired` record carrying a `direction` fails).
- `finding.state` ∈ the axis's declared enum (reuse the resolver's verdict token set for v1).
- `magnitude.value != null` ⇒ `scale != null` (no bare numbers).
- `certainty` block passes the existing disjointness rule (corroboration card ∉ verdict cards).

**M0 acceptance:** schema + validator + one hand-authored example per axis; `contracts-validate`
green; **zero** runtime consumers. Scorecard: no movement yet (shadow only).

---

## 3. Migration phases (PR-sized, per repo)

Strangler-fig, expanded from §6. Each phase is a small stack of PRs; the token stays the source of
truth until **M3**.

### M1 — Shadow the record (compute, emit, consume nothing)

- **skills** (per axis, one PR each, mirrors the certainty-hook fan-out that just shipped): a
  `_claim_record(cards, fired, verdict_pair)` builder that assembles the `Claim` from the *same*
  inputs the resolver + certainty hook already read. Emit into
  `decision.json.claim_vector_shadow[axis]`. **Consume nothing.** Goldens untouched (shadow is a new
  key; add it to the golden allowlist as non-asserted, or emit behind `--emit-claim-shadow`).
- **contracts:** nothing beyond M0.
- **Acceptance:** shadow present for all 10 axes on the calibration set; `provenance.fired_rule_ids`
  in the shadow == the resolver's actual fired set (a cross-check test per axis). Scorecard I4
  (warrant-carrying rate) computable from the shadow → expect a jump from ~0.1 toward ~1.0 as the
  *shadow* now carries `{availability, certainty}` everywhere.

### M2 — Prove `ρ(record) ≡ legacy_token`

- **skills:** implement `render(claim) -> token` (pure lookup) and a replay test over the ~40-target
  calibration runs asserting `render(claim_vector_shadow[axis]) == decision.json.verdict[axis]`
  **byte-for-byte, all axes**. This is the gate that lets us swap the source in M3.
- **Adjudication:** any mismatch is either a builder bug *or* a latent first-match-order artifact in
  the legacy ladder. Log each; route order-artifacts to a domain expert (they are exactly the R6
  silent-masking cases the audit predicted). Do **not** "fix" the token to match — fix the builder,
  or record the ladder bug as a deliberate future rebless.
- **Acceptance:** 100% render-equivalence on the calibration set (or an explicit, expert-signed list
  of adjudicated order-artifacts carried into M4). Scorecard R6 (order-bias) now *quantified* (the
  mismatch count).

### M3 — Swap the source (record becomes truth; ladder → oracle)

- **skills:** `decision.json.verdict[axis]` is now sourced from `render(claim)`; the resolver ladder
  is retained **only** as a test oracle (`test_render_matches_ladder`). Hashes don't move (M2
  proved it). Promote `claim_vector_shadow` → `claim_vector`.
- **contracts:** `claim_record.schema.json` gains consumers → flip its validator from advisory to
  required in `contracts-validate`.
- **Acceptance:** full skills suite + all resolver goldens green with the record as source;
  `scripts/preland.sh` clean. **This is the point of no easy return** — after M3 the record is load-
  bearing. Rollback = re-point `verdict` at the ladder (kept as oracle), record stays additive.

### M4 — Earn new distinctions (one reviewed rebless per axis)

Now — and only now — the record is allowed to say things the token couldn't. Each is **one axis, one
golden-rebless PR**, with the calibration set as the diff surface and a scorecard target:

- **M4a — split `insufficient`** into open-world (`not_wired|data_blocked` → ACQUIRE, non-directional)
  vs closed-world (`measured_negative` → KILL). Target: **R2** (ignorance/negation separation)
  5/10 → 10/10; **R3** (honest-abstention) → 1.0. The `acquisition_backlog` facet from Move #2
  becomes the ACQUIRE surface.
- **M4b — generalize `verdict_by_modality`** from safety to every divergent axis, SM-vs-biologics
  base only (I5). Target: **I5** realized without inflating the golden surface with the inert
  ADC/TCE axis.
- **M4c — coarsen `magnitude`** to boundary-aligned bins (`{below_gate, above_gate}` + `borderline`
  only in the near-threshold band, only when n supports it); replace the `ratio == 1.0` veto with a
  banded rule. Target: **R1** fabrication flags → 0; **R5** over-precision (levels-emitted vs
  levels-that-flip) → tight.
- **M4d — match-all-then-reduce Fold** replaces first-match precedence structurally. Target: **R6**
  → 0 (order-independence proved by a permutation test, not a flag).

Each M4 PR must show the scorecard delta in its description and re-bless only the goldens that
*should* move.

### M5 — Demote the inert 273 rules to a display channel

- **contracts:** the 273 verdict-inert rules move from `signals:` that no resolver reads into an
  explicit `display:` / annotation channel, so the record's provenance can surface them without
  pretending they gate. Target: **I1** signal-sink coverage stops being measured against dead
  emitters; **I3** per-coordinate VOI documents which rules are annotation-only by design.

---

## 4. Dependency & sequencing

```
M0 (contracts: schema+validator)
  └─> M1 (skills: shadow builder, per axis — parallelizable, 10 PRs)
        └─> M2 (skills: render + equivalence proof)   ← BLOCKING GATE
              └─> M3 (skills+contracts: swap source, validator required)
                    ├─> M4a insufficient split
                    ├─> M4b modality vector generalize   (I5 already measured → safe to build)
                    ├─> M4c magnitude coarsen
                    ├─> M4d match-all fold
                    └─> M5 demote inert rules (contracts)
```

- M1 fans out per axis exactly like the certainty-hook sweep that just completed — reuse that
  pattern (per-skill `_claim_record` + a `test_claim_shadow_matches_ladder`), so the fan-out is
  low-risk and reviewable one skill at a time.
- **M2 is the single blocking gate.** Nothing downstream is safe until render-equivalence is proved.
- M4a–d and M5 are independent of each other and can land in any order / parallel sessions, each
  gated on its own scorecard metric. Do **not** bundle them — the whole point is one reviewed
  rebless at a time.

## 5. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Builder drift: shadow record diverges from what the resolver actually read | M1 acceptance cross-checks `provenance.fired_rule_ids` == resolver fired set; M2 proves render-equivalence byte-for-byte before any swap. |
| Golden churn masks a real regression during M4 rebless | One axis per PR; PR body must show the scorecard delta and enumerate every re-blessed golden with a one-line justification. |
| Order-artifacts in the legacy ladder get silently "fixed" into the token | M2 forbids editing the token to match; mismatches are adjudicated by a domain expert and carried as explicit reblesses into M4d. |
| `certainty` schema fork (parent doc vs shipped) | §1 delta: record adopts `CERTAINTY_MODEL.md` verbatim; one errata PR reconciles VERDICT_REPRESENTATION §3. |
| n≈40 tempts a learned fold | Explicitly out of scope (parent §2/§7). Every record coordinate is card-emitted, expert-mapped, or a deterministic set/max/meet fold — nothing fit. |
| Cross-repo land-order (skills reference contract enums) | contracts M0 lands first; skills M1 references the schema; validator flips to required only at M3 when consumers exist. |

## 6. What this plan does **not** do (still deferred)

Unchanged from VERDICT_REPRESENTATION §7 — the record is deliberately a *per-axis vector*, not a graph
or a probability model:

- **Relational side-structure** (SL partner identity, node-leverage "a better-leveraged neighbour
  exists", co-mutation partner+pathway, MoA→modality 31-class wiring, cross-gate shared-card de-dup as
  a graph) — separate workstream.
- **Probabilistic shared-parent layer** — the only correct fix for the 6-card cross-gate
  double-counting *with calibrated uncertainty*; deferred (n≈40 can't fit CPTs, byte-identical floats
  unachievable). The `_cross_gate_shared_evidence` facet is the interim honest flag.
- **Interpretable decision manifold / portfolio layer** — revisit at ≫200 labeled targets.

---

### Appendix — scorecard baselines to beat (from VERDICT_REPRESENTATION §5.1)

I1 = 0/32 · verdict-inert = 270/393 (68%) · R6 worst fan-in safety 9→1 / genomic 8→1 ·
R4 cross-gate cards = 6 · R7 certainty coverage was 1/10 (**now ~6/10 gating axes + 2 `unmeasured`**
after the certainty sweep) · effective rank ≈ 4 · availability abstention 121/396 (31%, concentrated
in SL/subtype/differentiation). Every M-phase acceptance is stated as a delta against these.
