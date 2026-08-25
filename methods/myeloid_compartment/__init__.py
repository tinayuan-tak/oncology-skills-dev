"""myeloid_compartment — pan-cancer tumour-infiltrating MYELOID-state presence layer.

Backs the immune-context skill's suppressive-TME / myeloid-target lens (VERDICT-INERT display card
myeloid-compartment-expression-cheng). The myeloid sibling of the malignant/TME-compartment
sc_tumor_celltype pseudobulk products — completes the TME triad's myeloid lane.

Substrate: sc-pseudobulk-myeloid-cheng-v1 (data-catalog derived) — one row per
(gene_symbol, cancer_type, myeloid_subtype) over the Cheng et al. 2021 pan-cancer atlas of
tumour-infiltrating myeloid cells (GEO GSE154763). The grain is the author myeloid cell-STATE
(MajorCluster, e.g. M06_Macro_ISG15); statistics are detection_fraction + abundance_log1p_cp10k.

read (read.py): per-gene predicate-pushdown reader over the gene-SORTED pseudobulk parquet (pyarrow
                S3FileSystem + gene_symbol pushdown), summarising to a per-gene myeloid-state shape
                (pyarrow/pandas/boto3 only — no scanpy/anndata at read time). Absence-disciplined:
                404 / no landed product -> data_unavailable; transient S3 faults propagate.
"""
from .read import read_target_summary

__all__ = ["read_target_summary"]
