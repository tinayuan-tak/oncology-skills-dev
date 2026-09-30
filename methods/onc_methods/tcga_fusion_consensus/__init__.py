"""tcga_fusion_consensus — pan-TCGA fusion consensus product.

Builds a per-(sample, gene) parquet from three ingested TCGA fusion callers
(TumorFusions/Hu 2018 PRADA, Gao 2018 Cell Reports, cBioPortal TCGA PanCancer
Atlas 2018), preserving each caller's per-partner + frame-prediction detail so
downstream consumers can pick their own consensus threshold
(caller_count >= 1 for union / >= 2 for majority / == 3 for strict).
"""

# Per-target reader over the derived product — the fusion-rearrangement-landscape card
# dispatcher getattr's this off the package.
from .read import read_target_summary  # noqa: F401,E402
