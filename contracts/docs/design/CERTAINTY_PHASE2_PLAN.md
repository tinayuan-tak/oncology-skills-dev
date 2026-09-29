# Certainty layer — Phase 2 implementation plan (central per-axis certainty tier)

**Status:** PLAN for sign-off (2026-08-18) · implements §5 of [`CERTAINTY_MODEL.md`](CERTAINTY_MODEL.md)
· gated by the Phase-0 A/B (PASSED) and the Phase-0.5 framing fix.

**Objective (locked):** narrative fidelity + analyst confidence calibration, **verdict-inert**. Phase 2
adds a *coarse per-axis certainty tier* to the `target-profile` synthesis, computed **centrally** (in
`tp_facets`), with **zero per-skill code** and **no carrier change**. It does not move the
recommendation, the gate, or the audited confidence tier.

---

## 1. Why Phase 2 exists (what Phase 0 left on the table)

Phase 0 routes the composed **fragility facet** into synthesis — a *flip-stability* signal (how
sensitive a verdict LABEL is to toggling one resolver rule). The MET/LUAD A/B proved that
flip-fragility is **not** the same as evidence-certainty:

| MET/LUAD dependency | value | reading |
|---|---|---|
| `decision_flip_fragility` | 0.5455 (12/22 rules) · `contested: True` | ladder is **brittle** (structural) |
| `cards_missing` | `[]` (0 of 11) | data is **complete** |
| fired concordance rule | `concordant-non-dependent-neutral` | CRISPR ↔ RNAi **agree** |

So the *call* is a biologically-solid concordant negative sitting on a *brittle rule ladder*. Phase 0.5
fixed the **framing** (tell the LLM not to read flip-fragility as evidentiary doubt). Phase 2 adds the
**missing signal**: a positive statement of *evidence-certainty* (coverage + corroboration +
unknown_mass) so a solid-but-brittle call reads as **high certainty / brittle ladder**, not as doubt.

---

## 2. What Phase 2 builds

Extend `tp_facets` (the central, target-profile-side facet layer — no sub-skill edits) to emit, per
decision-relevant axis, a coarse **`certainty`** object matching the 4-field contract shape:

```
certainty = { level, coverage, corroboration, unknown_mass }   # level = min(coverage, corroboration)
```

computed **only from signals target-profile already has centrally**:

- **coverage** — reuse `tp_gates._run_coverage_for_short` (already computed in the fragility facet:
  `full` / `partial` / `blind`, downgraded to `blind` when all a gate's cards are missing this run).
- **unknown_mass** — the §1.1 contract definition: **fraction of the axis's decision-relevant cards
  that are `data_unavailable` / blind this run** = `n_missing_cards / n_cards` from `sub_results[short]
  ["cards"]` (already assembled for the fragility facet). Purely generic; no per-skill knowledge.
- **corroboration** — **DEFERRED to Phase 3 for most axes.** Central code cannot read a card's
  agreement *value* (e.g. Broad↔Sanger replication class) without per-skill field knowledge, and the
  contract requires corroboration be **verdict-disjoint** (a validator-enforced property). In Phase 2,
  `corroboration` is emitted as `unmeasured` (which, per weakest-link, does **not** inflate `level`),
  EXCEPT where a verdict-disjoint agreement flag is *already surfaced centrally* (none are today). This
  keeps Phase 2 honest and zero-per-skill; corroboration is the Phase-3 leg.
- **level** = `min(coverage, corroboration)` with `corroboration = unmeasured` treated as a ceiling of
  `medium` (an axis with full coverage but no measured corroboration is *at most* `medium`-certain — it
  is not `high` until independent lines are shown to agree). This is the one calibration knob; see §4.

**Presentation.** Route `certainty` into the same how-solid prompt block (Phase 0.5), in its own
columns, ALONGSIDE — never merged with — call-fragility. The block already forbids conflation; Phase 2
adds the positive certainty read so the LLM can say *"solid call, brittle ladder"*.

**Non-goals (hard boundaries):** no per-skill code; no `GateVerdict`/`compose_core` carrier field; no
resolver-grammar change; `certainty` stays a target-profile-side sidecar keyed by sub-skill short and
is **not** written into `nomination.json` `sub_verdicts` or `GateVerdict.as_dict()` (byte-golden).

---

## 3. Acceptance test (the golden case)

**MET / LUAD is the named Phase-2 acceptance test.** With the Phase-2 tier wired, on MET dependency:

- `certainty.coverage` = the run coverage (`partial` baseline, **not** downgraded — 0 cards missing),
- `certainty.unknown_mass` = `0.0` (0/11 cards unavailable),
- `certainty.corroboration` = `unmeasured` in Phase 2 (→ `level` capped at `medium`),
- `certainty.level` ≥ `medium` (a complete, concordant read is NOT low-certainty),

**while** the fragility facet reads `fragility 0.5455`, `contested: True` (brittle ladder).

PASS = the two signals **diverge** (certainty ≥ medium, fragility brittle) AND the synthesis prompt
presents them in distinct columns/sentences. A unit test asserts the divergence deterministically
(no Bedrock); an A/B re-run on MET confirms the prose now says "solid negative on a sensitive ladder"
rather than "unresolved gap". If Phase 2 cannot make MET's certainty read ≥ medium while fragility
stays brittle, the tier is not doing its job.

> Note the tension Phase 3 must later resolve: once corroboration is wired (dependency →
> Broad↔Sanger cross-consortium, per the contract), MET's `level` should rise to `high` IF the
> consortia replicate the non-dependency — turning "at most medium" into a confident solid negative.

---

## 4. Open calibration questions (need owners before wiring)

1. **The `corroboration = unmeasured → level ≤ medium` cap.** Is "full coverage but no measured
   corroboration = at most medium" the right default, or should full+concordant single-consortium read
   `high`? (Recommend the `medium` cap: it honestly reserves `high` for shown independent agreement.)
2. **Coverage tier semantics per axis** — `_run_coverage_for_short` returns a baseline
   `framework_can_evidence` tier per gate; the 8 non-dependency baselines need owners (this is the
   same open item as `CERTAINTY_MODEL.md` §4.1 — do not wire an axis whose baseline is unowned).
3. **unknown_mass exposure** — numeric + ordinal, or ordinal only (carried from the contract §4.2).

---

## 5. STOP gate → Phase 3

Proceed to Phase 3 (per-skill, verdict-disjoint corroboration adapters, path-A resolver skills only)
**only if** a reviewed nomination is demonstrably mis-narrated for lack of a *corroboration* signal the
central Phase-2 tier cannot supply (i.e. coverage + unknown_mass + framing were not enough). Otherwise
stop at Phase 2. The MET case is the first evidence to weigh: if the Phase-2 `medium` cap reads as
honest and sufficient, Phase 3 corroboration is a refinement, not a requirement.
