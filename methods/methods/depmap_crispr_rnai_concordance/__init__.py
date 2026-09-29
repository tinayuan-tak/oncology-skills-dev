"""depmap_crispr_rnai_concordance — derived card computing CRISPR-RNAi concordance.

DERIVED CARD: this method composes the depmap_chronos_distribution + depmap_demeter_distribution
loaders to fetch CRISPR + RNAi score columns for the target, then partitions the
cell-line union into 8 concordance buckets (partition-preserving — no imputation).

Public API for live-reader dispatcher:
    read_crispr_rnai_concordance(target, indication=None) -> dict
"""

__version__ = "0.1.0"

from .read import read_crispr_rnai_concordance

__all__ = ["read_crispr_rnai_concordance"]
