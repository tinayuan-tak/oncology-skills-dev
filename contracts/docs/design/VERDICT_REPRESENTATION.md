# Verdict & Rule Representation — Design Proposal

Status: **DRAFT** (2026-08-24). Author: audit synthesis (8-agent richness panel + 5-agent
representation panel + 4-lens information/representation panel). Not yet on a branch; do not
merge without the target-contracts worktree/PR ritual.

---

## 1. Problem (measured, not asserted)

The abstraction layer compresses a large evidence base (84 cards → 393 rules) into a per-axis
**verdict token** (10 `resolvers/*.resolver.yaml`, first-match precedence over the fired-rule
SET) → a **scalar** nomination (`pass|hold|veto`). A static audit (`scripts/`-runnable, see §6)
found the layer is simultaneously **over-compressed and over-representative** — it fails the two
things a knowledge layer must do at once:

| Measured defect | Number |
|---|---|
| Rules defined vs **verdict-inert** (no resolver consumes them) | 393 total, **273 (69%) inert** |
| Signal `(channel,value)` pairs emitted by rules vs **consumed by resolvers** | **32 emitted (incl. `killer`/`opposing` + all 5 modality channels), 0 consumed** |
| Worst compression fan-in (rules → one token) | genomic `multi_class_driver` **8→1**; tractability `structurally_ligandable` **6→1**; safety `human_genetics_safety_concern` **5→1** |
| Resolvers separating no-data / ambiguous / negative | only **1 of 10** (selectivity); 5/10 fold no-data into `insufficient` |
| One measurement driving **>1 verdict gate** (double-count) | 6 cards — e.g. `normal-tissue-liability`→safety+surface; `pan-cancer-crispr-dependency`→dependency+safety |
| Continuous fields (log2fc, LOEUF, copies/cell, CERES) coerced to nominal tokens at hard cuts | pervasive; incl. a measure-zero `ratio == 1.0` veto |
| Certainty layer wired | **1 of 10 axes** |

Root cause: a **single categorical token** is forced to carry three concerns that should be
orthogonal — *finding* (what the evidence says), *interpretation* (what it means for a
nomination), *confidence* (how sure) — while **discarding** magnitude, modality-conditionality,
mechanism class, and the ignorance-vs-negation distinction. A scalar bottleneck makes over- and
under-compression unavoidable simultaneously.

## 2. Objective

Make the layer **maximally informative while staying representative** — two *orthogonal*
quantities, both to be driven toward 1:

- **Informative** = retain every distinction that changes a nomination (rate–distortion
  *retention*; decision-theoretic *value of information*; epistemic *warrant survives*).
- **Representative** = assert nothing the data doesn't support, with no bias (measurement-theoretic
  *homomorphism / no fabrication*; epistemic *ignorance ≠ negation*; *no false precision*).

