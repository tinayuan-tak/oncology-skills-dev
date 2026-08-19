# Changelog — tumor-selectivity

The `version` in [SKILL.md](SKILL.md) and `SKILL_VERSION` in
[scripts/run.py](scripts/run.py) must always match (guarded by
`skills/tests/test_version_parity.py`); bump both together and add an entry here.

## 1.11.0
- Added `tumor-protein-abundance-cptac` as an 11th card — an RNA→PROTEIN tumor-vs-normal
  CORROBORATION arm (verdict-INERT). Projects `protein_tumor_vs_normal_effect_size` +
  `protein_tumor_vs_normal_q_value` (CPTAC per-cohort TMT-MS,
  `cptac-protein-tumor-vs-normal-per-cohort-v1`) plus a derived, spine-inert
  `rna_protein_tvn_concordance` (does the protein direction agree with the RNA call at BH q<0.05?).
  Closes the aggregate card's caveat #5 (RNA selectivity does not guarantee protein selectivity — the
  RNA-up/protein-flat false-positive). Feeds no resolver rung / no clamp: the `selectivity_class`
  verdict spine + normal-breadth veto are byte-identical (guarded by the CEACAM5/TACSTD2 replay).
  `data_unavailable` off the ~10 CPTAC cohorts (honest abstain).

## 1.10.1
- Productionization cleanup (behavior-preserving): consolidated the documentation and removed
  internal edit-tracking labels from all prior edits; moved the inline version history out of
  `run.py` into this file; single-sourced the axis-A "selective" set in `selectivity_hero.py` from
  `selectivity_veto.py`; consolidated repeated per-card summary lookups in `run.py::_headline`. The
  `decision.json` verdict spine + headline are byte-identical.

## 1.10.0
- Surfaced the `sc-normal-celltype-expression` card into the headline
  (`sc_normal_expression_class`, `sc_normal_safety_essential_class`,
  `sc_normal_max_detection_cell_type`/`_fraction`, `sc_normal_n_cell_types_above_20pct`). This card
  was already verdict-driving via the veto, but its descriptive output reached no
  `decision['headline']` consumer. Additive / display-only; the `selectivity_class` spine is unchanged.

## 1.9.0
- Single-cell + in-situ spatial coverage expansion (the tumor side of the selectivity question).
  Composed the tumor single-cell card (`tumor-scrna-celltype-expression`) + two in-situ spatial RNA
  cards (`spatial-region-rna-expression`, `spatial-tumor-normal-colocalization`) + the spatial protein
  card (`spatial-surface-protein-abundance`, which abstains where GeoMx panels are absent). All are
  verdict-inert additive facets: they surface the malignant-cell-intrinsic-vs-stroma + in-situ
  tumour-enrichment + normal-epithelium-adjacency evidence next to the bulk axis-A call, but feed no
  resolver rung and no clamp, so the `selectivity_class` spine is byte-stable. The malignant-vs-stroma
  signal is the intended input for the roadmap stromal-confound veto (see SKILL.md § Roadmap).

## 1.8.0
- The normal-breadth veto clamp was single-sourced into `_skills_common.selectivity_veto` and applied
  by the compose-dashboard engine (`compose_core.resolve_gate_spine`), closing the gap where the
  engine had resolved the raw resolver verdict without the clamp. No verdict change for the standalone
  skill (the clamp already ran here); the bump reconciled the emitted provenance with the SKILL.md
  contract, which had been drifting.

## 1.7.0
- SKILL.md doc-drift fixes (percentile-crossing, sc-normal, purity-confound, and surface-density all
  declared in `cards_used` / `measurement_types`).

## 1.6.0
- Added the absolute surface-density facet (`surface-abundance-density`): Tier-1 calibrated
  copies/cell + floor standing + modality-viability flags. Verdict-inert — below-floor is a modality
  caveat, not a downgrade (CD19 is the counterexample). `selectivity_class` byte-stable.

## 1.5.0
- Added the cell-type-resolved veto arm: `sc-normal-celltype-expression` with
  `sc_normal_safety_essential_class == critical_organ_liability` fires
  `tvn-sc-normal-critical-organ-veto` → downgrade. The third normal-breadth veto arm.

## 1.4.0
- Added the pan-normal window veto arm (`tvn-no-full-normal-window-veto`).

## 1.3.0
- The headline now emits the resolved (post-veto) verdict; added the purity-confound facet.

## 1.2.0
- Opt-in `--synthesize` selectivity-lens narrator.
