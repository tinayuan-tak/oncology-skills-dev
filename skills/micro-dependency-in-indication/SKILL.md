---
name: micro-dependency-in-indication
description: |
  Focused single-question skill: "Is target X a genetic dependency in
  indication Y, and how does the call hold up across CRISPR + RNAi + lineage
  context?" Consumes three cards:
    - pan-cancer-crispr-dependency-distribution
    - pan-cancer-rnai-dependency-distribution
    - crispr-rnai-dependency-concordance
    - dependency-lineage-selectivity   (optional 4th, lineage lens)
  Runs the dependency-* rule subset from the intracellular-intrinsic rules
  file (~20 rules across the 4 cards). Emits a compact decision.json with
  a dependency verdict + which rules fired + optional modality lenses.

  Use this skill for focused questions like "is KRAS a dependency in
  COADREAD?", "is MET essential across CRC cell lines?", "does the CRISPR
  and RNAi signal agree for CDK7 in LUAD?" — cases where you want the
  dependency call without the full 16-card evaluation.

metadata:
  version: 1.0.0
  owner: ryan.abo@takeda.com
  layer: micro
  cards_used:
    - pan-cancer-crispr-dependency-distribution
    - pan-cancer-rnai-dependency-distribution
    - crispr-rnai-dependency-concordance
    - dependency-lineage-selectivity
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg
---

# Micro — Dependency in Indication

## What this skill does

- Fetches the 4 dependency-relevant cards via the compose-dashboard live-reader
  dispatchers (zero new dispatcher code; same read path Macro uses).
- Filters the intracellular-intrinsic rules to those whose `when.card_id` is
  in the 4 dependency cards (skips tvn-*, prism-*, mutation-*, cn-*, etc.).
- Emits `decision.json` with:
  - `headline`: `dependency_verdict` (essential / lineage_selective /
    concordant_dependent / non_dependent / discordant / insufficient),
    plus the driving CRISPR + RNAi calls.
  - `fired_rules`: which of the dep-* rules matched.
  - `modality_lenses`: optional SM+degrader tally.

## Verdict resolution

Rank-ordered (first match wins) — kept deliberately simple, biology-first,
so the logic is inspectable at a glance:

  1. If a rule marked `dominant: true` fires with a killer signal on either
     CRISPR or RNAi (e.g. pan-essential): verdict is `pan_essential_killer`.
  2. Else if `concordant-dependent-supportive-dominant` fires: verdict is
     `concordant_dependent`.
  3. Else if a lineage-selective rule fires: `lineage_selective`.
  4. Else if `concordance-discordant-warning` fires: `discordant`.
  5. Else if any non-dependent rule fires with no counter-signal:
     `non_dependent`.
  6. Else: `insufficient`.

Which specific rule drove the verdict is recorded in the headline
(`driving_rule_id`), so a reviewer can trace back to the interpretation-
rules YAML.

## What this skill does NOT do

- No new dispatchers, no new rules — reuses target-contracts.
- No figure rendering by default; caller can invoke `compose-dashboard` on
  a filtered spec to get the 4-card figure set.
- Not modality-locked. Modality lenses are OPTIONAL post-hoc projections
  (biology-first output shape).

## Invocation

```
python scripts/run.py --target KRAS --indication COADREAD \
    --out /tmp/dep-KRAS-COADREAD
# → writes /tmp/dep-KRAS-COADREAD/decision.json
```

## How Claude invokes this skill

When called as `/micro-dependency-in-indication`, Claude should:

1. Extract `target` (HGNC gene symbol, uppercase) and `indication`
   (AACR OncoTree code, uppercase — e.g. COADREAD, LUAD, BRCA) from the
   user's prompt. Ask if either is missing or ambiguous.
2. Pick an `out` directory. Default: `/tmp/micro-dependency-in-indication/{target}-{indication}`
   unless the user specifies one.
3. Run:
   ```
   export AWS_PROFILE=cbg && \
   python3 /home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills/skills/micro-dependency-in-indication/scripts/run.py \
     --target <TARGET> --indication <INDICATION> --out <OUT_DIR>
   ```
4. Read `<OUT_DIR>/decision.json`, present the headline + the driving_rule_id
   inline, and offer to open the full JSON if the user wants details.
5. If the underlying card summary carries `_schema: v2_two_product_fallback`
   (only `micro-tumor-selectivity`), flag that the v3 sensitivity product
   is not yet in S3 for that indication and the response is on legacy
   two-contrast data.
