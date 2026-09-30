# Evidence-property envelope — v0 (DISPOSABLE)

**Status:** v0, deliberately boring, disposable. Extracted (not invented) from the four landed
cross-source concordance claims. Epic: claude-oncology-skills#1507 (L2b-5, #1629). Follows the F
inventory (`PROPERTY_MAPPING_COVERAGE_INVENTORY_2026-09-25.md`) and the #1507 reframe
(issuecomment-5834901882) + refinement addendum (issuecomment-5835153813).

> This doc records a contract the code **already obeys at n=4**. If a foreign family cracks it, the
> crack is the result — amend this doc, do not defend it against the biology.

## What the envelope is (and is not)

It is the **smallest common shape** shared by purpose-built, deterministic, cross-source *integrated
property claims* (layer L2b). It is **NOT** a per-family schema and **NOT** a universal record spine —
F settled that fields are the wrong fleet-wide unit (overall clean 20.1%). The forward architecture is
**property islands + this small common envelope**, canonicalized *only* for purpose-built cross-source
single-fact properties, never retrofitted onto emitted classifiers.

Its whole job, and nothing more: *identify the biological property, identify the grain, expose
source-level resolved evidence, declare source dependence, preserve the quantitative evidence, and
record how the integrated claim was deterministically produced.* If it can do that across
presence / dependency / safety / recurrence, that is the win.

**v0 stays boring.** It carries **no** `expected_relationship`, `biological_interpretation`,
`modality_relevance`, or `decision_weight` — those are downstream (L3 / decision-frame) concerns and
would smuggle a verdict into the inert layer.

## v0 minimum-viable shape

```yaml
property_claim:
  property_id:            # the biological property resolved (e.g. driver_recurrence)
  context:                # target × indication scope, when applicable
  grain:                  # the measurement grain — FIRST-CLASS (see §grain)
  source_support:
    - source:             # a stable per-source key (uniform shape across sources)
      value:              # the source's raw resolved token/class
      resolved:           # did THIS source resolve a trusted call?           (source notion 1)
      quality_eligible:   # may its value be USED for resolution / shown?     (source notion 2)
      corroboration_eligible:  # may it count as an INDEPENDENT replication?  (source notion 3)
      dependence_group:   # which independence group it belongs to (see §dependence)
      derived_from:       # for a DERIVED/superset source: the sources it is built from
      provenance:         # card_id / headline field it was read from
      retained_quantitative:   # raw numeric anchor demoted-not-deleted (percentile, effect size…)
  integrated_claim:
    state:                # the integrated class token (concordant / one-side-masks / discordant / …)
    corroboration:        # measured-arm tier over the INDEPENDENT arms only
    integration_method: explicit_deterministic   # NO llm_inference — L2b is reproducible by contract
  resolved_source_count:               # count of sources that resolved (INCLUDING dependent/derived)
  corroborating_independent_arm_count: # count of INDEPENDENT arms eligible to replicate (pooled excluded)
  provenance: { sources: [...], independence_note: ... }
# surface half (L3 surface-consumption, #1578/#1584/#1594) ADDS, never routes:
#   positive_signal · qualifying_signal · uniform source_support presentation map · boundary_sensitive
```

`integration_method` is always `explicit_deterministic`. The key is **omitted when the property is
unresolved** (byte-stable), so a target with no evidence adds no noise.

## The two counts and the three source notions (the dependence-aware core)

`n_sources` is **overloaded** and forbidden. The envelope carries **two counts**:

- **`resolved_source_count`** — how many sources produced a trusted read, *including* dependent /
  derived sources. This is the honest "how much did we see."
- **`corroborating_independent_arm_count`** — how many *independent* arms are eligible to count as
  replication. A dependent/superset source is **excluded** here.

and keeps **three separate source-level notions**, so no single overloaded boolean smuggles two
meanings:

