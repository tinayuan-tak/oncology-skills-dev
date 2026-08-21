---
name: genomic-alteration-profile
description: |
  Focused question skill: "How is target X genomically altered in indication Y
  — by SNV/indel (recurrent driver, biomarker-stratified dependency, or
  passenger), by copy-number (amplification/deletion), or a mix — and which
  alteration class drives?" Reports the alteration MIX and names which class
  carries the signal, rather than implying "not a driver" for an amplification-
  or fusion-driven target (ERBB2, MYC, MET).

  Consumes 18 cards: 9 verdict-driving (mutation-type-counts, mutation-stratified-
  dependency, copy-number-distribution, the 3 stratified-dependency siblings
  [cn/fusion/amp-expr], alteration-role, fusion-rearrangement-landscape [LIVE,
  tcga-fusion-consensus-v1], and mutation-drug-response), the mutation-hotspot-
  frequency recurrence facet, and 8 additive signal-only layers (variant-level,
  clonality, functional-gene-state, patient↔model match, + 4 indication-level
  cohort-context facets). Emits a data-package output tree with a multi-class
  genomic-alteration verdict.

  Use for questions like "is KRAS a recurrent driver in COADREAD?", "is ERBB2
  amplification-driven in this indication?", "does BRAF-mutant CRC show a
  dependency biomarker signal?"

  Biology-first output. Modality is a POST-HOC lens exposed via optional
  --modality flag. See CHANGELOG.md for development history.

metadata:
  version: 2.8.0
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg

