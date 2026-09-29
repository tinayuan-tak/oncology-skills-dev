# Data → Card → Rule → Verdict Map (target-profile v1)

**The complete wiring of every target-profile dimension, end to end** — the working
reference for iterating on data→evidence→verdicts. Reflects the merged state after
the defensible-v1 sequence (2026-07-17). Companion to `FRAMEWORK_OVERVIEW.md` (the
concepts) and the per-card docs under `cards/`.

Portable GFM (compact tables + fenced ASCII; no Mermaid/HTML) per README format rules.

Reconstructed from a full 3-agent code trace; every row is grounded in the actual
sub-skill `_verdict`/`_snapshot`, the rules files, and the gate vocab. When you change
a verdict string, rule_id, or short key, the guard test
(`claude-oncology-skills/skills/tests/test_no_reference_drift.py`) enforces cross-map
consistency — run it after edits.

---

## At-a-glance: the 9 wired dimensions

| Phase | Sub-skill (short) | Data source | Card(s) → class field | Gate? | Risk-table? |
|---|---|---|---|---|---|
| A | tumor-presence (`expression`) | recount3 bulk RNA + DepMap expr | cellline-rna-distribution, tumor-rna-vs-adjacent, tumor-protein-abundance-cptac → `expression_class` | ✗ | biological (hi/lo only) |
| B | tumor-selectivity (`selectivity`) | recount3 4-cell DESeq2 (TCGA-adj ±ComBat, GTEx ±ComBat) | tumor-vs-normal-selectivity → `selectivity_class` | ✗ | biological |
| C | functional-requirement (`dependency`) | DepMap CRISPR (Chronos) + RNAi (DEMETER2) | pan-cancer-crispr/rnai-dependency-distribution, crispr-rnai-dependency-concordance, dependency-lineage-selectivity, paralog-buffering → `dependency_class` | **✓ veto** | biological |
| D | mechanism-and-pharmacology (`mechanism`) | SIGNOR + CollecTri + Reactome + kinome-atlas (composed) | signaling-network-mechanism → `network_class` | ✗ | ✗ |
| A/E | genomic-alteration-profile (`genomic_alteration`) | DepMap MAF/Chronos/CN + GDC MC3 hotspot | mutation-type-counts, mutation-stratified-dependency, mutation-hotspot-frequency, copy-number-distribution, (fusion placeholder) → `mutation/cn_class` | ✗ | biological (partial) |
| E | differentiation-landscape (`differentiation`) | TCGA MC3 + GENIE Fisher (panel-intersect) | co-mutation-and-mutual-exclusivity → `cooccurrence_class` | ✗ | ✗ |
| F | tractability-small-molecule (`tractability_sm`) | DepMap PRISM + predictability precompute | prism-compound-activity, prism-crispr-concordance, dependency-predictability → `prism/concordance/predictability_class` | ✗ | druggability |
| F | surface-modality-fit (`surface_modality`) | surfaceome/structure products (3/5 not on S3) | surface-topology-and-ptm, surfaceome-family, structure-features, surface-abundance, adc-tce-modality-fit | ✗ | ✗ |
| G | on-target-safety-liability (`safety`) | gnomAD LoF constraint | gnomad-lof-constraint → `constraint_class` | **✓ hold** | safety |
| (opt) | subtype_fit | DepMap subgroup panorama | subgroup-stratified-dependency (+ mutation-frequency) → `per_subgroup_metrics` | **✓ hold** | ✗ |

`✓ veto`/`✓ hold` = this dimension can move the deterministic nomination gate. Only
**dependency, safety, subtype** gate the verdict; the other 6 are advisory (LLM
narrative + risk table) UNLESS they raise the positive tier (below).

---

## The verdict vocabularies (what each sub-skill can emit)

Each sub-skill's `_verdict()`/`_snapshot()` (in `<skill>/scripts/run.py`) is a
rank-ordered rule_id → verdict-string map. The full emitted vocabulary:

- **expression**: broadly_high_expression, strongly_upregulated_in_tumor,
  lineage_restricted, modestly_upregulated_in_tumor, broadly_moderate_expression,
  broadly_low_expression, not_informative, data_unavailable, insufficient
- **selectivity**: strong_tumor_selective, modest_tumor_selective,
  discordant_across_comparators, not_selective, not_informative, data_unavailable,
  insufficient
- **dependency**: pan_essential_killer, concordant_dependent, lineage_selective,
  selective_dependent, discordant, non_dependent, broadly_dependent, insufficient
