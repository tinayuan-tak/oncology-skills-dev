---
name: tractability-and-modality
description: |
  Phase-F skill: "Given known chemical + genetic evidence, plus surface
  topology + structural features + surfaceome family + cohort ranking,
  does target X in indication Y look druggable — and which modality fits
  best?"

  EXTENDED 2026-07-08: composition expanded from 3 chemical-genetic cards
  to 9 cards. Adds 6 F-phase cards (4 leaves + 1 composed + 1 target-scan
  hook). Consumes both intracellular-intrinsic rules (via the 3 chemical-
  genetic cards) AND surface-intrinsic rules (via the 6 new F-phase cards).

  Modality-lens discipline (arch A2, 2026-07-08): letter grades (adc_grade,
  tce_grade) are LENS-CONDITIONAL — emitted only when --modality is invoked.
  Without --modality, biology-first fit_class categorical is emitted only.
  The isoform-selective vocabulary (arch A3) suppresses letter grades
  unconditionally for targets with clinically-dominant alt isoforms.

  Use for questions like "does PRISM show anyone hitting KRAS in COADREAD?",
  "does EGFR look ADC-favorable in COADREAD?", "is CDH17 top-percentile in
  the surfaceome ranking for gastric?"

metadata:
  version: 2.1.0
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg
  method_version_pins:
    modality_rubric: '1.0.0'
    isoform_selective_targets: '1.0.0'

composition:
  data_mode: derived_read
  phase: [F]
  cards_used:
    - prism-compound-activity
    - prism-crispr-concordance
    - dependency-predictability
    - surface-topology-and-ptm
    - surfaceome-family-classification
    - structure-features-static
    - surface-abundance-density
    - adc-tce-modality-fit
    - surfaceome-cohort-ranking
  rules_scope:
    - all
  synthesis:
    - rule_engine
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
  optional_lenses:
    - modality
  status: wired
---

# Micro — Druggability Snapshot

## What this skill does

- Fetches the 3 chemical-genetic cards via the compose-dashboard live-reader
  dispatchers.
- Filters intracellular-intrinsic rules to those whose `when.card_id` is
  in the 3 cards.
- Emits `decision.json` with:
  - `headline`: `druggability_snapshot` (well_covered / partially_covered /
    chemically_unhit / discordant / insufficient), driving prism activity
    class, concordance class, and predictability class.
  - `fired_rules`: which prism-* / predictability-* rules matched.
  - `modality_lenses`: optional SM+degrader tally when `--modality-lens`
    passed (biology-first by default).

## Snapshot resolution (rank-ordered, first match wins)

  1. If prism-crispr-concordance fires `concordant-drug-active-dep`:
     → `well_covered` (chemical hits agree with genetic dep — highest
     confidence for a compound-oriented modality)
  2. Else if prism-compound-activity fires an active-in-indication rule:
     → `chemically_active` (compound hits, no genetic-concordance yet)
  3. Else if prism-crispr-concordance fires a discordant/warning rule:
     → `discordant`
  4. Else if prism-compound-activity fires an inactive rule:
     → `chemically_unhit`
  5. Else: `insufficient`

## What this skill does NOT do

- Doesn't include TVN-sel or dependency cards — those are the neighboring
  Micros (`micro-tumor-selectivity`, `micro-dependency-in-indication`).
  A full druggability workup should chain all three.
- No new dispatchers, no new rules.

## Invocation

```
python scripts/run.py --target KRAS --indication COADREAD \
    --out /tmp/drug-KRAS-COADREAD
```

## How Claude invokes this skill

When called as `/micro-druggability-snapshot`, Claude should:

1. Extract `target` (HGNC gene symbol, uppercase) and `indication`
   (AACR OncoTree code, uppercase — e.g. COADREAD, LUAD, BRCA) from the
   user's prompt. Ask if either is missing or ambiguous.
2. Pick an `out` directory. Default: `/tmp/micro-druggability-snapshot/{target}-{indication}`
   unless the user specifies one.
3. Run:
   ```
   export AWS_PROFILE=cbg && \
   python3 /home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills/skills/micro-druggability-snapshot/scripts/run.py \
     --target <TARGET> --indication <INDICATION> --out <OUT_DIR>
   ```
4. Read `<OUT_DIR>/decision.json`, present the headline + the driving_rule_id
   inline, and offer to open the full JSON if the user wants details.
5. If the underlying card summary carries `_schema: v2_two_product_fallback`
   (only `micro-tumor-selectivity`), flag that the v3 sensitivity product
   is not yet in S3 for that indication and the response is on legacy
   two-contrast data.