composition:
  data_mode: derived_read
  phase: [A, E]
  cards_used:
    # SPLICE-FORM facets (2) — VERDICT-INERT display (R10 homing); fire no rule, genomic verdict spine byte-stable
    - tumor-splice-dysregulation
    - tumor-splice-expression
    # VERDICT-DRIVING — these cards' rules enter the genomic_alteration resolver (see rules_scope):
    - mutation-type-counts                   # SNV/indel variant-class landscape
    - mutation-stratified-dependency         # are mutant cell lines Chronos-more-dependent?
    - copy-number-distribution               # focal amplification / deletion recurrence
    - copy-number-stratified-dependency      # are amplified lines Chronos-more-dependent? (ERBB2/MYC)
    - fusion-stratified-dependency           # are fusion-positive lines more dependent? (EWSR1-FLI1)
    - amp-expr-stratified-dependency         # amplified AND high-expression conjoint dependency
    - alteration-role                        # typed driver ROLE (OncoKB × IntOGen); fires the confirmed_driver
                                             # rungs together with a mutation/CN driver rule
    - fusion-rearrangement-landscape         # recurrent TCGA fusion driver (tcga-fusion-consensus-v1); a
                                             # recurrent_fusion_driver fusion_class fires the fusion rung
    - mutation-drug-response                 # genotype → on-target drug response (PRISM); the STRONG class
                                             # (mutant_strongly_drug_sensitive) fires the drug_response_biomarker rung
    # RECURRENCE — VERDICT-DRIVING as of Phase 2: the POOLED multi-cohort pooled_driver_recurrence_class
    # (TCGA-MC3 + GENIE + MSK-CHORD) fires the snv-recurrence-top-driver rule → recurrent_snv_driver rung.
    # (The single-cohort MC3/GENIE driver_recurrence_* fields remain display-only comparators.)
    - mutation-hotspot-frequency             # recurrence frequency + pooled driver-recurrence (VERDICT-DRIVING)
    # ADDITIVE signal-only layers — feed the LLM/matrix + headline; fire NO resolver rung, so they are
    # NOT in rules_scope and the verdict spine is byte-stable:
    - variant-level-interpretation           # CIViC per-variant oncogenicity + resistance alleles
    - target-clonality                       # mutation clonality/truncality (ccf from MC3 VAF × ABSOLUTE purity)
    - functional-gene-state                  # allele-count / biallelic two-hit state
    - genomic-event-model-match              # which DepMap models carry the SAME event as the tumours
    - genomic-instability-state              # indication-level aneuploidy / CIN / WGD / MSI cohort context
    - mutational-signature-context           # indication-level mutagenic-process context (TCGA MC3 → COSMIC v3.3 SBS)
    - ddr-deficiency-context                 # indication-level DDR/HRD cohort context (Knijnenburg 2018)
    - oncogenic-pathway-alteration           # indication-level oncogenic-pathway alteration freq (Sanchez-Vega 2018)
    - cross-consortium-dependency            # Q4 CONFIDENCE (verdict-inert): Broad↔Sanger CRISPR agreement
    - dependency-predictability              # Q4 CONFIDENCE (verdict-inert): omics-learnability + lineage-collapse flag
    - subgroup-stratified-mutation-frequency # DESCRIPTIVE per-stratum mutation-frequency panorama (emits no
                                             # verdict); applies only when a subgroup_spec is set
    - subgroup-stratified-copy-number        # DESCRIPTIVE per-stratum patient focal amp/del panorama (TCGA GISTIC
                                             # per-sample); the CN subtype axis — --subtypes-gated, verdict-inert
    - subgroup-stratified-fusion             # DESCRIPTIVE per-stratum fusion-recurrence panorama (usually
                                             # underpowered per stratum); the fusion subtype axis — --subtypes-gated
  # The DISTINCT measurement_type claims this skill pulls, one per distinct card measurement_type
  # (mutation-hotspot-frequency + subgroup-stratified-mutation-frequency share
  # mutation_hotspot_frequency → listed once). Every entry is registered in
  # target-contracts/vocabularies/measurement_types.yaml, and test_genomic_measurement_types.py
  # enforces parity with cards_used so this list cannot silently drift.
  measurement_types_pulled:
    # verdict-inert splice-form facets (R10)
    - tumor_splice_dysregulation
    - tumor_splice_expression
    # verdict-driving axes
    - mutation_variant_class_spectrum        # mutation-type-counts
    - mutation_stratified_dependency         # mutation-stratified-dependency
    - copy_number_alteration                 # copy-number-distribution + subgroup-stratified-copy-number (subtype view)
    - cn_stratified_dependency               # copy-number-stratified-dependency (resolver §2b)
    - fusion_stratified_dependency           # fusion-stratified-dependency (resolver §2c)
    - amp_expr_stratified_dependency         # amp-expr-stratified-dependency (resolver §2d)
    - alteration_role                        # alteration-role (resolver §0 confirmed_driver)
    # composed + headline. mutation_drug_response + fusion_rearrangement ARE verdict-driving
    # (they fire the drug_response_biomarker / recurrent_fusion_driver rungs); the rest are additive.
    - mutation_hotspot_frequency             # mutation-hotspot-frequency + subgroup-stratified-mutation-frequency (display-only)
    - mutation_drug_response                 # mutation-drug-response (VERDICT-DRIVING: strong class → drug_response_biomarker)
    - fusion_rearrangement                   # fusion-rearrangement-landscape (VERDICT-DRIVING: recurrent_fusion_driver rung)
                                             # + subgroup-stratified-fusion (subtype view, display-only)
    - variant_level_interpretation           # variant-level-interpretation
    - mutation_clonality                     # target-clonality (#2: ccf-based truncality; verdict-inert)
    - functional_gene_state                  # functional-gene-state
    - genomic_event_model_match              # genomic-event-model-match
    - genomic_instability_state              # genomic-instability-state (indication-level cohort context)
    - mutational_signature_context           # mutational-signature-context (indication-level cohort context)
    - ddr_deficiency_context                 # ddr-deficiency-context (indication-level cohort context)
    - oncogenic_pathway_alteration           # oncogenic-pathway-alteration (indication-level cohort context)
    - cross_consortium_dependency            # cross-consortium-dependency (Q4 confidence; verdict-inert)
    - dependency_predictability              # dependency-predictability (Q4 confidence; verdict-inert)
  # rules_scope = cards whose rules actually enter the genomic_alteration resolver.
  # mutation-hotspot-frequency is VERDICT-DRIVING as of Phase 2: its POOLED pooled_driver_recurrence_class
  # (not the display-only single-cohort overall_mutation_frequency) fires the recurrent_snv_driver rung.
  rules_scope:
    - mutation-type-counts
    - mutation-stratified-dependency
    - copy-number-distribution
    - copy-number-stratified-dependency
    - fusion-stratified-dependency
    - amp-expr-stratified-dependency
    - alteration-role
    - fusion-rearrangement-landscape         # resolver §3c: fusion_class==recurrent_fusion_driver fires
                                             # fusion-landscape-recurrent-driver-supportive → recurrent_fusion_driver
    - mutation-drug-response                 # resolver §2d-drug: drug_response_stratification_class==
                                             # mutant_strongly_drug_sensitive fires mutation-drug-response-strongly-
                                             # sensitive-supportive → drug_response_biomarker (STRONG class only)
    - mutation-hotspot-frequency             # resolver tier 6 (Phase 2): pooled_driver_recurrence_class==top_1pct
                                             # fires snv-recurrence-top-driver-supportive → recurrent_snv_driver
  synthesis:
    - rule_engine
    - structured_llm    # opt-in --synthesize (genomic-alteration-lens narrator, two-slot; verdict-inert)
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
  optional_lenses:
    - modality
  status: wired
---

# genomic-alteration-profile

## What this skill does

- Fetches the SNV/indel cards (mutation-type-counts, mutation-stratified-
  dependency, mutation-hotspot-frequency) + copy-number-distribution via the
  compose-dashboard live-reader dispatchers. Fusion-rearrangement-landscape is
  LIVE (tcga-fusion-consensus-v1, 3-caller TCGA consensus); a recurrent_fusion_driver
  fusion_class fires the `recurrent_fusion_driver` resolver rung (§3c) — so it IS
  verdict-driving (in rules_scope), not merely additive.
- Fires the `mut-*` / `mutant-*` / `cn-*` / `fusion-landscape-*` /
  `mutation-drug-response-*` rules.
