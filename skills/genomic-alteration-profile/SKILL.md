---
name: genomic-alteration-profile
description: |
  Focused question skill: "How is target X genomically altered in indication Y
  — by SNV/indel (recurrent driver, biomarker-stratified dependency, or
  passenger), by copy-number (amplification/deletion), or a mix — and which
  alteration class drives?" Consumes 3 mutation cards + copy-number-distribution
  (+ a fusion-rearrangement placeholder). Emits a data-package output tree with
  a multi-class genomic-alteration verdict.

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
  version: 2.0.0
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg

composition:
  data_mode: derived_read
  phase: [A, E]
  cards_used:
    - mutation-type-counts
    - mutation-stratified-dependency
    - mutation-hotspot-frequency
    - copy-number-distribution
    - fusion-rearrangement-landscape        # PLACEHOLDER — data not yet landed
  # DATA_TO_SKILL_CONTRACT Rule 3 — measurement_type claims pulled. mutation-type-counts and
  # mutation-hotspot-frequency are DISTINCT types (variant-class spectrum vs cohort recurrence);
  # fusion_rearrangement is pulled-but-data-blocked (placeholder provider) — a visible-gap state.
  measurement_types_pulled:
    - mutation_variant_class_spectrum
    - mutation_stratified_dependency
    - mutation_hotspot_frequency
    - copy_number_alteration
    - fusion_rearrangement
  rules_scope:
    - mutation-type-counts
    - mutation-stratified-dependency
    - mutation-hotspot-frequency
    - copy-number-distribution
  synthesis:
    - rule_engine
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
  a declared placeholder (resolves `_missing` until fusion data lands).
- Fires the `mut-*` / `mutant-*` / `cn-*` rules.
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
     `recurrent_lof_driver` / `recurrent_missense_driver`.
  3. **Only copy-number drives** (mutation passenger/mixed/absent)
     → `recurrent_amplification_driver` / `recurrent_deletion_driver`.
  4. **Neither** → the mutation axis's `mixed_pattern` / `passenger_pattern`,
     else `insufficient`.

## Alteration classes

- **SNV / indel** — wired (TCGA MC3 + DepMap), 3 cards, full rule coverage.
- **Copy number** — wired (copy-number-distribution card + its 11 `cn-*` rules
  already existed; this reframe is the first skill to compose them).
- **Fusion / rearrangement** — PLACEHOLDER (`fusion-rearrangement-landscape`
  card, v0.1.0). No method/product yet; resolves `_missing`, does not
  contribute to the verdict. Fusion may warrant its own skill if it grows heavy.

## What this skill does NOT do

- Doesn't recompute alteration calls. Reads existing DepMap 26Q1 + TCGA MC3
  sources via existing dispatchers.
- Doesn't yet score fusions (placeholder axis).

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
