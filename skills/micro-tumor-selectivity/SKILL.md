---
name: micro-tumor-selectivity
description: |
  Focused single-decision skill: "How selectively is target X expressed in
  tumor vs normal for indication Y, and how robust is that call across
  independent comparators?" Consumes exactly ONE card
  (tumor-vs-normal-selectivity, card v3.0.0 — the four-cell sensitivity
  product). Emits a compact decision.json with selectivity_class,
  cells_supporting (n/3), dominant_direction, discordant flag, and the
  matched interpretation rule.

  Use this skill when a scientist asks a focused per-target question like
  "is EPCAM tumor-selective in COADREAD?", "is KRAS overexpressed in
  colorectal tumors?", or "how does APC read on tumor-vs-normal in CRC?" —
  cases where the full evidence package (16 cards, ~1-2 min compute) is
  overkill and a single-card call is enough.

  This is a MODALITY-AGNOSTIC skill. The v3 tumor-vs-normal-selectivity card
  produces signals for both small-molecule and degrader lenses; those are
  exposed as optional `modality_lenses` in the output for callers that want
  them, but the primary output is the biology call (selectivity_class),
  which is modality-independent.

metadata:
  version: 1.0.0
  owner: ryan.abo@takeda.com
  layer: micro
  cards_used: [tumor-vs-normal-selectivity]
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg
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
