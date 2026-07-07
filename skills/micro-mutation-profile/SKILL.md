---
name: micro-mutation-profile
description: |
  Focused single-question skill: "What is target X's mutation profile in
  indication Y — recurrent driver, biomarker-stratified dependency, or
  passenger pattern?" Consumes three mutation-oriented cards:
    - mutation-type-counts             (E4: cell-line MAF variant-class counts)
    - mutation-stratified-dependency   (mut-vs-WT CRISPR effect delta)
    - mutation-hotspot-frequency       (TCGA MC3 tumor MAF, hotspot recurrence)
  Runs the mut-* + mutant-* rule subset. Emits decision.json with a
  mutation-profile verdict + driving rule + hotspot metrics.

  Use for focused questions like "is KRAS a recurrent driver in COADREAD?",
  "does BRAF-mutant CRC show a dependency biomarker signal?", "is TP53's
  mutation pattern LOF-dominant?" — cases where you want the mutation call
  without the full 16-card evaluation.

metadata:
  version: 1.0.0
  owner: ryan.abo@takeda.com
  layer: micro
  cards_used:
    - mutation-type-counts
    - mutation-stratified-dependency
    - mutation-hotspot-frequency
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg
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
