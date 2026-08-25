"""ici_response — per-gene immune-checkpoint-inhibitor (ICI) RESPONSE expression-association layer.

Backs the immune-context skill's ICI-response lens (VERDICT-INERT display card
ici-response-association). Answers, for a gene, whether its baseline expression is higher in ICI
RESPONDERS than non-responders in open-GEO melanoma cohorts — the biomarker complement to the
CIBERSORT effector-context call.

Substrate: ici-response-expression-per-gene-v1 (data-catalog derived) — one row per
(gene_symbol, cohort) over open-GEO melanoma anti-PD-1 cohorts (Riaz GSE91061 nivolumab, Hugo
GSE78220 pembrolizumab) plus a `pan-melanoma-rollup` cross-cohort meta-row (signed-Stouffer combine).

read (read.py): per-gene predicate-pushdown reader over the gene-SORTED per-gene parquet (pyarrow
                S3FileSystem + gene_symbol pushdown), summarising to a per-gene ICI-association shape
                (pyarrow/pandas/boto3 only). Absence-disciplined: 404 / no product -> data_unavailable;
                transient S3 faults propagate.
"""
from .read import read_target_summary

__all__ = ["read_target_summary"]
