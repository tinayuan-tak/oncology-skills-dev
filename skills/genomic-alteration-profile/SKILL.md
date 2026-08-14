---
name: genomic-alteration-profile
description: |
  Focused question skill: "How is target X genomically altered in indication Y
  — by SNV/indel (recurrent driver, biomarker-stratified dependency, or
  passenger), by copy-number (amplification/deletion), or a mix — and which
  alteration class drives?" Consumes 18 cards: 7 verdict-driving (3 SNV/indel +
  copy-number-distribution + 3 stratified-dependency siblings [cn/fusion/amp-expr]
  + alteration-role), the mutation-hotspot-frequency recurrence facet, a LIVE
  fusion-rearrangement landscape (tcga-fusion-consensus-v1), and 8 additive
  signal-only layers (drug-response, variant-level, allele-count, patient↔model
  match, + 3 indication-level cohort-context facets). Emits a data-package output
  tree with a multi-class genomic-alteration verdict.

  REFRAMED 2026-07-14 from `mutation-profile` (SNV/indel only). The
  copy-number-distribution card + its 11 rules already existed but were never
  composed into a skill; a mutation-only skill implied "not a driver" for
  amplification-driven targets (ERBB2, MYC, MET). This skill reports the
  alteration MIX.

  Use for questions like "is KRAS a recurrent driver in COADREAD?", "is ERBB2
  amplification-driven in this indication?", "does BRAF-mutant CRC show a
  dependency biomarker signal?"

  Biology-first output. Modality is a POST-HOC lens exposed via optional
  --modality flag.

metadata:
  version: 2.3.0
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg

composition:
  data_mode: derived_read
  phase: [A, E]
  cards_used:
    # VERDICT-DRIVING (rules enter the genomic_alteration resolver — see rules_scope):
    - mutation-type-counts
    - mutation-stratified-dependency
    - copy-number-distribution
    - copy-number-stratified-dependency      # A1a: amplified lines Chronos-more-dependent → resolver §2b (biomarker_stratified_dependency)
    - fusion-stratified-dependency           # A1-fusion: fusion-positive lines more-dependent → resolver §2c
    - amp-expr-stratified-dependency         # A1 amp-expr: amplified+high-expr conjoint → resolver §2d
    - alteration-role                        # typed driver ROLE (OncoKB × IntOGen); VERDICT-DRIVING — fires the
                                             # 12 confirmed_driver rungs (resolver §0) via when_all_fired with a
                                             # mut/cn driver rule. (2026-08-08 review: was mis-filed below as
                                             # "additive / no resolver rung" — it is NOT additive.)
    - mutation-hotspot-frequency             # composed + headline, but fires ZERO rules (display-only recurrence); NOT in rules_scope
    # ADDITIVE signal-only layers (feed the LLM/matrix + headline; fire NO resolver rung, so they
    # are NOT in rules_scope and the verdict spine is byte-stable):
    - fusion-rearrangement-landscape         # LIVE 2026-07-23 (tcga-fusion-consensus-v1, pan-TCGA 3-caller consensus); additive signal-only
    - variant-level-interpretation           # CIViC per-variant oncogenicity + resistance alleles; additive signal-only
    - target-clonality                       # scientific-gap #2 (2026-08-14): mutation clonality/truncality (ccf from MC3 VAF x ABSOLUTE purity); durability/resistance facet, additive signal-only
    - functional-gene-state                  # M6 allele-count / biallelic two-hit state; 2026-07-22
    - genomic-event-model-match              # M11 patient↔model genomic-event join (canonical P3); 2026-07-22
    - genomic-instability-state              # M7 aneuploidy/CIN burden (2026-08-06): INDICATION-level cohort context (target-independent); additive signal-only, verdict-inert
    - mutational-signature-context           # 2026-08-12: per-indication mutagenic-process context (TCGA MC3 → SigProfilerAssignment COSMIC v3.3); INDICATION-level, target-independent; additive, verdict-inert (APOBEC/MMR/HRD/tobacco/UV/POLE); PATIENT arm, sibling of ddr-deficiency-context
    - ddr-deficiency-context                 # Track PI (2026-08-09): per-indication DDR/HRD cohort context (Knijnenburg 2018 DDR footprint); INDICATION-level, target-independent; additive, verdict-inert (frames the PARP1/HRD blind axis)
    - oncogenic-pathway-alteration           # Sanchez-Vega 2018 (2026-08-10): per-indication oncogenic-pathway ALTERATION freq; verdict-inert cohort context; complements PROGENy activity
    - mutation-drug-response                 # (in run.py CARDS; 2026-08-11 doc-drift fixed) mutation-stratified drug-
                                             # response (delta log2AUC on-target compounds); additive signal-only, verdict-inert
    - subgroup-stratified-mutation-frequency # SUBTYPE axis (2026-08-05): per-stratum mutation frequency (MSI/MSS/sidedness/LoT); tier:subtype, DESCRIPTIVE panorama (emits no verdict — display facet like tumor-presence's by-subtype card); applies only when subgroup_spec is set
  # DATA_TO_SKILL_CONTRACT Rule 3 — the DISTINCT measurement_type claims this skill pulls, one per
  # distinct card measurement_type (mutation-hotspot-frequency + subgroup-stratified-mutation-frequency
  # share mutation_hotspot_frequency → listed once). Every entry is registered in
  # target-contracts/vocabularies/measurement_types.yaml. 2026-08-13 review (G7/G8): completed from 8
  # → 17 — the 3 stratified-dependency siblings (cn/fusion/amp_expr), the drug-response biomarker, and
  # the 5 cohort-context/variant layers (instability, mutational-signature, DDR, oncogenic-pathway,
  # variant-level) were pulled by cards_used but never declared here. test_genomic_measurement_types.py
  # now enforces parity so this cannot silently re-drift.
  measurement_types_pulled:
    # verdict-driving axes
    - mutation_variant_class_spectrum        # mutation-type-counts
    - mutation_stratified_dependency         # mutation-stratified-dependency
    - copy_number_alteration                 # copy-number-distribution
    - cn_stratified_dependency               # copy-number-stratified-dependency (resolver §2b)
    - fusion_stratified_dependency           # fusion-stratified-dependency (resolver §2c)
    - amp_expr_stratified_dependency         # amp-expr-stratified-dependency (resolver §2d)
    - alteration_role                        # alteration-role (resolver §0 confirmed_driver)
    # composed + headline, additive signal-only (no resolver rung)
    - mutation_hotspot_frequency             # mutation-hotspot-frequency + subgroup-stratified-mutation-frequency
    - mutation_drug_response                 # mutation-drug-response
    - fusion_rearrangement                   # fusion-rearrangement-landscape
    - variant_level_interpretation           # variant-level-interpretation
    - mutation_clonality                     # target-clonality (#2: ccf-based truncality; verdict-inert)
    - functional_gene_state                  # functional-gene-state
    - genomic_event_model_match              # genomic-event-model-match
    - genomic_instability_state              # genomic-instability-state (indication-level cohort context)
    - mutational_signature_context           # mutational-signature-context (indication-level cohort context)
    - ddr_deficiency_context                 # ddr-deficiency-context (indication-level cohort context)
    - oncogenic_pathway_alteration           # oncogenic-pathway-alteration (indication-level cohort context)
  # rules_scope = cards whose rules actually enter the genomic_alteration resolver. NOTE
  # (2026-08-05): mutation-hotspot-frequency was listed here but fires ZERO rules — its
  # overall_mutation_frequency is display-only (headline), never a verdict input. Dropped to
  # match reality (see ALT-3: a driver-recurrence percentile is the intended way to make
  # frequency verdict-relevant). fusion-rearrangement-landscape + the additive layers are NOT here.
  # (2026-08-08 review: added the 3 stratified-dependency cards — resolver §2b/2c/2d — and
  # alteration-role — resolver §0 confirmed_driver — which DO enter the resolver but were omitted.)
  rules_scope:
    - mutation-type-counts
    - mutation-stratified-dependency
    - copy-number-distribution
    - copy-number-stratified-dependency
    - fusion-stratified-dependency
    - amp-expr-stratified-dependency
    - alteration-role
  synthesis:
    - rule_engine
    - structured_llm    # 2026-08-05: opt-in --synthesize (genomic-alteration-lens narrator, two-slot; verdict-inert)
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
  LIVE (tcga-fusion-consensus-v1, 3-caller TCGA consensus) + composed as an
  ADDITIVE signal-only layer (reaches the headline/LLM, fires no resolver rung).
