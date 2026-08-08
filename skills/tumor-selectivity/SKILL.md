---
name: tumor-selectivity
description: |
  Focused question skill: "How selectively is target X expressed in tumor
  vs normal for indication Y, and how robust is that call across
  independent comparators?" Consumes THREE cards — tumor-vs-normal-selectivity
  (v3, four-cell sensitivity; the aggregate verdict) + tumor-vs-normal-
  percentile-crossing (Q2 per-sample corroboration) + modality-therapeutic-window
  (the normal-breadth VETO: downgrades an axis-A-selective call to
  selective_but_broadly_normal when there is no therapeutic window) — and emits a
  data-package output tree (decision.json + summary.yaml + tables/ + figures/ + provenance.yaml).
  Optional --synthesize attaches a two-slot LLM narration (verdict-inert).

  Use for focused per-target questions like "is EPCAM tumor-selective in
  COADREAD?", "is KRAS overexpressed in colorectal tumors?", "how does APC
  read on tumor-vs-normal in CRC?" — cases where a full evidence package
  is overkill.

  Biology-first output. Modality is a POST-HOC lens exposed via optional
  --modality flag; the primary output (selectivity_class + cells_supporting
  + discordant flag) is modality-independent.

metadata:
  version: 1.2.0
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg

composition:
  data_mode: derived_read
  phase: [B]
  cards_used:
    - tumor-vs-normal-selectivity
    - tumor-vs-normal-percentile-crossing    # Q2 per-sample corroboration (2026-08-05: was composed in
                                             # run.py but omitted here — doc-drift fixed). Its
                                             # tumor-vs-normal-crossing-* rules emit SM/degrader signals;
                                             # the selectivity RESOLVER stays keyed to the aggregate card.
    - modality-therapeutic-window            # axis-B/E NORMAL-BREADTH VETO (conjunction redesign INC-1/2,
                                             # 2026-08-07): therapeutic_window_class == no_therapeutic_window
                                             # downgrades an axis-A-selective call to selective_but_broadly_normal
                                             # via the run.py::_verdict post-resolver clamp (a 2-card conjunction
                                             # the single-rule resolver cannot express). In run.py CARDS since
                                             # the INC-1/2 landing; declared here 2026-08-08 (doc-drift fixed).
  # DATA_TO_SKILL_CONTRACT Rule 3 — measurement_type claims pulled. tumor_vs_normal_selectivity is
  # the efficacy-window framing (distinct from safety's normal_tissue_breadth — Rule 1 discriminator b).
  measurement_types_pulled:
    - tumor_vs_normal_selectivity
    - modality_window                        # the normal-breadth veto instrument (modality-therapeutic-window)
  rules_scope:
    - tumor-vs-normal-selectivity
    - tumor-vs-normal-percentile-crossing
    - modality-therapeutic-window            # the tvn-no-therapeutic-window-veto rule feeds the _verdict clamp
  synthesis:
    - rule_engine
    - structured_llm    # 2026-08-05: opt-in --synthesize (selectivity-lens narrator, two-slot; verdict-inert)
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
  optional_lenses:
    - modality
  status: wired
---

# Tumor-vs-Normal Selectivity

## What this skill does

- Fetches THREE cards for a single (target, indication) via the compose-dashboard
  live-reader dispatcher (reuses the exact same read path Macro uses — no drift):
  - `tumor-vs-normal-selectivity` (v3, four-cell sensitivity) — the aggregate verdict.
  - `tumor-vs-normal-percentile-crossing` — Q2 per-sample corroboration (fraction of
    tumors above the matched-normal p95).
  - `modality-therapeutic-window` — the axis-B/E NORMAL-BREADTH VETO (tumor ÷ worst
    critical-normal); its `therapeutic_window_class == no_therapeutic_window` downgrades
    an otherwise-selective call (see the veto note below).
- Runs the tvn-* + tumor-vs-normal-crossing-* subset of the intracellular-intrinsic
  rules against the summaries. The selectivity RESOLVER stays keyed to the aggregate
  card's classes (verdict byte-stable); the crossing rules add SM/degrader signal.
- NORMAL-BREADTH VETO (conjunction redesign INC-1/2): after the resolver returns an
  axis-A verdict, `run.py::_verdict` applies a one-directional post-resolver clamp — if
  the verdict is selective AND the `tvn-no-therapeutic-window-veto` rule fired (a gene
  broadly expressed in normal tissue with no therapeutic window), it downgrades to
  `selective_but_broadly_normal`. This is a 2-card conjunction the single-rule resolver
  cannot express; it exists to stop a housekeeping-like gene passing as tumor-selective.
  KNOWN LIMITATION (2026-08-08 review): this clamp is effective in the standalone skill
  but currently inert inside the composed target-profile (the window card is scoped to a
  different sub-skill lens there); the fix is tracked in the selectivity-conjunction plan.
- Emits `decision.json` with:
  - `headline`: `selectivity_class`, `cells_supporting`, `dominant_direction`,
    `discordant`, `max_abs_log2fc`, the Axis-1 `selectivity_allgene_percentile*`
    (relative-selectivity context), and the `percentile_crossing_class` corroboration.
  - `verdict`: the resolved selectivity verdict, which may be the veto outcome
    `selective_but_broadly_normal` (axis-A selective but no therapeutic window) via the
    `_verdict` clamp; `driving_rule_id` names the rule that set it.
  - `fired_rules`: which rules matched
  - `modality_lenses`: optional SM+degrader tally for callers who want it
  - `llm_synthesis` (only with --synthesize): a two-slot selectivity-lens narration.

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

Live-read only (a focused single-lens skill). Reads S3 via the same dispatcher chain
that Macro uses. If the sensitivity product is not yet in S3 for the
requested indication, the reader's v2 fallback kicks in and the skill
still returns a decision (with `_schema: v2_two_product_fallback` visible
in the underlying summary).

## How Claude invokes this skill

When called as `/tumor-selectivity`, Claude should:

1. Extract `target` (HGNC gene symbol, uppercase) and `indication`
   (AACR OncoTree code, uppercase — e.g. COADREAD, LUAD, BRCA) from the
   user's prompt. Ask if either is missing or ambiguous.
2. Pick an `out` directory. Default: `/tmp/tumor-selectivity/{target}-{indication}`
   unless the user specifies one.
3. Run (add `--synthesize` for the optional LLM narration):
   ```
   export AWS_PROFILE=cbg && \
   python3 /home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills/skills/tumor-selectivity/scripts/run.py \
     --target <TARGET> --indication <INDICATION> --out <OUT_DIR>
   ```
4. Read `<OUT_DIR>/decision.json`, present the headline + the driving_rule_id
   inline, and offer to open the full JSON if the user wants details.
5. If the underlying card summary carries `_schema: v2_two_product_fallback`,
   flag that the v3 sensitivity product is not yet in S3 for that indication
   and the response is on legacy two-contrast data.
