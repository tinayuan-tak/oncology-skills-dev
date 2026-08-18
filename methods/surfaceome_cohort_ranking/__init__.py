"""surfaceome_cohort_ranking — per-indication whole-surfaceome effect-size ranking.

Composes a target-scan-mode product: per indication, rank all surface-confirmed proteins
(intersected with surfaceome-family-classification) by tumor-vs-normal effect size, keeping
comparator-robust tumor-up hits, then overlay CPTAC protein concordance. Reads the DESeq2
sensitivity products materialized at s3://onc-compbio/data-catalog/derived/{indication}-dge-
tumor-vs-normal-sensitivity-v1/.

Companion:
    data-catalog:manifests/derived/surfaceome-cohort-ranking-per-indication-v1.yaml

Consumer: surfaceome-cohort-ranking evidence card + skill (Phase F target-scan
hook) — a percentile-context lookup product that target-profile joins against.

Design: composes from the sensitivity DEG so effect sizes are directly comparable to per-target
profile outputs, and the ranking is comparator-robustness-aware. The sensitivity products are
HETEROGENEOUS (1-3 comparator "cells" per indication; column sets differ), so the robustness
filter is RELATIVE — keep genes supported by >= min(min_cells_supporting, cells_ran) cells — which
scales from single-cell indications (OV) to 3-cell products without dropping any wired indication.
(This supersedes the original scaffold's fixed 4-cell / cells_supporting>=3 assumption, which
returned zero rows against the real products.) Compute lives in derive.py (unit-tested, S3-free).
"""
METHOD_VERSION = "0.1.0"

from .read import read_target_summary  # noqa: F401,E402
