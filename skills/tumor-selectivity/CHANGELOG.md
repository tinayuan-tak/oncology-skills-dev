# Changelog — tumor-selectivity

The `version` in [SKILL.md](SKILL.md) and `SKILL_VERSION` in
[scripts/run.py](scripts/run.py) must always match (guarded by
`skills/tests/test_version_parity.py`); bump both together and add an entry here.

## 1.13.0
- Promoted the `normal-tissue-protein-abundance-tphp` card from DISPLAY-only to a VERDICT-BEARING
  NORMAL-BREADTH veto arm (the 4th). Its new `tphp_normal_protein_liability_class == broad_and_abundant`
  fires `tvn-tphp-broad-abundant-normal-protein-veto`; the shared `selectivity_veto` clamp then
  downgrades an axis-A-selective call to `selective_with_normal_liability` (a SELECTIVITY-PRESERVING
  named liability, NOT the housekeeping KILL — same outcome as the sc-normal critical-organ arm).
- Gated on ABUNDANCE, not DIA detection (Floor-C): `broad_and_abundant` requires a BROAD count of adult
  tissues (>=35) each at/above a global per-tissue abundance floor (product p75). A broadly-DETECTED-but-
  not-broadly-abundant protein (CEACAM5: 63 tissues detected, 30 above floor) reads `detected_not_abundant`
  and does NOT fire — the deliberate DIA-detects-broadly-at-trace correction.
- Applied SKILLS-SIDE (no target-contracts resolver rung; a conjunction the single-rung resolver cannot
  express). Precedence: window > full-normal > sc-normal > tphp-normal-protein (a no-window KILL outranks
  the liability flag). Card moved DISPLAY-ONLY -> `rules_scope`; the 3 parity lists intact. Golden
  snapshot regenerated (selectivity gate rule_ids += the new rule; resolver treats it inert — verdicts
  unchanged, since the clamp is skills-side). Replay fixtures (CEACAM5/TACSTD2) refrozen.
- VERDICT-FLIP DELTA (panel): ZERO flips. CEACAM5/ERBB2/FOLR1/MSLN/EPCAM/TACSTD2 read
  detected_not_abundant/restricted (no fire); DLL3 data_unavailable; GAPDH fires but the window KILL
  outranks it; KRAS fires but is not axis-A-selective (clamp no-op). No approved antigen is downgraded.

## 1.12.0
- Added the canonical HEADLINE layer (verdict + confidence + top-tension), mirroring the merged
  tumor-presence / functional-requirement exemplars (docs/HEADLINE_CONTRACT.md). `_headline` now emits
  `headline_block` — a verdict-INERT projection over the resolved `selectivity_class` + the
  WIN/DIST/INT/SAFE `claim_vector` / `key_signals` (best-effort; a build fault degrades to
  `_enrichment_errors["headline_block"]` and never discards the spine). The `HeadlineSpec` declares the
  four selectivity axes (critical axis = WIN, the tumor-vs-normal window), a curated verdict→phrase map,
  a polarity read (positive = a tumor-selective call, negative = not-selective / broadly-normal KILL
  veto, neutral = gaps + the selectivity-preserving `selective_with_normal_liability` flag, mirroring
  functional-requirement's `pan_essential_killer` treatment), and a `tension_extra` surfacing the
  normal-breadth VETO downgrade as the sharpest cross-cutting caveat.
- `--figures` now also emits the shared `figure_headline_hero.{svg,png,json}` ALONGSIDE the existing
  selectivity evidence-strip hero (`emit_selectivity_hero` unchanged; the two are complementary).
- `headline_block` added to `_SYNTHESIS_FACET_KEYS` so the target-profile fan-out carries the canonical
  headline. Verdict-INERT throughout: `selectivity_class` + the normal-breadth veto spine are
  byte-stable (CEACAM5/TACSTD2 replay guard).

## 1.11.1
- Doc hygiene: documented the Phase S normal-breadth veto SPLIT in SKILL.md — the sc-normal
  critical-organ arm now downgrades to `selective_with_normal_liability` (selectivity-preserving
  named-organ safety flag), distinct from the therapeutic-window arms' `selective_but_broadly_normal`
  KILL; corrected the sc-tumor coverage list (STAD = 8th cube). No behavior change (Phase S behavior
  shipped in _skills_common via #554); this aligns the skill docs + version with it.

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
