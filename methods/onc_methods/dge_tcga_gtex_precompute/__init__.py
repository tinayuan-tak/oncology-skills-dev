"""dge_tcga_gtex_precompute — batch DEG for TCGA-tumor vs GTEx-unmatched-normal.

Complements the existing TCGA-tumor-vs-adjacent DEG (methods/dge_deseq2's R
pipeline, product coadread-dge-df06320) with an orthogonal
tumor-vs-population-normal contrast. Uses the recount3 substrate at
s3://onc-compbio/data-catalog/sources/recount3/tcga-gtex-2023-01-04/ for both
sides of the contrast.

Design decisions (locked 2026-07-02):
  - Welch's t-test on log2(CPM+1) — pragmatic single-gene DEG stat that
    doesn't require R DESeq2 at emit-time. Sufficient for target-eval
    selectivity readouts (within-gene tumor-vs-normal contrasts).
  - CPM normalization skips gene-length: acceptable for within-gene
    contrast, avoids Gencode-v26 gene-length dependency.
  - BH-correct q-values across all HGNC-mappable protein-coding genes per
    indication.
  - Output: per-gene parquet with log2_fc, p_value, q_value, n_tumor,
    n_gtex_normal, mean_log2cpm_tumor, mean_log2cpm_gtex_normal, is_significant,
    is_upregulated_provider_call. Schema-parallel to the existing DGE product.

Runs per indication as a batch. First target: COADREAD (TCGA COAD+READ vs
GTEx COLON). Extends to LUAD/BRCA/PAAD/... as batch runs.
"""
