"""sc_normal_expression — single-cell RNA expression in NORMAL tissue by cell type.

Backs the safety-surface card `sc-normal-celltype-expression` (measurement: sc_rna,
sample_context: normal) — the cell-type-resolved on-target-off-tumor safety substrate for
ADC/BiTE/TCE programs. The sc-unique axis: per-cell-type detection in NORMAL tissue across
many donors (CELLxGENE Census), where bulk RNA averages across all cell types and loses the
cardiomyocyte vs fibroblast distinction that determines safety liability class.

Substrate: sc-normal-celltype-expression-{tissue}-v1 Tier-1 parquets (cross-donor aggregations
built by aggregate.py from the sc-pseudobulk-normal-celltype-{tissue}-v1 Tier-2 products).
  - median_det: cross-donor median detection_fraction per (gene, cell_type)
  - expressing_donor_fraction: fraction of reliable donors (n_cells >= 10) that express
  - n_donors_reliable: donors with n_cells >= 10 in the group

read (read.py):   per-gene predicate-pushdown reader over the Tier-1 parquet (pyarrow/boto3 only).
stats (stats.py): pure cell-type roll-up + the normal-tissue liability classifier (numpy/pandas).
aggregate.py:     Tier-2 → Tier-1 DuckDB cross-donor aggregation script (CLI, produces the product).
"""
from .read import read_target_summary
