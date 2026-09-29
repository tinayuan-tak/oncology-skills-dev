"""depmap_parquet_precompute — one-time batch job converting DepMap 26Q3 CSVs to parquet.

Produces a derived data product at:
    s3://onc-compbio/data-catalog/derived/depmap-26q3-parquet-v1/

with parquet versions of:
  - CRISPRGeneEffect (cell-line rows × gene cols; column-projection reads)
  - OmicsExpressionTPMLogp1HumanProteinCodingGenes (with metadata cols preserved)
  - OmicsCNGeneMC_WES + OmicsCNGeneWGS (with MC-ID index)
  - D2_combined_gene_dep_scores (RNAi DEMETER2; transposed gene-cols orientation)
  - OmicsSomaticMutations (partitioned by HugoSymbol for row-group predicate pushdown)

Plus a manifest.yaml documenting input hashes + row counts + column counts.

RUN THIS ONCE per DepMap release. Subsequent framework runs read the parquets
via pyarrow.dataset with column projection — cutting per-fetch size from
500 MB CSVs to 1-2 MB parquet column reads.

CLI:
    python -m methods.depmap_parquet_precompute.cli --release-pin 26q3 \
        --output-prefix s3://onc-compbio/data-catalog/derived/depmap-26q3-parquet-v1/
"""

__version__ = "0.1.0"
