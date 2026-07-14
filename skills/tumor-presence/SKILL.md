---
name: tumor-presence
description: |
  Focused question skill: "Is target X expressed in indication Y's tumor
  tissue, and how does its expression distribute across cancer cell lines
  vs. tumor samples?" Consumes 2 wired expression cards:
    - expression-distribution           (E3a: pan-cancer cell-line TPM distribution)
    - expression-tumor-vs-adjacent      (bulk tumor RNA-seq DEG vs. paired adjacent)
  Runs the expression-* rule subset. Emits a data-package output tree with
  a rank-ordered expression-status verdict.

  Use for questions like "is EPCAM expressed in CRC?", "how does MET
  distribute across colon cell lines?", "is CDX2 tumor-elevated relative
  to adjacent margin?"

  This skill answers Phase-A questions (presence) — distinct from Phase-B
  (selectivity vs. normals), which is `tumor-selectivity`.

  Biology-first output. Modality is a POST-HOC lens exposed via optional
  --modality flag.

metadata:
  version: 1.1.0
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg

composition:
  data_mode: derived_read
  phase: [A]
  cards_used:
    - expression-distribution
    - expression-tumor-vs-adjacent
    - protein-presence-cptac         # Layer 6c addition: dual RNA + protein presence
  rules_scope:
    - expression-distribution
    - expression-tumor-vs-adjacent
    - protein-presence-cptac
  synthesis:
    - rule_engine
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
  optional_lenses:
    - modality
  status: wired
---

# tumor-presence

## What this skill does

- Fetches the two expression cards via compose-dashboard live-reader
  dispatchers. Reuses the exact same read path Macro uses — no drift.
- Runs the expression-* rule subset (9 rules across the 2 cards) against
  the summaries.
- Emits a data-package output tree with:
  - `decision.json` — presence_verdict + fired rules
  - `summary.yaml` — per-card summary dicts
  - `tables/` — per-card summary_stats CSVs
  - `figures/` — populated per-card if a card emitter is wired
  - `provenance.yaml` — audit anchor including `invoked_lenses`

## Verdict resolution (rank-ordered)

1. `expression-broadly-high-supportive` fires → `broadly_high_expression`
2. `expression-strong-upregulation-supportive` fires → `strongly_upregulated_in_tumor`
3. `expression-lineage-restricted-supportive` fires → `lineage_restricted`
4. `expression-modest-upregulation-neutral` fires → `modestly_upregulated_in_tumor`
5. `expression-broadly-moderate-neutral` fires → `broadly_moderate_expression`
6. `expression-broadly-low-degrader-killer` fires → `broadly_low_expression`
7. `expression-call-not-informative-degrader-killer` fires → `not_informative`
8. `expression-data-unavailable-insufficient` fires → `data_unavailable`
9. else → `insufficient`

The `driving_rule_id` is captured in the headline so a reviewer can trace
the verdict back to the exact rule in intracellular-intrinsic.rules.yaml.

## What this skill does NOT do

- Does NOT recompute the DGE — reads pre-computed derived products.
- Does NOT compare tumor to GTEx-population-normal — that's `tumor-selectivity`.
- Does NOT synthesize narrative — see `target-profile` for the composed skill.

## How Claude invokes this skill

When called as `/tumor-presence`, Claude should:

1. Extract `target` (HGNC gene symbol, uppercase) and `indication`
   (AACR OncoTree code, uppercase — e.g. COADREAD, LUAD, BRCA) from the
   user's prompt. Ask if either is missing or ambiguous.
2. Pick an `out` directory. Default: `/tmp/tumor-presence/{target}-{indication}`.
3. Run:
   ```
   export AWS_PROFILE=cbg && \
   python3 /home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills/skills/tumor-presence/scripts/run.py \
     --target <TARGET> --indication <INDICATION> --out <OUT_DIR>
   ```
   Add `--modality <M>` if the user names a modality; otherwise omit.
4. Read `<OUT_DIR>/decision.json`, present the headline (presence_verdict +
   driving_rule_id + per-card summary highlights) inline.
