"""pdxe_drug_response — per-gene PDXE IN-VIVO drug-response rollup reader.

Backs the translational-readiness skill's PDX in-vivo tractability-corroboration lens (VERDICT-INERT
display card target-pdx-drug-response). Answers, for a target gene, whether treatments that name the
gene as a target produced tumour regression in Novartis PDXE (Gao et al. 2015) PDX population trials —
the in-vivo complement to the in-vitro cell-line drug-response rollups (GDSC / PRISM).

Substrate: pdxe-drug-response-per-gene-v1 (data-catalog derived) — one row per PDXE 'Treatment target'
gene token, aggregating median/min BestAvgResponse + objective-responder fraction + the most-active
treatment across all treatments naming the token and all models. TARGET-GRAIN (gene_symbol ONLY): PDXE
carries no per-indication response split in this rollup, so `indication` is accepted and IGNORED.

read (read.py): per-gene predicate-pushdown reader over the gene-SORTED per-gene parquet (pyarrow
                S3FileSystem + gene_symbol pushdown, @lru_cache), summarising to a per-gene PDX
                in-vivo-response shape (pyarrow/pandas/boto3 only). Absence-disciplined: 404 / no
                product -> data_unavailable; transient S3 faults propagate.
"""
from .read import read_target_summary

__all__ = ["read_target_summary"]