**Informative ≤ faithful** — you cannot buy signal by asserting structure the data lacks. The
distortion measure is **decision loss (nomination regret), not data reconstruction**. Because
n≈40 labeled targets is too small to *fit* anything, sufficiency is assessed **structurally**
(a distinction matters iff some downstream fold's output changes when it flips) — label-free,
deterministic, PR-reviewable.

Non-goals: any learned/ML combiner (n too small); a probabilistic layer or interpretable
decision manifold (both deferred — see §7).

## 3. Solution — the factored typed record

Replace the single verdict token with a **factored, typed record per axis**. The token survives
only as a **pure rendering** `ρ(record)` (a lossy projection for humans + backward-compat), so
determinism and the ~300 golden tests are preserved (token is *derivable* from the record).

```yaml
Claim(axis):
  finding:
    state:        <closed per-axis enum>              # WHAT (e.g. selective | broad | none)
    direction:    supports | opposes | neutral         # valence toward nomination
    magnitude:    { level: none|weak|moderate|strong,  # HOW MUCH — ordinal, binned to decision
                    value: <num>, scale: <unit>,       #   cutpoints; raw value + distance-to-cut
                    distance_to_cut: <num> }           #   retained (late, non-destructive discretization)
    availability: not_wired | data_blocked | read_error   # OPEN-WORLD ignorance  → ACQUIRE
                | insufficient                             # measured-but-underpowered → HOLD-WEAK
                | measured_negative | measured_positive    # CLOSED-WORLD finding → KILL / PASS
                | out_of_scope                             # question malformed for this target → n/a
  mechanism:  { classes: set<MoAClass>, role: GoF|LoF|DN|mixed|unknown }   # WHY / which class
  modality_scope:                                     # FOR WHAT — per channel
    { small_molecule, degrader, adc, bite_tce, antibody } -> favorable|unfavorable|na
  certainty:  { provenance_class: measured|inferred|curated|predicted,
                corroboration:   single|corroborated|contradicted,
                directness:      direct|proxy }        # HOW SURE — orthogonal to magnitude, downgrade-only
  provenance: { fired_rule_ids, cards, source_product_ids, versions }   # composition-INERT audit sidecar
```

**Three deterministic, hand-authored operators** (no arithmetic on measured values beyond ordinal
comparison; commutative/associative folds → byte-stable regardless of rule order):

1. **Fold** (rules → record): `magnitude.level = max`; `availability` via a fixed join table;
   `mechanism.classes = set-union`; `modality_scope` per-channel meet. Replaces the first-match
   precedence ladder with an *algebra*.
2. **Render** `ρ(record) → token`: a pure lookup; the legacy token string is unchanged so goldens
   hold.
3. **Compose** (records → nomination): the gate reads records and emits **`verdict_by_modality`**
   (a per-channel action vector), not a scalar.

**Separation invariant:** finding ⊥ interpretation ⊥ confidence. The resolver emits a *finding*
(`pan_essential`); the **gate** assigns the *action* (`kill`); `certainty` never multiplies into
`magnitude` (a strong *inferred* signal ≠ a strong *measured* one — downgrade-only).

## 4. The six prioritized moves

Ordered by cross-lens weight × cheapness (all four information/representation lenses concur):

1. **Wire the killer/opposing signals** (0 of 32 consumed). Pure over-compression; the signals are
   already emitted — routing them is the cheapest distortion reduction.
2. **Partition `availability` into open-world vs closed-world → different ACTIONS.** Ignorance
   (`not_wired`/`data_blocked`/`read_error`) → `ACQUIRE` (emit an `acquisition_actions[]` backlog);
   measured-negative → `KILL`; add a `conditional_pass` action that *names the resolving datum*.
   5/10 conflating resolvers → 10/10. **Highest-value single fix.** Record invariant: an
   open-world `availability` forces `finding.state = unknown` (a `not_wired` record carrying a
   `direction` fails validation).
3. **Certainty as a mandatory coordinate on all 10 axes**, whose job is to **coarsen resolution**
   (thin cohort ⇒ degrade to a coarser level or `conditional_pass`, never a crisp pass).
4. **Modality → `verdict_by_modality` vector** (sparse: one base action + only channels that differ,
   each difference traceable to a named discriminator: allele-selectivity, endocytosis,
   essential-normal-tissue, E3-substrate). Gate becomes modality-indexed. *Gate the build on
   measuring the modality-divergence rate first (§6, metric I5) — if channels rarely diverge on the
   calibration set, the vector isn't worth its rate.*
5. **Coarsen `magnitude` to boundary-aligned bins; demote inert rules to a display channel.** Default
   `{below_gate, above_gate}` + a `borderline` bin only inside the near-threshold band and only when
   n supports it. Replace the `ratio == 1.0` veto with a banded rule.
6. **De-bias the composition.** Match-all-then-reduce (not first-match) → no silent masking + no
   order bias; `no_data` is **gate-inert** (not a soft-negative) → kills availability bias
   ("well-studied" leaking in as "good"); de-duplicate correlated evidence (the 6 shared cards +
   TCGA↔GENIE / CRISPR↔RNAi pseudo-replication) so corroboration isn't inflated.

## 5. The scorecard — objective made measurable (label-free, CI-able)

Two panels; keep the aggregates **separate** (a layer can be *faithful-but-thin* or *rich-but-lying*).
All computable from the YAML + resolver-replay over the calibration runs — no fitting.

**INFORMATIVE** (retention / VOI / warrant):
- **I1 Signal-sink coverage** — consumed / emitted signal pairs *(baseline 0/32)*.
- **I2 Sufficiency retention** — distinct decisions produced ÷ decision-equivalence classes of an
  expert reference fold `d*`.
- **I3 Per-coordinate decision-flip rate (VOI)** — resolver-replay; flip≈0 ⇒ demote to annotation.
- **I4 Warrant-carrying rate** — verdicts with full `{availability, provenance_class,
  corroboration, directness}` *(baseline ~0.1)*.
- **I5 Modality-divergence rate** — run FIRST; tests whether the modality vector earns its rate.

**REPRESENTATIVE** (faithful / unbiased / not false-precision):
- **R1 Scale-fidelity** — count interval→nominal coercions; **fabrication flags** (equality/hard
  cut on a continuous field, e.g. `== 1.0`) → target 0.
- **R2 Ignorance/Negation separation rate** — resolvers routing open-world vs measured-negative to
  distinct actions *(baseline ~0/5 → 10/10)*.
- **R3 Honest-abstention rate** — open-world axes emitting non-committal, not directional → 1.0.
- **R4 Availability-bias index** — Gini of coverage across axes × decision-weight; flags
  high-weight/low-coverage axes (safety predicted).
- **R5 Over-precision audit** — emitted levels vs levels that ever flip a decision.
- **R6 Order-bias / masking** — silent-flip count + permutation sensitivity → 0.
- **R7 Certainty coverage / laundering collisions** *(baseline 1/10)*; same-token-different-provenance
  ⇒ different record.

`faithfulness = harmonic_mean(R1..R7)` (one low ⇒ unfaithful in a specific way);
`informativeness = {I1..I5}`.

### 5.1 Empirical baseline (Phase-0b, n=36 calibration targets, `--no-synthesis --verdict-only`)

Replay over 36 composed nominations (caveat: n=36, directional not precise):

- **Effective rank ≈ 4.** The 11 verdict gates behave like **~4.0 independent axes** (participation
  ratio of the Cramér's-V gate-association matrix). Strongest co-variation: genomic~safety 0.64,
  safety~tractability 0.63, dependency~mechanism 0.63, surface~tractability 0.63 — mapping onto the
  6 shared-input cards. **Consequence:** summing 11 gates as independent corroboration overstates
  confidence by ~2.5× → validates move #6 (de-dup correlated evidence).
- **Modality split is justified at SM-vs-biologics, not ADC-vs-TCE.** `verdict_by_modality` would
  diverge from a scalar for **25/36 (69%)** of targets on the small-molecule-viable vs
  biologics-viable axis, but only **3/36 (8%)** on ADC-vs-TCE. → Build move #4, but prioritize the
  SM/biologics channel split; the ADC/TCE sub-split is low-value.
- **Availability bias is structural, not incidental.** 121/396 (31%) of gate-verdicts abstain, and
  it is concentrated: `synthetic_lethal_partners` and `subtype_fit` abstain **36/36**,
  `differentiation` 24/36, `selectivity` 16/36 — while dependency/genomic/tractability/safety almost
  never abstain. So the nomination is effectively driven by the ~7 always-present axes; ~2 contribute
  zero. This conflation of "not run / not wired" with "no data" is itself the R2 defect → validates
  moves #2 (availability as first-class actions) and #6 (`no_data` gate-inert).

Static baselines (from `p0_scorecard.py`): I1 = 0/32; verdict-inert = 270/393 (68%); R6 worst fan-in
safety 9→1 / genomic 8→1; R4 = 6 cross-gate cards; R7 = 1/10.

## 6. Migration — strangler-fig with the token as invariant

1. **Shadow.** Compute the record in parallel; emit into `decision.json.claim_vector_shadow`;
   consume nothing. Goldens untouched.
2. **Prove `ρ(record) ≡ legacy_token`** on the ~40-target calibration set, all axes, byte-for-byte.
   Any mismatch is a migration bug (or a latent first-match-order artifact to adjudicate with a
   domain expert).
3. **Swap the source** of `decision.json.verdict` to `ρ(record)`; hashes don't move; retire the
   ladder to a test oracle.
4. **Earn new distinctions deliberately** — split `insufficient`, add `verdict_by_modality`, coarsen
   magnitude. Each is a reviewed golden-rebless, one axis at a time, with the calibration set as the
   diff surface.

Rollback at any step = read the ladder; the record is additive throughout.

## 7. Scope, deferred layers, constraints

- **Relational side-structure (typed graph)** — for what a per-axis vector *can't* hold: SL partner
  identity, "a better-leveraged neighbour exists" (node-leverage), co-mutation partner+pathway, the
  MoA→modality wiring (31-class ontology currently read by zero rules), and cross-gate shared-card
  de-dup. A **separate workstream**; the factored record handles everything else.
- **Probabilistic (shared-parent) layer** — the only correct fix for the 6-card cross-gate
  double-counting + calibrated uncertainty, but n≈40 can't fit CPTs and byte-identical floats are
  unachievable → **deferred** unless correlation/uncertainty becomes the priority.
- **Interpretable decision manifold (portfolio layer)** — target-as-point in
  conviction×window×deliverability. **Deferred**: no learned combiner at n≈40; revisit at ≫200
  labeled targets. Its collinearity diagnostic (participation ratio) is still useful as a
  redundancy read for R4.
- **Constraints honored throughout:** determinism, byte-stable golden tests, domain-expert
  PR-review, non-Turing resolver grammar. Every coordinate is card-emitted, expert-mapped, or a
  deterministic fold — nothing learned.

## 8. The modality-conditionality fix chain (worked from the KRAS safety case)

An information-theoretic audit of KRAS/COADREAD safety (H(safety token)=2.55 bits cohort-wide;
H(driving_rule|token)=0.41 bits) showed the token-naming collapse is **minor** — the real loss is
that the safety axis **never encodes modality**, so the decision-flipping bit ("safe as an
allele-selective G12C inhibitor, WT-constraint HOLD as a degrader") is not recoverable by refining
the token. The variable the concern conditions on — *does the agent engage/deplete WILD-TYPE
protein?* — is absent from the representation, and `safety.resolver.yaml` improvises it from a GoF
role proxy. **The fix must move upstream, in order:**

- **Layer 0 — modality carries the property.** `wt_engagement ∈ {engages_wt, conditional,
  not_applicable}` on every modality in `modality.enum.yaml`. ✅ **DONE** (branch
  `feat/modality-wt-engagement`; all contracts-validate gates pass). Additive/inert until Layer 2.
- **Layer 1 — rules author per-channel modality-relevance.** The WT-loss safety rules must stop
  painting `small_molecule==degrader` uniformly. Needs either a rule-level `modality_conditionality`
  marker (a schema addition to `interpretation_rules.schema.json`, currently
  `unevaluatedProperties:false`) or a derived mapping keyed on the Layer-0 property. NOT a signal
  rewrite — the `small_molecule` channel is `conditional` (allele-selectivity is agent-level), so
  the concern is marked WT-engagement-conditional, not flipped to neutral.
- **Layer 2 — composition emits `verdict_by_modality`.** Evaluate all channels: a WT-loss concern
  opposes `engages_wt` channels, is `not_applicable` on surface, and is surfaced as
  "applies to pan-inhibitors; allele-selective agents spare WT" on the `conditional` SM channel.
  **Delete the 6 role-proxy downgrade rungs** in `safety.resolver.yaml` — the property now does the
  work explicitly.
- **Layer 3 — decouple fact from choice.** GoF role stays a biology finding (makes allele-selectivity
  *eligible*), but no longer silently downgrades safety.

**Ordering matters: `verdict_by_modality` (Move #4) cannot be built before Layers 0–1** — it has no
correct inputs until the property exists and rules declare applicability. Upstream-before-vector.

### 8.1 Assessment — what else is affected (scan of all rules + resolvers)

- **Uniform `small_molecule==degrader` signals span 17 rules, but only ~9 are genuinely
  WT-engagement-conditional:** the 5 germline WT-loss warnings (`highly-constrained-safety-warning`,
  `gene-burden-lof-safety-warning`, `clingen-dominant-loss-safety-warning`,
  `mouse-ko-lethal-safety-warning`, `clinvar-germline-pathogenic-safety-warning`), the 3
  pan-essential/broad-tox (`pan-essential-killer`, `rnai-pan-essential-killer`,
  `pan-essential-broad-tox-safety-warning`), and `normal-tissue-protein-liability-safety-warning`.
  Plus `gene-burden-protective-favorable` — WT-engagement-relevant but **inverted** (LoF
  population-protective ⇒ `engages_wt` is *supportive*). The remaining ~8 are NOT this pattern and
  must be left alone: SL rules (`combo-*-synthetic-lethal`), soft-neutral gnomAD rungs
  (`moderately-constrained`, `constraint-data-unavailable`), and TSG/LoF-role rules — all correctly
  modality-uniform.
- **Faked modality-conditionality is confined to `safety.resolver.yaml` — exactly 6 rungs**
  (`wt_constraint_mechanism_mismatch` + 5× `wt_human_genetics_mechanism_mismatch`), all conditioning
  on `[activating-driver-role-safety-context, oncogene-role-safety-context]`. No other resolver fakes
  modality from role. These 6 are what Layer 2 deletes.
- **No category errors.** WT-loss concerns correctly omit surface channels; the lone surface-painting
  LoF rule (`modality-matrix-lof-role-surface-antigen-loss-opposing`) is a legitimate
  antigen-loss-on-downregulation concern, correctly on `{adc,bite_tce,antibody}`.
- **Surface already handles modality-specificity** (the recent bite_tce-only TCE-unsafe killers), so
  the surface axis is ahead; the **intracellular WT-loss axis is the one that lags** and is the
  scope of Layers 1–3.