- **mechanism**: well_characterized, partial, sparse, has_pd_marker, data_unavailable,
  insufficient  *(precedence 2026-07-17: network-shape before has_pd_marker)*
- **genomic_alteration**: biomarker_stratified_dependency, moderate_biomarker_dependency,
  missense_dominant_pattern, lof_dominant_pattern, recurrent_amplification_driver,
  recurrent_deletion_driver, recurrent_fusion_driver, multi_class_driver, mixed_pattern,
  passenger_pattern, insufficient
  *(T1.1 2026-08-09: recurrent_{missense,lof}_driver → {missense,lof}_dominant_pattern — those*
  *fire on variant-CLASS composition, not patient recurrence. T1.3: + recurrent_fusion_driver*
  *from the fusion-rearrangement landscape, a true sample-recurrence driver.)*
- **differentiation**: both_patterns_present, strong_mutually_exclusive, strong_cooccurring,
  has_cooccurring_driver, modest_cooccurring, modest_mutually_exclusive, ns,
  data_unavailable, insufficient
- **tractability_sm**: well_covered, chemically_confirmed_genetic, chemically_active,
  clinical_precedent_only, tool_compound_only, weakly_active, measured_potent_ligand,
  structurally_ligandable, structurally_intractable, discordant, chemically_unhit, insufficient
  *(T1.2 2026-08-09: + clinical_precedent_only — phase-1+ compound annotated, NO measured PRISM*
  *activity. T1.1: discordant reordered above the retrospective chemical-activity rungs. T3.1:*
  *+ measured_potent_ligand — a potent (<=1 uM) MEASURED chemotype series from ChEMBL/BindingDB,*
  *between the chemical-activity tier and the structural tier; weak measured activity -> structurally_ligandable.)*
