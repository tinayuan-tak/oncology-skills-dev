# Changelog — tractability-small-molecule


`SKILL_VERSION` in [scripts/run.py](scripts/run.py) is the current semver; the dated
development history below was migrated verbatim from the former inline `SKILL_VERSION`
comment. Newest first.

## 3.12.0 (2026-09-10, #993 pt1): VERDICT-INERT minority_allele_coverage_caveat — a positive SM snapshot resting on an approved ALLELE-SELECTIVE drug (curated approved_drug_target_allele.yaml) that covers only a MINORITY of the indication's mutant-allele spectrum (dominant hotspot uncovered; KRAS/COADREAD G12C-only) reads well_covered_for_minority_allele. Adds mutation-hotspot-frequency to CARDS (verdict-inert context, read only by the caveat). Spine/resolver/golden byte-stable; indication-conditioned (KRAS/LUAD G12C-dominant does NOT fire).

## 3.11.1 (2026-09-07, CASE-008 #07): _sm_modality_mismatch_caveat fallback now reads the biologics-only modality map LIVE from biologics_precedent_targets.yaml (_biologics_only_modalities → _live_readers._load_biologics_precedent_modalities, keyed on biologics_only: true) instead of the hardcoded _BIOLOGICS_APPROVED_NONSM (demoted to a last-resort fail-safe). New vocab entries covered automatically. VERDICT-INERT (caveat is a headline field; spine/resolver/golden byte-stable).
