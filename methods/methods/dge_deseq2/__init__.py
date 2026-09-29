"""dge_deseq2 — DESeq2-based differential expression analysis method.

Carved out from rnd-computational-biology-oncology-claude-oncology-skills/batch/expression_rna_COADREAD/
on 2026-06-26 (R4 in A1's refactor sequencing). Public API: `read` (this package's read-side
subpackage, `dge_deseq2.read`) for consumers; `cli` drives the R pipeline via
`Rscript r/live/run_pipeline.R`. The R scripts live under r/live/ (production recount3
four-cell path) and r/legacy/ (quarantined single-cell GDC-STAR chain + the dev-only,
unwired Xena/Toil loader — see r/legacy/README.md); reorganized 2026-09-23 (analysis-methods
issue#692, S0 of the dge_deseq2 modernization arc, issue#690).
"""

__version__ = "0.3.0"

# Re-export the pan-cancer RNA breadth reader so compose-dashboard's _import_method
# (which imports the PACKAGE, then getattrs the fn) resolves it — same pattern as the
# CPTAC method's __init__ re-export of read_tumor_elevation_breadth.
from .derive_pancan_stack import read_rna_tumor_elevation_breadth
from .read import (
    read_dge_gene_row,
    read_per_sample_expression_all_three_groups,
    read_per_sample_expression_tumor_vs_adjacent,
    read_tumor_vs_gtex_gene_row,
    read_tumor_vs_normal_selectivity,
    read_tumor_vs_normal_sensitivity_gene_row,
)

__all__ = [
    "read_dge_gene_row",
    "read_tumor_vs_gtex_gene_row",
    "read_tumor_vs_normal_sensitivity_gene_row",
    "read_tumor_vs_normal_selectivity",
    "read_per_sample_expression_tumor_vs_adjacent",
    "read_per_sample_expression_all_three_groups",
    "read_rna_tumor_elevation_breadth",
]