- **surface_modality**: adc_preferred, tce_preferred, both_viable, neither_viable,
  modality_ambiguous, isoform_dependent_undefined,
  adc_preferred_tce_unsafe, tce_unsafe_normal_liability, surface_viable_density_caveated,
  shed_dominant_opposed, insufficient (surface_intrinsic axis)
  *(2026-08-09 modality-fit review: corrected stale adc/tce_favorable → *_preferred; + 4 safety/*
  *density/shed combination verdicts that let the cards' KILLER/downgrade signals refine the*
  *topology-only fit_class. All NON-NOMINATING foreclosure/caveat refinements.)*
- **safety**: highly_constrained_safety_concern, moderately_constrained_safety,
  tolerant_reduced_safety_risk, data_unavailable, insufficient
- **subtype_fit** (opt-in via `--subtypes`): subtype_specific_non_dependence, None

---

## The aggregation layer — where verdicts land

### 1. Nomination gate (KILL-only, one-directional) — `nomination_verdict_gate.yaml` `gates`
```
(dependency, pan_essential_killer) → veto
(dependency, non_dependent)        → veto     [CRISPR only; RNAi-only excluded, 2026-07-17]
(safety, highly_constrained_safety_concern) → hold
(subtype_fit, subtype_specific_non_dependence) → hold
```
Resolution: max severity (veto > hold). Conservative-complete fallback (missing vocab
still fires vetoes). Only these 4 (sub_skill, verdict) tuples move the action.

### 2. Positive tier (confidence FLOOR, F1-safe) — `nomination_verdict_gate.yaml` `positive_signals`
Computed ONLY when no kill fired (else-branch). Writes only `confidence`, never the
action. dominant: dependency:concordant_dependent, selectivity:strong_tumor_selective,
tractability_sm:{well_covered, chemically_confirmed_genetic}. supportive:
dependency:{lineage_selective, selective_dependent}, selectivity:modest_tumor_selective.
`strong` = ≥1 dominant + ≥2 dims + no contradiction; `moderate` = ≥1 dim.
Contradictions (block strong): not_selective, discordant_across_comparators,
dependency:discordant, broadly_dependent, tractability_sm:{discordant, chemically_unhit}.
Empty-fallback (missing vocab → no tier, never spurious strong).

### 3. Six-category risk table — `_risk_by_category_from_sub_verdicts()`
- **biological** ← expression/selectivity/dependency/genomic_alteration:
  LOW if any of {strong_tumor_selective, concordant_dependent,
  biomarker_stratified_dependency, broadly_high_expression}; HIGH if any of
  {not_selective, non_dependent, broadly_low_expression}; MEDIUM if
  discordant_across_comparators; else mixed/insufficient.
- **druggability** ← tractability_sm: well_covered/chemically_confirmed_genetic → LOW;
  chemically_active → LOW-MEDIUM; measured_potent_ligand → LOW-MEDIUM (a potent measured chemotype
  series — a real chemical start point); clinical_precedent_only → MEDIUM (annotation-only clinical
  anchor, no measured activity); tool_compound_only/weakly_active → MEDIUM-HIGH;
  chemically_unhit/discordant → HIGH.
- **safety** ← safety: highly_constrained_safety_concern → HIGH;
  moderately_constrained_safety → MEDIUM; tolerant_reduced_safety_risk → LOW.
- **translational / clinical / commercial** → hardcoded `insufficient_evidence`
  (no wired source; translational/clinical = placeholder phases, commercial = no
  licensed market data). Literature would fill these but is deliberately kept OUT of
  the verdict (see RISK_ASSESSMENT_INTEGRATION.md).

### 4. LLM synthesis
Everything (all sub-verdicts + card summaries) is fed to the single Bedrock call as
text; the LLM writes narrative + proposes recommendation/confidence, then the gate
clamps the action + the positive tier floors the confidence. Sub-verdicts are the
invariant audit spine; prose is a skin.

---

## Coverage + known gaps (the iteration backlog)

**Fully wired + firing on real data:** A (presence), B (selectivity), C (dependency),
D (mechanism), E-genomic, E-differentiation, F-tractability_sm, G-safety.

**Data-blocked** (dispatcher wired, derived product not on S3):
- surface-modality-fit: 3/5 cards (structure-features, surfaceome-family,
  cohort-ranking) → verdict `insufficient` until products land.

**Verdict-inert cards** (in a cards_used list but contribute no verdict):
- `mutation-hotspot-frequency` — no categorical class field, no rules; only its
  `overall_mutation_frequency` scalar surfaces (a headline number).
- `fusion-rearrangement-landscape` — placeholder, no dispatcher, always `_missing`.
- `dependency-predictability` — rules fire but no `_snapshot` branch consumes them.

**Known under-weightings / judgment calls (open for iteration):**
1. **Genomic under-weighting** — `_biological()` consumes only 1 of genomic_alteration's
   10 verdicts (`biomarker_stratified_dependency`). The 9 driver classes
   (recurrent_missense/lof/amplification/deletion_driver, multi_class_driver, …) do NOT
   feed biological risk — so an amplification-driven target (ERBB2) under-credits on the
   biological axis. Fix = widen `_biological()` to treat the driver classes as
   LOW-risk-supportive. **Deliberately deferred** (needs a biology decision on which
   classes count).
2. **6 of 9 dimensions are advisory-only** — mechanism/genomic/differentiation/
   tractability/surface/expression don't gate the verdict (only feed positive tier +
   risk table + LLM). By design (kill-only gate + positive-floor), but the boundary is
   worth revisiting per dimension.
3. **Placeholder phases** — combo-and-resistance (I), translational-readiness (J) are
   stubbed (no cards/data). Clinical/commercial risk rows are permanent placeholders.

**Provenance/doc drift (cosmetic, tracked):** mechanism card claims SIGNOR-only but data
is a 4-source union; PRISM activity card pins v3 while dispatcher reads v4.

---

## How to iterate safely

- **Change a verdict string / rule_id / short key** → run
  `skills/tests/test_no_reference_drift.py` (asserts no dangling references) +
  `tests/vocabularies/test_nomination_verdict_gate.py` (positive/kill/contradiction
  disjointness).
- **Add a card** → new method reader + card YAML (9 required fields) + dispatcher entry
  in `_live_readers.py` + (optionally) rules. Card is the contract; keep it thin.
- **Make a dimension gate the verdict** → add a `(sub_skill, verdict) → action` row to
  `gates` (stay one-directional / cross-target per the curation principle) OR a
  `positive_signals` entry (confidence floor only).
- **Card class-vocab MUST match its reader's emitted values** (the paralog drift lesson).

## Cross-references
- `FRAMEWORK_OVERVIEW.md` — the four repos, two engines, signal grammar, guard rails.
- `nomination_verdict_gate.yaml` — the authoritative kill + positive policy.
- `RISK_ASSESSMENT_INTEGRATION.md` — why literature stays out of the verdict.
- per-card docs under `cards/`; per-skill `SKILL.md` composition blocks.
