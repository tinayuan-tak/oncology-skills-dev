---
name: genomic-alteration-profile
description: |
  Focused question skill: "How is target X genomically altered in indication Y
  — by SNV/indel (recurrent driver, biomarker-stratified dependency, or
  passenger), by copy-number (amplification/deletion), or a mix — and which
  alteration class drives?" Consumes 3 mutation cards + copy-number-distribution
  + a LIVE fusion-rearrangement landscape (tcga-fusion-consensus-v1) + additive
  role/allele-count/patient-model/subtype layers. Emits a data-package output tree
  with a multi-class genomic-alteration verdict.

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
  version: 2.1.1
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
    - functional-gene-state                  # M6 allele-count / biallelic two-hit state; 2026-07-22
    - genomic-event-model-match              # M11 patient↔model genomic-event join (canonical P3); 2026-07-22
    - genomic-instability-state              # M7 aneuploidy/CIN burden (2026-08-06): INDICATION-level cohort context (target-independent); additive signal-only, verdict-inert
    - subgroup-stratified-mutation-frequency # SUBTYPE axis (2026-08-05): per-stratum mutation frequency (MSI/MSS/sidedness/LoT); tier:subtype, DESCRIPTIVE panorama (emits no verdict — display facet like tumor-presence's by-subtype card); applies only when subgroup_spec is set
  # DATA_TO_SKILL_CONTRACT Rule 3 — measurement_type claims pulled. mutation-type-counts and
  # mutation-hotspot-frequency are DISTINCT types (variant-class spectrum vs cohort recurrence);
  # fusion_rearrangement is LIVE (tcga-fusion-consensus-v1). alteration_role + functional_gene_state
  # + genomic_event_model_match + subgroup-stratified-mutation-frequency are the additive
  # role / allele-count / patient↔model-match / subtype-panorama layers (all signal-only, no resolver rung).
  measurement_types_pulled:
    - mutation_variant_class_spectrum
    - mutation_stratified_dependency
    - mutation_hotspot_frequency
    - copy_number_alteration
    - fusion_rearrangement
    - alteration_role
    - functional_gene_state
    - genomic_event_model_match
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
