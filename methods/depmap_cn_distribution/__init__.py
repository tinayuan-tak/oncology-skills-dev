"""depmap_cn_distribution — pan-cancer copy-number distribution analysis method.

Consumes DepMap 26Q1 OmicsCNGeneWGS.csv (canonical, preferred) + OmicsCNGeneMC_WES.csv
(legacy fallback when the target gene is absent from the WGS matrix) + Model.csv (for
ModelConditionID → ModelID + lineage bridge). Emits gene-level CN distribution
stats, lineage stratification, and a descriptive copy_number_class label.

Public API for live-reader dispatcher:
    read_cn_distribution(target, indication=None) -> dict
"""

__version__ = "0.1.0"

from .read import read_cn_distribution

__all__ = ["read_cn_distribution"]
