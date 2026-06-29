"""depmap_chronos_distribution — pan-cancer Chronos distribution analysis method.

Consumes DepMap 26Q1 CRISPRGeneEffect + Model and emits the pan-cancer dependency
distribution card output: summary stats, two SVG figures (waterfall + histogram-KDE),
and a per-cell-line plot_data Parquet.

Implementation reads DepMap files from the data-catalog manifest (S3 URI when AWS
credentials available; local cache otherwise). Backwards-compatible: when CRISPRGeneEffect
or Model is unreachable, the method emits a structured _live_read_error so callers can
fall back to stub fixtures.

Public API for live-reader dispatcher:
    read_pan_cancer_distribution(target, indication=None) -> dict
"""

__version__ = "0.1.0"

from .read import read_pan_cancer_distribution

__all__ = ["read_pan_cancer_distribution"]
