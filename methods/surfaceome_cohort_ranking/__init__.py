"""surfaceome_cohort_ranking — per-tissue whole-surfaceome effect-size ranking.

Composes a target-scan-mode product: per indication, rank all surface proteins
(intersected with the SURFY high-confidence set + cells_supporting >= 3 filter)
by tumor-vs-normal effect size. Reads the 4-cell DESeq2 sensitivity products
already materialized at s3://onc-compbio/data-catalog/derived/{indication}-dge-
tumor-vs-normal-sensitivity-v1/ + fuses with the surfaceome-family-classification
derived product to filter to surface-only.

Companion:
    data-catalog:manifests/derived/surfaceome-cohort-ranking-per-indication-v1.yaml

Consumer: surfaceome-cohort-ranking evidence card + skill (Phase F target-scan
hook) — a percentile-context lookup product that target-profile joins against.

Reviewer-driven design (2026-07-08): the dashboard's iDAS ranking uses a single
limma run vs. cohort-bulk; ours composes from the 4-cell sensitivity DEG so
effect sizes are directly comparable to per-target profile outputs, AND the
ranking is cells_supporting-aware (surface proteins with cells_supporting < 3
are excluded so the top of the list isn't dominated by 1-cell false positives).
"""
METHOD_VERSION = "0.1.0"
