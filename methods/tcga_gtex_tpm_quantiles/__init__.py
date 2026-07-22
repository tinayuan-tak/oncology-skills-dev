"""tcga_gtex_tpm_quantiles — pan-cancer by-tissue TPM distribution SUMMARY product.

The render-path companion to the two multi-GB long TPM products
(tcga-tumor-tpm-recount3-long-v1 + gtex-tpm-recount3-long-v1). A per-gene
predicate-pushdown read of either long product costs 7-35s local / 65-132s from S3
(Parquet footer parse over ~51k-96k row-groups) — far too slow for a dashboard render
and the two raw products (6 GB) don't fit the host's free disk. A boxplot needs only
five numbers per group (min/Q1/median/Q3/max), so this method precomputes, ONCE at emit
time, the per-(gene, source, group) distribution quantiles of log2(TPM+1) and stacks
TCGA-tumor (per study) + GTEx-normal (per tissue) into ONE small product on a shared
gene axis and a shared log2(TPM+1) unit — exactly what the pan-cancer tumor-vs-normal
by-tissue distribution figure co-plots.

NO re-normalization: reads the already-computed log2(TPM+1) values straight from the two
long products (both derived from the SAME recount3/Monorail substrate + GENCODE v26, so
tumor and normal are already on one comparable axis). This method only AGGREGATES.

Output long/tidy parquet, one row per (gene, source, group):
    gene_symbol       string   HGNC symbol (informational; not unique)
    ensembl_gene_id   string   ENSG stem — PRIMARY KEY axis (shared by both long products)
    source            string   tcga_tumor | gtex_normal
    group             string   TCGA study code (COAD, GBM, ...) OR GTEx tissue (BRAIN, ...)
    n                 int32    samples in the (gene, source, group) cell
    min, q1, median, q3, max   float32   log2(TPM+1) five-number summary
    mean              float32  log2(TPM+1) mean (convenience)
Sorted by (ensembl_gene_id, source, group) with modest row-groups so a per-gene read
prunes to a few row-groups (the whole point).

Whisker rendering note: only the five-number summary is stored, NOT the Tukey within-fence
extreme data points. The figure emitter draws whiskers by clamping the 1.5xIQR fence to
[min, max]; this slightly overextends a whisker to the fence rather than the nearest data
point, a standard summary-boxplot approximation, documented on the manifest.
"""
