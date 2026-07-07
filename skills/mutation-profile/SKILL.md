---
name: mutation-profile
description: |
  Focused question skill: "What is target X's mutation profile in
  indication Y — recurrent driver, biomarker-stratified dependency, or
  passenger pattern?" Consumes 3 mutation-oriented cards (type-counts +
  stratified-dependency + hotspot-frequency) + the mut-* + mutant-* rule
  subset. Emits a data-package output tree with a rank-ordered mutation-
  profile verdict + hotspot metrics.

  Use for focused questions like "is KRAS a recurrent driver in COADREAD?",
  "does BRAF-mutant CRC show a dependency biomarker signal?", "is TP53's
  mutation pattern LOF-dominant?"

  Biology-first output. Modality is a POST-HOC lens exposed via optional
  --modality flag.

metadata:
  version: 1.0.0
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
  rules_scope:
    - mutation-type-counts
    - mutation-stratified-dependency
    - mutation-hotspot-frequency
  synthesis:
    - rule_engine
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
  optional_lenses:
    - modality
  status: wired
---

# Micro — Mutation Profile

## What this skill does

- Fetches the 3 mutation-relevant cards via compose-dashboard live-reader
  dispatchers.
- Filters intracellular-intrinsic rules to `when.card_id` in the 3 cards.
- Emits `decision.json` with:
  - `headline`: `mutation_profile` (biomarker_stratified_dependency /
    recurrent_lof_driver / recurrent_missense_driver / mixed_pattern /
    passenger_pattern / insufficient), driving_rule_id, plus hotspot
    frequency + top hotspot from the MC3 card.
  - `fired_rules`: which of the mut-*/mutant-* rules matched.
  - `modality_lenses`: optional SM+degrader tally.

## Verdict resolution (rank-ordered)

  1. If `mutant-strongly-dependent-supportive` fires — the strongest signal
     (mut-vs-WT dependency delta): `biomarker_stratified_dependency`.
  2. Else if `mutant-moderately-dependent-supportive` fires:
     `moderate_biomarker_dependency`.
  3. Else if `mut-lof-dominant-supportive` fires: `recurrent_lof_driver`
     (tumor-suppressor pattern).
  4. Else if `mut-missense-dominant-supportive` fires:
     `recurrent_missense_driver` (oncogene pattern).
  5. Else if `mut-mixed-neutral` fires: `mixed_pattern`.
  6. Else if `mut-no-mutations-neutral` fires: `passenger_pattern`.
  7. Else: `insufficient`.

## Coverage note

- The `mutation-hotspot-frequency` card is WIRED (dispatches to
  `gdc_somatic_hotspot` streaming TCGA MC3) but does NOT currently have
  Tier-2 interpretation rules in `intracellular-intrinsic.rules.yaml`.
  Its evidence flows to Macro synthesis directly, not through the rule
  engine. This Micro surfaces its raw metrics (mutation rate,
  hotspot_frequency, top_hotspot) as HEADLINE color for the reader,
  independent of the rule-engine verdict. If the hotspot signal is
  needed as a rule-firing gate, adding hotspot-* rules to the rules
  file is a follow-on.

## What this skill does NOT do

- Doesn't recompute mutation calls. Reads from DepMap 26Q1 + TCGA MC3
  sources via existing dispatchers.
- No figure rendering by default.

## Invocation

```
python scripts/run.py --target KRAS --indication COADREAD \
    --out /tmp/mut-KRAS-COADREAD
```

## How Claude invokes this skill

When called as `/micro-mutation-profile`, Claude should:

1. Extract `target` (HGNC gene symbol, uppercase) and `indication`
   (AACR OncoTree code, uppercase — e.g. COADREAD, LUAD, BRCA) from the
   user's prompt. Ask if either is missing or ambiguous.
2. Pick an `out` directory. Default: `/tmp/micro-mutation-profile/{target}-{indication}`
   unless the user specifies one.
3. Run:
   ```
   export AWS_PROFILE=cbg && \
   python3 /home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills/skills/micro-mutation-profile/scripts/run.py \
     --target <TARGET> --indication <INDICATION> --out <OUT_DIR>
   ```
4. Read `<OUT_DIR>/decision.json`, present the headline + the driving_rule_id
   inline, and offer to open the full JSON if the user wants details.
5. If the underlying card summary carries `_schema: v2_two_product_fallback`
   (only `micro-tumor-selectivity`), flag that the v3 sensitivity product
   is not yet in S3 for that indication and the response is on legacy
   two-contrast data.
