"""spatial_colocalization — tumour–normal SPATIAL co-localization reader (imaging single-cell).

Reads the spatial-coloc-tumor-{indication}-v1 products (data-catalog scripts/aggregate_spatial_
neighborhood.py; CosMx/Xenium/MERFISH). For a target on malignant cells, reports which neighbour
compartments (immune / stromal / endothelial / normal epithelium) are spatially CO-LOCALIZED with the
target-positive malignant cells — the tissue-architecture / bystander-safety axis that dissociated
scRNA (sc_tumor_expression_celltype, pair_selectivity_gate.samecell) is blind to.

Modules:
- read.py   — pyarrow predicate-pushdown reader (gene-sorted product) + the neighbourhood assembler;
              INDICATION_TO_SPATIAL_COLOC map (pinned manifest ids). NO squidpy/anndata at read time.
- stats.py  — pure DONOR-is-replicate roll-up (cross-donor median) + spatial_coloc_class classifier.
- cli.py    — build_summary(target, indication) -> dict (the live-reader entry) + argparse main.
"""