- Emits `decision.json` with:
  - `headline`: `genomic_alteration_profile` verdict + `driving_rule_id`, plus
    the mutation landscape/stratification classes, mutation frequency, and the
    `copy_number_class`.
  - `genomic_alteration_by_class`: the PER-ALTERATION-CLASS decomposition of the
    collapsed multi_class verdict — `{snv_indel, copy_number, fusion}` → each class's own primary
    call (`verdict`) + `evidence_state` (measured / data_unavailable) + its stratified-dependency
    sibling. Mirrors tumor-presence's `presence_verdict_by_modality`: lets a consumer see WHICH class
    drives (e.g. ERBB2/BRCA → the collapsed `biomarker_stratified_dependency` decomposes to
    copy_number `amplified_strongly_dependent`, not SNV). ADDITIVE / verdict-inert — reuses fields
    already in the headline; `genomic_alteration_profile` is byte-stable.
  - `fired_rules`: which mutation + copy-number rules matched.

## Verdict resolution (multi-class)

The SNV/indel axis is primary (strongest therapeutic signals); copy-number is
a modifier so amplification/deletion-driven targets aren't collapsed to passenger:

  1. **Both classes drive** (a mutation driver AND a recurrent CN event)
     → `multi_class_driver` (mutation rule reported as primary driver).
  2. **Only SNV/indel drives** → the mutation verdict stands:
     `biomarker_stratified_dependency` / `moderate_biomarker_dependency` /
     `lof_dominant_pattern` / `missense_dominant_pattern`. The two
     `*_dominant_pattern` verdicts report the *variant-class composition* of the
     mutation spectrum (≥70% missense / ≥50% truncating) — NOT patient
     recurrence, which the mutation-type card never computes.
  3. **Only copy-number / fusion drives** (mutation passenger/mixed/absent)
     → `recurrent_amplification_driver` / `recurrent_deletion_driver` /
     `recurrent_fusion_driver` (a recurrently rearranged patient oncogene —
     ≥3 samples — with no DepMap dependency line, previously lost to passenger).
  4. **Neither** → the mutation axis's `mixed_pattern` / `passenger_pattern`,
     else `insufficient`.

  Within the stratified-dependency family, precedence is **by effect strength
  then class**: all *strongly*-dependent signals (mut/cn/fusion/amp-expr)
  outrank all *moderately*-dependent ones, so a strong CN/fusion dependency is
  named the driver over a moderate mutation dependency for a dually-altered gene.

## Alteration classes

- **SNV / indel** — wired (TCGA MC3 + DepMap), 3 cards, full rule coverage.
- **Copy number** — wired (copy-number-distribution card + its family of `cn-*`
  rules; this skill is the first to compose them).
- **Fusion / rearrangement** — LIVE (`fusion-rearrangement-landscape` card,
  backed by `tcga-fusion-consensus-v1`: TumorFusions/PRADA + Gao 2018 +
  cBioPortal-TCGA-SV, 3-caller consensus). VERDICT-DRIVING: a `recurrent_fusion_driver`
  fusion_class fires the `recurrent_fusion_driver` resolver rung (§3c, the fusion analog
  of recurrent focal amplification) — so it CAN set the deterministic verdict (it is in
  rules_scope). Non-recurrent fusion classes stay narrative-only. `fusion_frequency`
  (fused / assayed samples in the tissue) IS computed, and pan-cohort GENIE-SV breadth
  is LIVE (`genie_sv_*`, backed by `genie-sv-recurrence-v1`). A verdict-inert
  `fusion_recurrence_confidence` tier flags whether a `recurrent_fusion_driver` call rests
  on a recurrent partner (`high_recurrent_partner`, reliable) or a promiscuous recurrence
  (`moderate_promiscuous`) — the latter also catches amplicon-artifact SVs at amplified
  oncogenes (e.g. ERBB2/STAD ~1%); a panel backtest showed no frequency/structural cut
  separates those from real promiscuous kinase fusions (ROS1/NTRK1), so the fix is a future
  fusion-competence / copy-number gate, not a threshold change.

## What this skill does NOT do

- Doesn't recompute alteration calls. Reads existing DepMap 26Q1 + TCGA MC3
  sources via existing dispatchers.
- Doesn't fold NON-recurrent fusion classes into the deterministic verdict — only a
  `recurrent_fusion_driver` fusion_class sets the verdict (resolver §3c); other fusion
  classes inform the narrative only.

## How Claude invokes this skill

1. Extract `target` (HGNC symbol, uppercase) + `indication` (OncoTree code).
2. Pick a durable `out` directory (avoid `/tmp`).
3. Run:
   ```
   export AWS_PROFILE=cbg && \
   python3 /home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills/skills/genomic-alteration-profile/scripts/run.py \
     --target <TARGET> --indication <INDICATION> --out <OUT_DIR>
   ```
4. Read `<OUT_DIR>/decision.json`, present `genomic_alteration_profile` +
   `driving_rule_id` inline.
