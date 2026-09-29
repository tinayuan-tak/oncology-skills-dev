"""depmap_demeter_distribution — pan-cancer RNAi (DEMETER2) distribution analysis method.

Consumes DepMap 26Q1 RNAi D2_combined_gene_dep_scores.csv + sample_info.csv (CCLE_ID
namespace) and emits the pan-cancer-rnai-dependency-distribution card output: summary
stats, two SVG figures (waterfall + histogram-KDE), and a per-cell-line plot_data
Parquet.

Mirrors the depmap_chronos_distribution sibling package structurally; differences are
documented inline (transposed matrix shape, CCLE_ID legacy namespace, DEMETER2 score
scale thresholds).

Public API for live-reader dispatcher:
    read_pan_cancer_rnai_distribution(target, indication=None) -> dict
"""

__version__ = "0.1.0"

from .read import read_pan_cancer_rnai_distribution

__all__ = ["read_pan_cancer_rnai_distribution"]