| notion | question it answers |
|---|---|
| `resolved` | did this source resolve a trusted call at all? |
| `quality_eligible` | may its value be used for resolution / shown as evidence? |
| `corroboration_eligible` | may it count as an *independent* replication arm? |

**`dependent ≠ ignore`.** A dependent/superset source still contributes **evidence** (show it,
preserve it, may inform resolution) but **not** an additional unit of **independent corroboration**.
The canonical worked case is `pooled` recurrence (§recurrence): `resolved: yes`,
`quality_eligible: yes`, `corroboration_eligible: no`. It is preserved in `source_support` and counts
toward `resolved_source_count`, but never toward `corroborating_independent_arm_count` and never
enters the corroboration tier.

## Grain is first-class

Grain was **enforced but not represented** at n=4: abundance's `_ABUNDANCE_GRAINS`
(`presence_claims.py`) guards patient-vs-model at **build time** — RNA only pairs with same-grain
protein so a magnitude disagreement is never confounded with a tumor-vs-model context difference — but
never *emits* grain as a claim attribute (F caveat §5). v0 makes `grain` an explicit slot.

Grain has facets, and different families exercise different ones:
- **sample-context** (patient tumour / cell-line model / normal tissue) — abundance guards this at build time.
- **assay-modality** (bulk RNA / single-cell RNA / MS-protein / IHC / exome / panel).

A claim must not equate reads across an unstated grain boundary (e.g. a panel-restricted denominator
is not exome-comparable — see recurrence).

## Dependence is relational, never a global boolean

Independence is a property of a **pair/group of sources**, not intrinsic to one source: MC3 ⊥ GENIE,
but `pooled` is dependent *with respect to both*. A global `independent: true/false` is known to fail
the moment sources partially overlap (also: multiple RNA datasets from overlapping cohorts; RNA +
protein from shared samples). So dependence is declared as a **structure**, e.g.:

```yaml
evidence_dependence:
  groups:
    - { members: [mc3_exome],  relationship: independent_cohort }
    - { members: [genie_panel], relationship: independent_cohort }
  derived_sources:
    pooled: { derived_from: [mc3_exome, genie_panel], corroboration_eligible: false }
```

At n=4 every source was independent, so this structure was **degenerate** (all singleton groups, no
derived sources) and stayed implicit inside `corroboration_from_arms` (which simply drops `None`
arms). Recurrence is the **first family with a genuinely dependent source**, which is exactly why it
was chosen — it forces the dependence slot to earn its place.

## Type-integrity invariant (system-wide, machine-checkable)

> **An evidence object may not be consumed downstream as a stronger epistemic type than it was emitted
> as.**

Concretely: `measurement ≠ integrated property` · `local-composite ≠ atomic property` ·
`unresolved ≠ neutral` · `dependent evidence ≠ independent corroboration` · `L3 interpretation ≠ L2
fact`. This is the invariant the typed consumption interface (G) will enforce; the **envelope is where
its source side is declared** (via `corroboration_eligible`, `derived_from`, and the two counts). It
is the same discipline as the `gap ≠ absent` rule (`claim_vector_core`) lifted to the source layer.

## The four claims instantiate the envelope

