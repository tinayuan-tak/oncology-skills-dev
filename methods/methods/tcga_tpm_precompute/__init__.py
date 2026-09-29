"""tcga-tpm-precompute — materialize the recount3-derived per-sample TCGA TUMOR
TPM matrix (the tumor analogue of gtex_tpm_precompute).

TPM DEFINITION (identical to the GTEx product + the on-demand dge_deseq2 reader):

    TPM_ij = (count_ij / length_kb_i) / sum_i(count_ij / length_kb_i) * 1e6
    value  = log2(TPM + 1)  as float32

where i indexes genes, j indexes samples, and length_kb is the GENCODE-v26
union-of-exon gene length in kb (methods.dge_deseq2.gene_lengths).

DENOMINATOR INVARIANT (do not "optimize" away): the per-sample RPK-sum
denominator accumulates over ALL length-having genes (~58k), NOT just the
~41k HGNC-mappable OUTPUT rows. Restricting the denominator to the output
gene set would inflate every TPM. The two sets are decoupled: rpk_sum += rpk
runs for every length-having gene; out_rpk[...] is populated only for
HGNC-mappable genes.

WHY TPM (not CPM): unlike dge_tcga_gtex_precompute — which uses CPM because
its within-gene tumor-vs-normal t-test makes gene length cancel — this
per-sample product places TCGA tumor and GTEx normal on the SAME cross-gene,
cross-cohort comparable axis (the pan-tissue distribution plot). That
requires full gene-length TPM normalization.

THE ONE DELTA vs the GTEx emitter: TCGA carries mixed sample types, so we
filter to Primary Tumor (recount3 metadata `gdc_cases.samples.sample_type ==
"Primary Tumor"`, joined on the gene_sums column header = gdc_file_id). GTEx
is healthy-donor by design and needs no such filter.
"""
