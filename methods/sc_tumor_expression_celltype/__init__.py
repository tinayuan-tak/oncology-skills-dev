"""sc_tumor_expression_celltype — single-cell per-cell-type tumor presence layer.

Backs the tumor-presence skill's sc_rna/tumor bucket (measurement: sc_rna, sample_context: tumor):
the single-cell modality that carries two signals bulk RNA cannot — DETECTION_FRACTION (in how many
cells of a compartment the target is detected) and COMPARTMENT ATTRIBUTION (is the tumor signal
tumor-cell-intrinsic = malignant compartment, or microenvironmental = immune/stromal/endothelial).

Substrate: sc-pseudobulk-donor-celltype-{indication}-v1 (data-catalog derived) — one row per
dataset_id × donor_id × compartment × gene, from a filtered CELLxGENE Census query. The donor is the
biological replicate; compartment stats are cross-donor medians.

read (read.py):   per-gene predicate-pushdown reader over the pseudobulk parquet + the presence
                  assembler (pyarrow/pandas/numpy/boto3 only — no scanpy/anndata at read time).
stats (stats.py): pure per-compartment roll-up + the malignant-anchored classifier (numpy/pandas).
"""
