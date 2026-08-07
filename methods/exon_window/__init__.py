"""exon_window — per-EXON tumor-vs-normal therapeutic window (enrichment E5).

The exon-resolution twin of tcga_gtex_tpm_quantiles.window. Reads tcga-gtex-exon-tpm-quantiles-v1
and emits `exon_window_class` ∈ {exon_heterogeneity_flag | uniform_gene_window |
essential_exon_liability | not_expressed_in_cohort | not_in_product | data_unavailable}.

HONEST SCOPE (live-smoke-calibrated): a HYPOTHESIS-GENERATING within-gene exon-heterogeneity +
window flag, NOT an isoform-identity call. Per-exon coverage quantiles are blind to transcript
membership, so this CANNOT confirm a specific isoform (can't resolve CLDN18.2 from CLDN18.1);
exon_heterogeneity_flag = "worth junction-level follow-up". Scores exon INCLUSION not SKIPPING.
"""
from .read import read_exon_window  # noqa: F401
METHOD_VERSION = "1.1.0"
