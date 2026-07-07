---
name: micro-druggability-snapshot
description: |
  Focused single-question skill: "Given known chemical + genetic evidence,
  does target X in indication Y look druggable — is there a compound that
  hits it, and does the compound's activity concord with the genetic
  dependency?" Consumes three cards:
    - prism-compound-activity            (E6 v3, Log2AUC primary metric)
    - prism-crispr-concordance           (E7, chemical-genetic triangulation)
    - dependency-predictability          (E5, multi-omics predictability model)
  Runs the prism-* + predictability-* rule subsets. Emits decision.json with
  a druggability snapshot and — optionally, if `--modality` is passed —
  a modality-lensed viability call for SM or degrader.

  Use for focused questions like "does PRISM show anyone hitting KRAS in
  COADREAD?", "does the compound-genetic signal agree for CDK7?", "how
  predictable is the MET dependency phenotype from features?" — where
  chemical-tractability is the crux, not the full evidence package.

metadata:
  version: 1.0.0
  owner: ryan.abo@takeda.com
  layer: micro
  cards_used:
    - prism-compound-activity
    - prism-crispr-concordance
    - dependency-predictability
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg
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
