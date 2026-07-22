---
name: functional-requirement
description: |
  Focused question skill: "Is target X a genetic dependency in indication
  Y, and how does the call hold up across CRISPR + RNAi + lineage context?"
  Consumes 4 dependency-relevant cards + the dependency-* rule subset.
  Emits a data-package output tree with a rank-ordered dependency verdict.

  Use for focused questions like "is KRAS a dependency in COADREAD?", "is
  MET essential across CRC cell lines?", "does the CRISPR and RNAi signal
  agree for CDK7 in LUAD?" — cases where you want the dependency call
  without the full 16-card evaluation.

  Biology-first output. Modality is a POST-HOC lens exposed via optional
  --modality flag; the primary output (dependency_verdict + driving_rule_id)
  is modality-independent.

metadata:
  version: 1.1.0
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg

composition:
  data_mode: derived_read
  phase: [C]
  cards_used:
    - pan-cancer-crispr-dependency-distribution
    - pan-cancer-rnai-dependency-distribution
    - crispr-rnai-dependency-concordance
    - dependency-lineage-selectivity
    - paralog-buffering                  # Layer 6d addition: dependency-hardening signal
    - prism-crispr-concordance           # E-PRISM re-home 2026-07-20: chemical-genetic confirmation arm (was in run.py CARDS, missing here)
    - dependency-predictability          # Gate-C gap 1 (Option A): META-evidence → CONFIDENCE annotation only, NOT the verdict
    # Biomarker-facet render cards (ADDITIVE, verdict-inert — feed NO resolver ladder). Grouped:
    - expression-dependency-correlation  # RNA arm: mRNA predicts dependency (was in run.py CARDS, missing here)
    - recommended-models                 # Q4 patient↔model correspondence: model-backed-dependency (was in run.py CARDS, missing here)
    - abundance-dependency               # Q7 PROTEIN arm: protein abundance predicts dependency (2026-07-22)
  # DATA_TO_SKILL_CONTRACT Rule 3 — the measurement_type CLAIMS this gate PULLs (resolves against
  # target-contracts/vocabularies/measurement_types.yaml; the 2 CRISPR cards fold into one type).
  # chemical_genetic_concordance = the prism-crispr CONFIRMATION arm; dependency_predictability is
  # pulled as confidence META-evidence (feeds dependency_confidence_note, not the verdict). The three
  # biomarker-facet types (expression/abundance dependency correlation + patient_model_correspondence)
  # are ADDITIVE render facets — pulled for the biomarker/preferred-assay synthesis, verdict-inert.
  measurement_types_pulled:
    - crispr_lof_dependency
    - rnai_lof_dependency
    - crispr_rnai_concordance
    - paralog_buffering
    - chemical_genetic_concordance
    - dependency_predictability
    - expression_dependency_correlation
    - abundance_dependency_correlation
    - patient_model_correspondence
  rules_scope:
    - pan-cancer-crispr-dependency-distribution
    - pan-cancer-rnai-dependency-distribution
    - crispr-rnai-dependency-concordance
    - dependency-lineage-selectivity
    - paralog-buffering
    - prism-crispr-concordance
    - dependency-predictability
  synthesis:
    - rule_engine
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
  optional_lenses:
    - modality
  status: wired
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
