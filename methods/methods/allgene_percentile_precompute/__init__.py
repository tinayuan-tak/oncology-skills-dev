"""allgene_percentile_precompute — precompute per-gene all-gene percentile products.

Phase 1C of the tumor-presence contextualized-interpretation enhancement. The RNA
cards read wide/multi-GB products, so a per-render all-gene-null scan is too expensive.
This builds two small, gene-sorted lookup products so a card reader can pushdown a
single gene's percentile-among-all-genes:

  build_tumor_rank.py  — per (source, group) all-gene rank of the tumor/normal MEDIAN,
                         DERIVED from the existing tcga-gtex-tpm-tissue-quantiles-v1
                         (aggregation-only, no re-scan of the multi-GB raw long products).
                         → tumor-rna-distribution card.
  build_depmap_rank.py — pan-cancer all-gene rank of the DepMap panel MEDIAN log2(TPM+1),
                         from the wide OmicsExpression matrix.
                         → cellline-rna-distribution card.

Both mirror the tcga_gtex_tpm_quantiles producer discipline: DuckDB/pandas compute →
gene-sorted parquet (row-group pushdown on ensembl_gene_id/gene_symbol) → snappy →
md5 stamped → S3 upload gated behind --no-upload. git_commit is hand-authored into the
data-catalog manifest (repo convention).
"""

from __future__ import annotations
