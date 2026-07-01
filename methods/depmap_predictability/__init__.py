"""depmap_predictability — thin lookup card method (E5).

Reads a single row from the frozen derived parquet
`s3://onc-compbio/data-catalog/derived/depmap-predictability-26q1-v1/predictability_per_gene.parquet`
via pyarrow predicate pushdown. NO sklearn at framework run-time; the precompute
pipeline `depmap_predictability_precompute` produced the parquet.
"""
