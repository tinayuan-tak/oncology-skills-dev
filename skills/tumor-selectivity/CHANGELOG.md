# Changelog — tumor-selectivity

The `version` in [SKILL.md](SKILL.md) and `SKILL_VERSION` in
[scripts/run.py](scripts/run.py) must always match (guarded by
`skills/tests/test_version_parity.py`); bump both together and add an entry here.

## 1.20.0
- **`--literature` retriever → `default_retrieve` (multi-source, lens-specific queries).** Shared
  `_skills_common/literature_retrieval.py` gains (1) `pubtator3_retrieve` (NCBI PubTator3 entity-index
  search) + `default_retrieve` = Europe PMC → PubTator3 **fallback chain**, so a transient single-source
  outage no longer collapses grounding to internal-knowledge/unverified (the failure mode seen on the
  1.19.0 validation run); (2) **per-subskill query specificity + variations** — `_build_query_variations`
  issues a broad gene∧disease query AND a lens-specific query whose terms come from the LensConfig's own
  `axis_labels` + a curated per-lens map (selectivity → therapeutic window / normal-tissue / IHC), merged
  and deduped by PMID; (3) a `verify_citations` NCBI E-utilities fallback. tumor-selectivity flips its
  `retrieve_fn` from `europe_pmc_retrieve` to `default_retrieve`. VERDICT-INERT / best-effort — spine
  untouched. (Shared-module change; coordinated with the presence literature arc.)

## 1.19.0
- **OPTIONAL `--literature` lane (VERDICT-INERT), Phase-5 fast-follow to 1.18.0.** Wires the shared
  `_skills_common` literature lane (`make_literature_fn`) into `run_wired_skill(literature_fn=…)`, scoped
  to this skill's WIN/DIST/INT/SAFE axes via the `TUMOR_SELECTIVITY` LensConfig (its thesis / axis_labels /
  polarity_note + the claim_vector drive the prompt). Grounded on **live Europe PMC** (`europe_pmc_retrieve`)
  and **PMID-verified** (`verify_citations`), attached as `decision['literature_synthesis']` and fed to the
  `--synthesize` narrator as a corroboration/contradiction lane. `--literature-model` overrides the model.
- Reuses the shared lane READ-ONLY (landed via the tumor-presence literature arc, #965) — NOT
  re-implemented. `--literature`/`--synthesize` need system python + `BEDROCK_AWS_PROFILE=cmp-dev`
  (+ `AWS_PROFILE=cbg` for the card reads). Verdict-inert: the lane runs AFTER the spine and never enters
  `fired`/the resolver/the veto; `selectivity_class` byte-stable.

## 1.18.0
- **Multi-platform corroboration folded into the claim vector (VERDICT-INERT signals-first enrichment).**
  The WIN/INT axes were single-lane (WIN = bulk-RNA comparators only; INT = single-cell only), so the
  claim vector — which the narrator LEADS with — was blind to signals the headline already computes.
  Three quorum-aware additions (`_skills_common/selectivity_claims.py`):
  - **WIN protein quorum.** The two tumor-vs-normal PROTEIN cards (CPTAC TMT + TPHP DIA-MS) now cap WIN
    corroboration when they FAIL to corroborate the RNA window (2 non-significant platforms → `low`; 1 →
    `moderate`; a significant OPPOSITE direction → `low`) and surface it as a WIN conflict. A fully
    corroborating protein layer imposes no cap. Catches the RNA-up / protein-flat false positive
    (EPCAM/COADREAD: CPTAC not-significant + TPHP tumor<normal → the RNA window is not confirmed at protein).
  - **INT spatial quorum.** In-situ `spatial-region-rna-expression` is now an independent arm of the
    malignant-compartment attribution: an agreeing `tumour_enriched_rna` lifts INT corroboration one step
    (single-cell + spatial concur); a `tme_enriched_rna` caps it and flags the conflict.
  - **WIN field-effect signature.** The per-comparator log2FCs (`log2fc_cell_a` adjacent vs `log2fc_cell_c`
    distant GTEx) the collapsed class hides are surfaced as a HIGH-NORMAL-BASELINE FIELD EFFECT note
    (tumor≈adjacent-normal but tumor>distant-normal — a genuine but NARROW window) — the EPCAM/CEACAM
    epithelial-marker archetype.
- **Narrator rule + thesis (LensConfig).** `TUMOR_SELECTIVITY` thesis extended to name the corroboration
  lanes; a new `polarity_note` instructs the synthesis to LEAD with whether independent platforms (protein
  MS + in-situ spatial) corroborate the RNA window, and to distinguish a field effect from a broadly wide
  window. Verified on a live EPCAM/COADREAD `--synthesize` run: the narrative now frames the field effect
  and cites the 2-platform protein non-corroboration.
- **Byte-stability:** all additions gate on the new headline fields (protein-concordance / spatial /
  per-cell log2FC), so they are NO-OPs when those inputs are absent; the CEACAM5/TACSTD2 replay fixtures'
  `selectivity_class` + normal-breadth/stromal-confound veto spine are untouched (resolver golden-stable).
  Corroboration *tiers* on the three curated fixtures are unchanged (already ≤ the protein cap; INT already
  high); only evidence/conflict strings enrich. Full `_skills_common` suite green (1038 passed).
- **PENDING fast-follow (Phase 5, blocked on `feat/presence-literature-and-claims`):** a `--literature`
  lane reusing the shared `_skills_common/literature_synthesis.py` (`make_literature_fn(TUMOR_SELECTIVITY)`)
  lands once that branch merges its `run_wired_skill(literature_fn=...)` + `--literature` dispatcher seam.
  This skill's LensConfig is already literature-ready (its thesis/axis_labels/polarity_note + the enriched
  WIN/INT claim axes are exactly what `build_literature_prompt` consumes). The lane is NOT re-implemented here.