| Envelope slot | coverage (`presence_claims.py:473`) | essentiality (`dependency_claims.py:358`) | normal-liability (`safety_claims.py:435`) | abundance (`presence_claims.py:735`) |
|---|---|---|---|---|
| `property_id` | bulk↔sc coverage | crispr↔rnai essentiality | normal-tissue liability | rna↔protein magnitude |
| `state` | `coverage_concordant` / `bulk_masks_low_coverage` | `…_concordant_{dependent,nondependent}` / `…_assay_discordant` / `…_single_assay_only` | `liability_concordant_{high,low}` / `…_assay_discordant` / `…_single_source_only` | `abundance_concordant` / `rna_high_protein_low` / `rna_low_protein_high` |
| `source_support` | uniform 2-source map | `assay_support` + `selective_assays` | `flagged/read_clean` map | per-source rank+magnitude list |
| `corroboration` | `_corr_from_arms([True, escape_arm])` | `corroboration_from_arms([crispr_arm, rnai_arm])` | `corroboration_from_arms([3 arms])` | `_corr_from_arms([True, cross-grain arm])` |
| `integration_method` | `explicit_deterministic` | `explicit_deterministic` | `explicit_deterministic` | `explicit_deterministic` |
| grain | tumour (bulk+sc) — implicit | pan-cancer cell-line — implicit | normal tissue, multi-assay — implicit | **explicit build-time guard** (patient/model) |
| dependence | all independent (degenerate) | CRISPR ⊥ RNAi (degenerate) | 3 independent assays (degenerate) | cross-grain arms independent (degenerate) |
| key omitted when… | **neither** source resolves (emits nothing on single arm) | neither assay resolves (**emits** `single_assay_only` on one) | no source resolves (**emits** `single_source_only` on one) | **no grain** resolves both modalities (emits nothing on single modality) |

**Slots that don't yet fit uniformly (recorded, not forced):**
1. **The single-source emit boundary is not uniform.** coverage + abundance **omit** the key on a
   single arm; essentiality + normal-liability **emit** a degraded `single_*_only` read. This is a
   real per-family choice, not envelope drift. Recurrence follows the **emit** variant (see below) so
   the `resolved_source_count ≠ corroborating_independent_arm_count` case is *surfaced*, not hidden.
2. **`grain` and the two counts / dependence structure were latent at n=4** — enforced (grain) or
   degenerate (dependence, all-independent) but never emitted. Recurrence promotes both to explicit,
   first-class slots. This is the envelope *learning something real* from a foreign family, exactly
   the intended outcome.

## Promotion ladder — where recurrence sits

