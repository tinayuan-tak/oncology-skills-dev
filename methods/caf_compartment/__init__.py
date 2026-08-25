"""caf_compartment — pan-cancer CANCER-ASSOCIATED-FIBROBLAST (CAF) state presence layer.

Backs the immune-context skill's stromal/CAF lens (VERDICT-INERT display card
caf-compartment-expression-luo). The stromal sibling of the malignant/TME-compartment
sc_tumor_celltype pseudobulk products — completes the TME triad's stromal/CAF lane.

Substrate: sc-pseudobulk-caf-luo-pancancer-v1 (data-catalog derived) — one row per
(gene_symbol, caf_subtype, cancer_type) over the Luo et al. 2022 pan-cancer CAF atlas (GEO GSE210347).
The grain is the CAF subtype (CAFmyo / CAFinfla / CAFadi / CAFEndMT / CAFPN / CAFap / NIF); statistics
are detection_fraction + abundance_log1p_cp10k.

read (read.py): per-gene predicate-pushdown reader over the gene-SORTED pseudobulk parquet (pyarrow
                S3FileSystem + gene_symbol pushdown), summarising to a per-gene CAF-state shape
                (pyarrow/pandas/boto3 only). Absence-disciplined: 404 / no landed product ->
                data_unavailable; transient S3 faults propagate.
"""
from .read import read_target_summary

__all__ = ["read_target_summary"]
