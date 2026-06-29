"""dge_deseq2 — DESeq2-based differential expression analysis method.

Carved out from rnd-computational-biology-oncology-claude-oncology-skills/batch/expression_rna_COADREAD/
on 2026-06-26 (R4 in A1's refactor sequencing). The R step scripts (steps/00_load_counts.R ...
steps/05_provenance.R) are preserved verbatim from the source; this module adds a Python CLI
wrapper that parameterizes indication and drives the R pipeline via `Rscript steps/run_pipeline.R`.
"""

__version__ = "0.1.0"

from .read import read_dge_gene_row

__all__ = ["read_dge_gene_row"]