| Rung | Envelope state | Reached by |
|---|---|---|
| 1 | **Observed** — described from n=4, no contract | done (#1507 reframe comment) |
| 2 | **Declared-v0** — written as this doc | **#1629 Phase 0 (this doc)** |
| 3 | **Provisional-conformance** — survives ONE out-of-neighborhood family | **#1629 Phase 1 (recurrence)** |
| 4 | **Multi-family-conformance** — 2–3 *structurally different* families conform (same-property independent replication AND dependent/superset evidence AND differing grain / multi-assay all exercised — e.g. + genomic-instability or surfaceome) | *future family issues* |
| 5 | **Contract-enforced** — a guard requires new concordance claims to instantiate the envelope | *future — DO NOT file until rung 4* |
| 6 | **Consumed via typed interface** — frames read islands as typed inputs (G) | unblocked, unfiled |

**One foreign family surviving earns nothing on its own** — recurrence *could* just happen to fit.
Enforcement (rung 5, the open-registry-with-maturity-states from the original design) is deferred
until **2–3 structurally different families** have conformed (rung 4), and is **not** to be filed
alongside #1629. This is stated here so a future session does not over-reach into a universal registry
on the strength of one conformance pass — the failure mode this whole reframe exists to avoid.

## Recurrence (#1629 Phase 1) — the first conformance test

`recurrence_concordance` on `genomic_claim_vector` integrates **MC3 exome**
(`driver_recurrence_class`) × **GENIE panel** (`genie_driver_recurrence_class`) as the two independent
cohort arms (`dependence_group: mc3` / `genie`). `pooled_driver_recurrence_class` is a **declared
dependent superset** (`derived_from: [mc3, genie]`): `resolved: yes`, `quality_eligible: yes`,
`corroboration_eligible: no` — shown and preserved, never a third independent arm. It replaces the
`_recurrence_class` `pooled OR driver` collapse (`genomic_claims.py:232`) — the exact
superset-as-fallback anti-pattern F named.

- **grain:** MC3 and GENIE are both patient-cohort variant reads (same sample-context grain), but
  panel-coverage-corrected-vs-exome is a real comparability caveat carried in
  `provenance.independence_note`; a panel-restricted denominator is never equated with exome.
- **two counts:** `corroborating_independent_arm_count` counts MC3 + GENIE only (max 2);
  `resolved_source_count` may be 3 — `pooled` must never inflate corroboration.
- **emit / M3:** emits when ≥1 independent arm resolves; one arm → `single_source_only` (degraded,
  corroboration `single_arm`); key omitted only when **neither** MC3 nor GENIE resolves — and
  `pooled` never resurrects it. Defeating one arm only degrades; defeating **every** independent arm
  omits the key (the mutation test must defeat every supply path).

If recurrence had fit only after ten special-case fields, it would be a different island class and the
envelope should not generalize that far. It fits after promoting exactly two latent slots (grain,
dependence structure + two counts) to first-class — so the envelope **learned something real** and
reaches **rung 3 (provisional-conformance)**.

## Envelope v1.1 — two additive fields (SK#2210 Wave-0c)

**Status:** both fields **declared here**; exactly one is **implemented** in 0c. Additive only — v1.1
renames nothing, re-keys nothing, and removes no slot. Every v0 consumer keeps reading v0 records
unchanged, because both fields are **optional and omitted when they do not apply**.

Read the two together. They are halves of one idea: *before you may relate two arms, say whether they
were relatable, and say how each arm's value was arrived at.* v0 already carries the caveat as prose
(`provenance.independence_note`, and an `integration.comparability` block on **all 13** families in
`contracts/vocabularies/property_catalog/integrated_families.yaml`). v1.1 makes the first half
machine-readable. The second half is what a fold would have to read to honestly claim the *middle*
state — which is why the two are declared at once and implemented apart.

### (i) `comparability_state` — a gate PRIOR to the relation

```yaml
comparability_state: comparable | normalized_to_compare | non_comparable   # optional; omitted, never null
```

Governed as a closed, semver-additive vocabulary in
`contracts/vocabularies/comparability_state.enum.yaml` (validator:
`contracts/validators/validate_comparability_state.py`, wired into `contracts/scripts/preland.sh`
including the token-level `--additive-against` check). It answers a question **logically prior** to
`concordance_class`: *was the comparison legal at all?* `concordance_class` reports what the fold
**found**; `comparability_state` reports whether the fold was **entitled to look**. Conflating them is
why this is a separate slot and not a fourth concordance token.

What it is **not**: not a quality score, not a confidence, and **not a statement about independence** —
`dependence_group` / `derived_from` already carry that, and two arms can be fully independent and still
not comparable (that is precisely the exome-vs-panel case).

**The criterion**, stated once so 13 families do not become 13 opinions:

- `normalized_to_compare` requires an **explicit transformation applied to the arms' values** placing
  them on a shared scale or vocabulary. **Narrowing the question is not a normalisation** — comparing
  only signs, dropping to the coarsest question both arms can answer, or using a scale-free estimand is
  `comparable`, because nothing was transformed.
- `non_comparable` is declared where a **reachable case exists** in which the arms may not be equated.
  It is a **per-case** value, not a verdict on the family — which is why 4 of 13 families declare both
  `comparable` and `non_comparable`.
- Omit the key entirely when **no comparison was attempted** (e.g. `single_source_only`). There is no
  relation to gate, so there is no state; a default here would claim a licence never exercised.

**Declaration is not emission.** All 13 L2b families declare a state, read from catalog prose. Exactly
**one family emits** it in 0c — `recurrence_concordance`
(`skills/_skills_common/genomic_claims.py`), keyed on the **GENIE arm's resolved direction**:

| `concordance_class` | `comparability_state` |
|---|---|
| `recurrence_concordant` | `comparable`, or `non_comparable` where GENIE reads `not_recurrent` |
| `panel_masks_recurrence` | `non_comparable` |
| `exome_masks_recurrence` | `comparable` |
| `single_source_only` | *key omitted* |

The asymmetry is the point, and it is read off v0's own caveat above (lines on grain and the panel
denominator): a panel **calling** a variant recurrent is evidence in either cohort, whereas a panel
**failing** to call it may only mean the panel never looked. So "GENIE says not recurrent" is where the
denominators cannot be equated. The gate keys on that **direction**, never on the class name.

