---
name: tumor-selectivity
description: |
  Focused question skill: "How selectively is target X expressed in tumor
  vs normal for indication Y, and how robust is that call across
  independent comparators?" Consumes the tumor-vs-normal-selectivity card
  (v3, four-cell sensitivity) and emits a data-package output tree
  (decision.json + summary.yaml + tables/ + figures/ + provenance.yaml).

  Use for focused per-target questions like "is EPCAM tumor-selective in
  COADREAD?", "is KRAS overexpressed in colorectal tumors?", "how does APC
  read on tumor-vs-normal in CRC?" — cases where a full evidence package
  is overkill.

  Biology-first output. Modality is a POST-HOC lens exposed via optional
  --modality flag; the primary output (selectivity_class + cells_supporting
  + discordant flag) is modality-independent.

metadata:
  version: 1.1.0
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg

composition:
  data_mode: derived_read
  phase: [B]
  cards_used:
    - tumor-vs-normal-selectivity
  # DATA_TO_SKILL_CONTRACT Rule 3 — measurement_type claims pulled. tumor_vs_normal_selectivity is
  # the efficacy-window framing (distinct from safety's normal_tissue_breadth — Rule 1 discriminator b).
  measurement_types_pulled:
    - tumor_vs_normal_selectivity
  rules_scope:
    - tumor-vs-normal-selectivity
  synthesis:
    - rule_engine
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
  optional_lenses:
    - modality
  status: wired
---

# Micro — Tumor-vs-Normal Selectivity

## What this skill does

- Fetches the tumor-vs-normal-selectivity card (v3, four-cell sensitivity)
  for a single (target, indication) via the compose-dashboard live-reader
  dispatcher. Reuses the exact same read path Macro uses — no drift.
- Runs the tvn-* subset of the intracellular-intrinsic rules (6 rules)
  against the summary.
- Emits `decision.json` with:
  - `headline`: `selectivity_class`, `cells_supporting`, `dominant_direction`,
    `discordant`, `max_abs_log2fc`
  - `fired_rules`: which of the tvn-* rules matched
  - `modality_lenses`: optional SM+degrader tally for callers who want it

## What this skill does NOT do

- Does NOT recompute the DEG. Reads the v3 sensitivity.parquet from S3.
- Does NOT synthesize a full evidence package. That is `compose-dashboard`.
- Does NOT render a figure by default. If a caller wants the 4-panel figure
  they can either invoke `compose-dashboard` with a filtered spec or use
  the emitter directly via `methods.dge_deseq2.emit`.

## Invocation

```
python scripts/run.py --target EPCAM --indication COADREAD --out /tmp/tvn-epcam
# → writes /tmp/tvn-epcam/decision.json
```

## Data mode

Live-read only (this is a Micro). Reads S3 via the same dispatcher chain
that Macro uses. If the sensitivity product is not yet in S3 for the
requested indication, the reader's v2 fallback kicks in and the skill
still returns a decision (with `_schema: v2_two_product_fallback` visible
in the underlying summary).

## How Claude invokes this skill

When called as `/micro-tumor-selectivity`, Claude should:

1. Extract `target` (HGNC gene symbol, uppercase) and `indication`
   (AACR OncoTree code, uppercase — e.g. COADREAD, LUAD, BRCA) from the
   user's prompt. Ask if either is missing or ambiguous.
2. Pick an `out` directory. Default: `/tmp/micro-tumor-selectivity/{target}-{indication}`
   unless the user specifies one.
3. Run:
   ```
   export AWS_PROFILE=cbg && \
   python3 /home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills/skills/micro-tumor-selectivity/scripts/run.py \
     --target <TARGET> --indication <INDICATION> --out <OUT_DIR>
   ```
4. Read `<OUT_DIR>/decision.json`, present the headline + the driving_rule_id
   inline, and offer to open the full JSON if the user wants details.
5. If the underlying card summary carries `_schema: v2_two_product_fallback`
   (only `micro-tumor-selectivity`), flag that the v3 sensitivity product
   is not yet in S3 for that indication and the response is on legacy
   two-contrast data.