## 1.17.0
- **INT-axis stromal-confound veto (verdict-MOVING, backtest-gated).** `tumor-scrna-celltype-expression`
  is now verdict-driving: its provenance-gated `stromal_confound_class == stromal_confounded` fires the
  `tvn-stromal-confound-veto` rule, and the shared `_skills_common.selectivity_veto` clamp (both engines)
  downgrades a selective axis-A call to the new `selective_but_stromal_confound` — a bulk selective signal
  that single-cell attribution shows is CAF/stroma-driven, not malignant-cell-intrinsic (a false window
  for tumor-cell-targeted modalities; ADC/TCE/CAR/degrader all opposing).
- **Precedence (Option B):** the stromal-confound KILL outranks the normal-breadth window KILL when both
  fire — the more fundamental disqualifier for a tumor-cell modality. Order: stromal-confound > window >
  full-normal > sc-normal > tphp.
- **Provenance-gated:** fires only on a trustworthy cube (curated/inferCNV, entity-specific); a
  phenotype_proxy / multi-entity-pooled cube reads `inconclusive_low_confidence` and cannot move the verdict.
- Backtest passed: RETAIN CEACAM5/EPCAM/CDH17/MSLN (malignant-intrinsic); DOWNGRADE FAP/POSTN/COL1A1/THY1.
  CEACAM5/TACSTD2 replay fixtures byte-stable. Cross-repo: analysis-methods #537 (the field) +
  target-contracts #590 (the rule + `selective_but_stromal_confound` token) landed first.
- Fixed a doc bug: the roadmap referenced `caf_vs_malignant_class == caf_high` (nonexistent); the real
  value is `caf_dominant`.

## 1.14.0
- Added the `tumor-vs-normal-protein-abundance-tphp` card — a VERDICT-INERT RNA→PROTEIN tumor-vs-normal
  corroboration facet, PARALLEL to `tumor-protein-abundance-cptac`, over the TPHP DIA-MS product
  `tphp-tumor-vs-normal-protein-per-cohort-v1` (Xu et al., Nature 2026): 22 carcinoma cohorts, several
  OUTSIDE CPTAC coverage (gallbladder, laryngeal, GIST, testis, thymoma, ...). New reader
  `methods/tphp_tumor_vs_normal_protein/read.py` emits CPTAC-ALIGNED field names
  (`protein_effect_size` / `protein_bh_q_value` / ...), so the existing `_rna_protein_tvn_concordance`
  projection consumes it UNCHANGED; the `_headline` surfaces a namespaced `_tphp` corroboration block.
- Fires NO resolver rung and NO veto clamp — verdict-INERT (absent from `card_resolver_consumption`).
  Added to run.py `CARDS` + `SKILL.md` cards_used/measurement_types_pulled + the 3 parity lists
  (`CARDS`, `SUB_SKILL_CARDS[tumor-selectivity]`, `DIMENSION_CARDS[selectivity]`). NOT wired into the
  certainty corroboration model (kept a pure display facet — the CPTAC sibling remains the sole
  selectivity certainty-corroboration source). New measurement_type `tumor_vs_normal_protein_abundance`
  (target-contracts). Selectivity verdict byte-stable (CEACAM5/TACSTD2 replay guard).

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
