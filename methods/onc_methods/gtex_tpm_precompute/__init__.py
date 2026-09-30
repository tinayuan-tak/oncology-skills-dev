"""gtex_tpm_precompute — materialize the recount3-derived GTEx TPM matrix.

Promotes the per-gene, on-demand GTEx TPM computation in
methods/dge_deseq2/read.py (read_per_sample_expression_all_three_groups,
documented there as "Live-fetch (no persistent derived product)") into a
single precomputed wide matrix so the pan-tissue distribution figure and
any other downstream consumer can do a fast parquet read instead of
re-streaming the ~50-300 MB gzipped recount3 tissue files per gene, per
request.

WHY recount3-DERIVED (not the canonical GTEx v10 portal TPM):
  The primary consumer (the pan-tissue plot) places TCGA tumor and GTEx
  normal on the SAME log2(TPM+1) axis. For that contrast to be valid, both
  arms must be processed identically — which is exactly what recount3 /
  Monorail provides (uniform reprocessing of TCGA + GTEx at GENCODE v26).
  Swapping in GTEx v10 portal TPM (different pipeline + gene model) would
  reintroduce the batch confound recount3 removes. The canonical GTEx v10
  portal release is ingested SEPARATELY as a source manifest for standalone
  canonical-GTEx lookups (data-catalog gtex-v10-gene-tpm).

TPM definition (identical to dge_deseq2/read.py so values match the plot):
    rpk_ij   = count_ij / (gene_length_kb_i)
    rpk_sum_j = sum over ALL length-having genes i of rpk_ij   (per sample j)
    tpm_ij   = rpk_ij / rpk_sum_j * 1e6
    value    = log2(tpm_ij + 1)

CRITICAL INVARIANT: rpk_sum_j (the denominator) is summed over ALL genes
that have a Gencode-v26 length (~58k across all biotypes), NOT just the
protein-coding output genes. If the denominator were restricted to the
output rows, every TPM would be inflated. The emitter decouples
"denominator genes" (all length-having) from "output genes" (protein-coding
/ HGNC-mappable).

Output (one parquet + one sidecar under the derived prefix):
  gtex_tpm_log2.parquet   genes(protein-coding) × samples wide matrix,
                          value = log2(TPM+1) float32. Columns: gene_symbol,
                          ensembl_gene_id, then one column per GTEx sample_id.
                          Rows sorted by gene_symbol, row_group_size tuned for
                          per-gene predicate pushdown.
  gtex_sample_tissue.parquet  sample_id → tissue (recount3 GTEx tissue code) +
                          SMTS + SMTSD subregion. The column-axis key for the
                          wide matrix.

Runtime: ~15-30 min (dominated by S3 streams of the 31 gzipped tissue files;
BRAIN alone is ~300 MB). Per-tissue rpk_sums reuse the on-disk cache written
by dge_deseq2.read._fetch_recount3_rpk_sums when present.
"""
