"""sclc_dge_tumor_vs_gtex — SCLC-tumor vs GTEx-lung differential expression.

SCLC (small-cell lung cancer) has no TCGA cohort and, in the ingested George
et al. 2015 cohort (`sclc-george-tpm-long-v1`), ZERO adjacent-normal samples —
SCLC is rarely resected, so no public paired-adjacent RNA-seq exists. A literal
tumor-vs-adjacent contrast is therefore impossible.

This method builds the tractable substitute the framework already uses for every
non-COADREAD indication: SCLC-tumor vs GTEx-LUNG (tissue-of-origin), emitting the
SAME per-gene DEG schema as the `{indication}-dge-tumor-vs-gtex-v1` products so
the existing `dge_deseq2.read.read_tumor_vs_gtex_gene_row` reader consumes it
with zero reader changes (it resolves the product by the id pattern).

IMPORTANT — why this is a SEPARATE method, not a param on dge_tcga_gtex_precompute:
that sibling reads RAW recount3 gene-sum counts and computes its own log2(CPM+1).
SCLC has NO raw counts (the George raw data is EGA-controlled; only the cBioPortal
FPKM matrix was ingested, harmonized to log2(TPM+1)). You cannot CPM-normalize a
TPM matrix. So this method operates directly on the two pre-normalized long-TPM
products, both already log2(TPM+1) on the same recount3 unversioned-Ensembl axis:

    tumor : sclc-george-tpm-long-v1        (study='SCLC', 81 tumors)
    normal: gtex-tpm-recount3-long-v1       (tissue='LUNG')

The Welch's t-test + BH kernel is REUSED verbatim from dge_tcga_gtex_precompute
(same math, same stats convention) — only the input unit changes (log2_tpm, not
log2_cpm). Positive log2_fc = up in tumor.

CROSS-COHORT BATCH CAVEAT (mandatory, stronger than the TCGA-vs-GTEx siblings):
George is hg19/FPKM-derived; GTEx is hg38/recount3. Same log2(TPM+1) UNIT but
DIFFERENT gene models and sequencing pipelines. A raw log2FC conflates biology
with cross-cohort batch. This product is a DIRECTIONAL over-expression screen vs
canonical healthy lung — NOT paired-adjacent rigor, NOT even within-recount3
tumor-vs-GTEx rigor. ComBat-seq is not applicable (no shared count space; and
source-confounded-with-condition risks over-correction). The caveat is the honest
instrument; it is recorded in the manifest and must surface to consumers.
"""