- Fires the `mut-*` / `mutant-*` / `cn-*` rules (fusion is NOT in rules_scope).
- Emits `decision.json` with:
  - `headline`: `genomic_alteration_profile` verdict + `driving_rule_id`, plus
    the mutation landscape/stratification classes, mutation frequency, and the
    `copy_number_class`.
  - `genomic_alteration_by_class` (2026-08-14): the PER-ALTERATION-CLASS decomposition of the
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
     `*_dominant_pattern` verdicts (renamed from `recurrent_*_driver`, T1.1)
     report the *variant-class composition* of the mutation spectrum
     (≥70% missense / ≥50% truncating) — NOT patient recurrence, which the
     mutation-type card never computes.
  3. **Only copy-number / fusion drives** (mutation passenger/mixed/absent)
     → `recurrent_amplification_driver` / `recurrent_deletion_driver` /
     `recurrent_fusion_driver` (T1.3: a recurrently rearranged patient
     oncogene — ≥3 samples — with no DepMap dependency line, previously lost
     to passenger).
  4. **Neither** → the mutation axis's `mixed_pattern` / `passenger_pattern`,
     else `insufficient`.

  Within the stratified-dependency family, precedence is **by effect strength
  then class** (T2.4): all *strongly*-dependent signals (mut/cn/fusion/amp-expr)
  outrank all *moderately*-dependent ones, so a strong CN/fusion dependency is
  named the driver over a moderate mutation dependency for a dually-altered gene.

## Alteration classes

- **SNV / indel** — wired (TCGA MC3 + DepMap), 3 cards, full rule coverage.
- **Copy number** — wired (copy-number-distribution card + its 11 `cn-*` rules
  already existed; this reframe is the first skill to compose them).
- **Fusion / rearrangement** — LIVE (`fusion-rearrangement-landscape` card,
  backed by `tcga-fusion-consensus-v1`: TumorFusions/PRADA + Gao 2018 +
  cBioPortal-TCGA-SV, 3-caller consensus). ADDITIVE signal-only: reaches the
  headline + LLM narrative + evidence matrix but fires no resolver rung, so the
  deterministic verdict spine is byte-stable. TCGA-only, presence-not-frequency
  (denominator is a fast-follow). GENIE-SV breadth is a future additive source.

## What this skill does NOT do

- Doesn't recompute alteration calls. Reads existing DepMap 26Q1 + TCGA MC3
  sources via existing dispatchers.
- Doesn't fold fusion into the deterministic verdict (fusion is composed but
  additive signal-only — it informs the narrative, not the resolver rung).

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
