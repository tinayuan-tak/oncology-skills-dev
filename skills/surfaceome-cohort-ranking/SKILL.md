---
name: surfaceome-cohort-ranking
description: |
  Phase-F target-scan hook — per-indication whole-surfaceome effect-size
  ranking. Given an indication (and optionally a target for context),
  produces the SURFY-high-confidence surface protein ranking by tumor-vs-
  normal effect size, cells_supporting-filtered from the 4-cell DESeq2
  sensitivity products.

  NEW SKILL 2026-07-08. This is a TARGET-SCAN hook (per-indication
  reusable derived product), NOT full target-ID mode. Full target-ID
  (druggable-genome universe, modality-calibrated ranking, portfolio
  priors) requires an architectural pass beyond this skill's scope.

  Reviewer-driven design (2026-07-08): the tumor-antigen dashboard's iDAS
  ranking uses a single limma run vs cohort-bulk. Ours composes from the
  4-cell sensitivity DEG so effect sizes are directly comparable to per-
  target profile outputs. cells_supporting >= 3 filter is applied to kill
  the top-of-list false positives seen in the dashboard's single-limma
  version.

  Question this skill answers:
  Which surface proteins in {indication.label} rank highest by tumor-vs-
  normal effect size (cells_supporting-robust), and does the RNA signal
  agree with the CPTAC protein signal?

metadata:
  version: 1.1.0
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg

composition:
  data_mode: batch_compute
  phase: [F]
  cards_used:
    - surfaceome-cohort-ranking
  rules_scope:
    - surfaceome-cohort-ranking
  synthesis:
    - rule_engine
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
  status: wired
---

# surfaceome-cohort-ranking — Phase F target-scan skill

## What this skill does

Given an indication:
  1. Loads the surfaceome-cohort-ranking-per-indication-v1 parquet.
  2. Applies the cells_supporting >= 3 filter (comparator-robustness gate).
  3. Emits a per-indication ranked parquet + slide-drop PNG showing:
     - tissue_rank
     - tissue_percentile_rna
     - tissue_percentile_protein
     - rna_protein_concordance
     - cohort_rank_class (top_1_percent / top_5 / top_25 / below_25)
  4. When a target-symbol is provided as context, the skill highlights the
     target's rank + percentile within the cohort and emits its concordance
     call.

## Two invocation modes

### Mode 1: full-cohort ranking (target-scan)

```
/surfaceome-cohort-ranking COADREAD
```

Emits the full ranked table for downstream analysis (per-tissue
percentile-context lookup product).

### Mode 2: target-in-cohort context (per-target lookup)

```
/surfaceome-cohort-ranking COADREAD --target MSLN
```

Emits the full table PLUS an annotated section highlighting MSLN's
percentile + concordance call. Used by target-profile to answer "where
does MSLN rank against all surface proteins in this tissue?"

## Output tree (data_package shape)

```
<out>/
├── decision.json                          # rule verdicts on target (if provided)
├── summary.yaml
└── provenance.yaml                        # data_provenance (manifest IDs)
```

NOTE (revived 2026-08-20): the `surfaceome-cohort-ranking-per-indication-v1`
derived product LANDED 2026-08-18 (36,150 rows / 29 indications, live md5-pinned
S3). The reader now returns REAL ranking rows, so the ranking tables +
waterfall figure are produced for covered indications. The product is
pre-filtered at build (relative robustness `cells_supporting >= min(2, cells_ran)`,
dominant_direction==up) — the skill does NO additional cells_supporting re-filter.

## What this skill does NOT do

- **NOT full target-ID mode:** does not walk the druggable-genome / TF-ome
  / secretome universes. Only the SURFY-confirmed surfaceome, only within
  a single indication.
- **NOT modality-calibrated:** the ranking is a biology-agnostic effect-
  size ordering. Modality-fit reasoning (ADC vs TCE) lives in
  tractability-and-modality, not here.
- **NOT cross-indication:** rankings are per-indication. Cross-indication
  rank pattern (a target's ranking across multiple tissues) is a
  documented iter-2 backlog item (surfaceome-cross-indication-rank-summary
  derived product).

## Provenance discipline

- `sensitivity_manifest_ids`: which per-indication sensitivity products
  contributed
- `surfaceome_family_manifest_id`: surfaceome-family-classification-per-
  uniprot-v1 md5
- `cptac_manifest_id`: cptac-protein-tumor-vs-normal-per-cohort-v1 md5
  (if applicable to the indication)
- `robustness_filter`: product-level `cells_supporting >= min(2, cells_ran)` (no skill-side re-filter)
- `n_ranked`: count of surface proteins in the emitted (pre-filtered) ranking

## Iter-2 roadmap

1. Cross-indication rank summary product (per-target rank pattern across
   all 18 indications).
2. Modality-calibrated ranking (weight the ranking by modality-viability
   features from adc-tce-modality-fit).
3. Full target-ID mode (separate architectural pass — druggable-genome +
   TF-ome + secretome + surfaceome universes with modality-conditional
   ranking).
