---
name: tractability-small-molecule
description: |
  Phase-F skill: "Given known chemical + genetic evidence, does target X in
  indication Y look druggable by a small molecule — is there a compound that
  hits it, and does the chemical signal agree with the genetic dependency?"

  SPLIT 2026-07-14 from the former `tractability-and-modality` skill. That
  skill had grown to 9 cards, but its verdict keyed entirely off the 3
  chemical-genetic cards; the 6 surface cards it merely displayed were split
  into the sibling `surface-modality-fit` skill. This skill owns the
  small-molecule / intracellular tractability call.

  Use for questions like "does PRISM show anyone hitting KRAS in COADREAD?",
  "is there a tool compound for MET, and does it agree with the CRISPR
  dependency?"

metadata:
  version: 3.0.0
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg

composition:
  data_mode: derived_read
  phase: [F]
  cards_used:
    - prism-compound-activity
    - prism-crispr-concordance
    - dependency-predictability
  rules_scope:
    - all
  synthesis:
    - rule_engine
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
  status: wired
---

# tractability-small-molecule

## What this skill does

- Fetches the 3 chemical-genetic cards (prism-compound-activity,
  prism-crispr-concordance, dependency-predictability) via the
  compose-dashboard live-reader dispatchers.
- Fires the `e7-*` / `prism-*` / `predictability-*` rules.
- Emits `decision.json` with:
  - `headline`: `druggability_snapshot` + `driving_rule_id`, plus the driving
    prism activity class, PRISM-CRISPR concordance class, and predictability
    class.
  - `fired_rules`: which chemical-genetic rules matched.

## Snapshot resolution (rank-ordered, first match wins)

  1. `e7-triangulated-target-engaged-supportive` → `well_covered`
     (chemical hits agree with genetic dependency — highest confidence)
  2. `e7-crispr-confirmed-supportive-sm` → `chemically_confirmed_genetic`
  3. `prism-clinically-active-supportive-sm` → `chemically_active`
  4. `prism-tool-compound-only-weak-supportive-sm` → `tool_compound_only`
  5. `prism-weakly-active-weak-supportive-sm` → `weakly_active`
  6. `e7-discordant-off-target-warning` → `discordant`
  7. `prism-no-compounds-found-neutral` → `chemically_unhit`
  8. else → `insufficient`

## What this skill does NOT do

- Does NOT assess biologics-modality fit (ADC / TCE / degrader surface
  topology, surfaceome family, structure pockets). That is the sibling
  `surface-modality-fit` skill. A full modality workup chains both.
- No new dispatchers, no new rules.

## How Claude invokes this skill

1. Extract `target` (HGNC symbol, uppercase) and `indication` (AACR OncoTree
   code, uppercase — e.g. COADREAD, LUAD).
2. Pick a durable `out` directory (prefer `~/dev/framework-runs/...`; avoid
   `/tmp`, which is wiped on SageMaker restart).
3. Run:
   ```
   export AWS_PROFILE=cbg && \
   python3 /home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills/skills/tractability-small-molecule/scripts/run.py \
     --target <TARGET> --indication <INDICATION> --out <OUT_DIR>
   ```
4. Read `<OUT_DIR>/decision.json`, present the `druggability_snapshot` +
   `driving_rule_id` inline.