Enforcement: the rung-5 conformance guard
(`skills/_skills_common/tests/test_rung5_envelope_enforcement.py`) validates the slot **when present**
against the governed roster and rejects a null, an unregistered token or a near-miss. That check is
structurally blind to a key that should be **absent**, so the omission contract is enforced separately
by `skills/_skills_common/tests/test_comparability_state_coverage.py`, which drives the builder over its
full input cross-product and reconciles emitted against declared pairs with `<OMITTED>` as a first-class
member. Both halves were proven able to fail by planting mutants; the non-omission mutant was found to
be a **live hole** that way.

**Corrected against the 0c plan, measured:** the plan called exome-vs-panel "a genuine
`normalized_to_compare` case". It is not — the builder normalises nothing and its `independence_note`
explicitly **declines** to equate the denominators, so recurrence is a `comparable` / `non_comparable`
family. But the middle token is not hypothetical either: `integrated_families.yaml` already names
`abundance` a `normalized_to_compare` case verbatim, and under the criterion above 3 of 13 families
instantiate it. It is therefore **declared-and-instantiated but unemitted**, recorded as such in the
enum's `documented_not_emitted` block and pinned by a test in both directions.

### (ii) `interpretation` — per-entry resolution provenance (declared only; **not** implemented in 0c)

```yaml
interpretation:            # optional, on an L2a source entry
  function_id: <module_qualified_resolver>   # e.g. expression_properties.resolve._magnitude
  version: <semver>                          # bumped when the resolver's disjuncts change meaning
  disjunct_fired: <stable_token>             # WHICH branch produced the value
```

The gap it closes, concretely. `methods/onc_methods/expression_properties/resolve.py:120` `_magnitude`
returns `high` from a **three-way OR** (`control_target_percentile` ≥ threshold **or**
`median_log2tpm_panel` ≥ threshold **or** `fraction_highly_expressed` ≥ threshold). Downstream sees
`high` and cannot tell which disjunct fired — so it cannot tell whether two arms both reading `high`
agree on anything beyond the label. Every L2a resolver of this shape loses the same information.

Why it is declared but not built here: **implementation belongs to #2227**, which is filed and
**blocked** — populating `interpretation` on tumour-presence entries changes the published artifact, and
the tumour-presence golden is owned by #2061 and #1984 PR-B. 0c regenerates no golden, so it declares
the shape and stops. The ownership record is in
`contracts/vocabularies/property_catalog/tumor_presence.yaml` (`governance.ownership`).

**The two fields are coupled, and that is the reason to declare them together.** A fold cannot honestly
emit `normalized_to_compare` until it can read its inputs' `interpretation`: claiming a transformation
placed two arms on a shared scale is a claim about *how each arm's value was produced*, and today that
is unrecoverable from the value alone. So the state that no family emits is exactly the state the
missing half would license — the enum is not carrying a dead token, it is carrying a token whose
enabling field is a filed, blocked issue.

### Ladder status, measured (the table above is stale)

Rung 5 says *"future — DO NOT file until rung 4"*. Both have since been reached:
`test_rung5_envelope_enforcement.py` carries `_EXPECTED_FAMILY_COUNT = 13` and asserts envelope
conformance across all 13 structurally different families, which is rung 4 passed and rung 5 built. The
table is left unedited because 0c renames and renumbers nothing; this note is the correction. The
caution the table was written to express still holds and 0c obeys it — v1.1 adds **no** family, bumps
**no** `_EXPECTED_FAMILY_COUNT`, and pilots emission in **one** family rather than declaring a universal
registry on the strength of one pass.
