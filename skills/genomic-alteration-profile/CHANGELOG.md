# genomic-alteration-profile — changelog

Development history for the skill. The `SKILL.md` header describes the CURRENT
contract only; dated design decisions and reclassification notes live here so the
contract stays readable.

## 2026-08-18
- Fixed a `depmap_common` lineage-ladder label bug (amp-expr strong→moderate downgrade
  never fired because the map keyed the abbreviated `amp_expr_*` class instead of the
  fully-spelled `amplified_overexpressed_*` the method emits). Corrected in analysis-methods.
- Added `fusion_recurrence_confidence` — a verdict-inert tier on a `recurrent_fusion_driver`
  call (`high_recurrent_partner` = reliable recurrent partner vs `moderate_promiscuous` =
  target recurs but no recurrent partner; the latter also catches amplicon-artifact SVs at
  amplified oncogenes, e.g. ERBB2/STAD ~1%). A panel backtest found no frequency/structural
  cut separates those from real promiscuous kinase fusions (ROS1/NTRK1), so the intended fix
  is a future fusion-competence / copy-number gate, not a threshold change.

## 2026-08-15
- Doc-parity fix: `fusion-rearrangement-landscape` and `mutation-drug-response` (STRONG class
  only) are VERDICT-DRIVING — they fire resolver rungs (`recurrent_fusion_driver` and
  `drug_response_biomarker` respectively) and belong in `rules_scope`. They had been
  mis-documented as additive signal-only.

## 2026-08-14
- Added `genomic_alteration_by_class`: the per-alteration-class decomposition of the collapsed
  multi-class verdict (`{snv_indel, copy_number, fusion}`), mirroring tumor-presence's
  `presence_verdict_by_modality`. Additive / verdict-inert — reuses fields already in the
  headline, so the verdict spine is byte-stable.
- Added `target-clonality` (ccf-based truncality from MC3 VAF × ABSOLUTE purity) as an additive
  durability/resistance facet.

## 2026-08-13
- Declared all pulled measurement types in `measurement_types_pulled` (previously 8 of 18: the
  3 stratified-dependency siblings, the drug-response biomarker, and the 5 cohort-context/variant
  layers were consumed by `cards_used` but never declared). `test_genomic_measurement_types.py`
  now enforces parity so it cannot silently re-drift.

## 2026-08-08 – 2026-08-12
- Reclassified `alteration-role` as VERDICT-DRIVING (fires the `confirmed_driver` rungs together
  with a mutation/CN driver rule) — it had been mis-filed as additive.
- Added the 3 stratified-dependency cards (cn/fusion/amp-expr) to `rules_scope`.
- Added indication-level cohort-context facets (additive, verdict-inert): `genomic-instability-state`
  (aneuploidy/CIN), `mutational-signature-context` (TCGA MC3 → COSMIC v3.3 SBS), `ddr-deficiency-context`
  (Knijnenburg 2018 DDR footprint), `oncogenic-pathway-alteration` (Sanchez-Vega 2018).

## 2026-08-05
- Dropped `mutation-hotspot-frequency` from `rules_scope`: it fires zero rules (its
  `overall_mutation_frequency` is display-only). A driver-recurrence percentile is the intended
  path to make frequency verdict-relevant.
- Renamed the `recurrent_*_driver` SNV verdicts to `*_dominant_pattern`: they report the
  variant-class COMPOSITION of the mutation spectrum (≥70% missense / ≥50% truncating), not
  patient recurrence, which the mutation-type card never computes.
- Added opt-in `--synthesize` (genomic-alteration-lens LLM narrator; verdict-inert).

## 2026-07-23
- `fusion-rearrangement-landscape` went LIVE (`tcga-fusion-consensus-v1`: TumorFusions/PRADA +
  Gao 2018 + cBioPortal-TCGA-SV, 3-caller consensus). A `recurrent_fusion_driver` fusion_class
  fires the fusion resolver rung.

## 2026-07-14
- REFRAMED from `mutation-profile` (SNV/indel only) to `genomic-alteration-profile`. The
  copy-number-distribution card + its copy-number rules already existed but had never been
  composed into a skill; a mutation-only skill implied "not a driver" for amplification-driven
  targets (ERBB2, MYC, MET). The skill now reports the alteration MIX and names which class drives.
