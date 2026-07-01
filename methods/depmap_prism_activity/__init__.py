"""depmap_prism_activity — thin lookup card (E6) for PRISM small-molecule viability.

Reads one gene row from the frozen derived parquet
`s3://onc-compbio/data-catalog/derived/depmap-prism-activity-v1/prism_activity_per_gene.parquet`
via pyarrow predicate pushdown. The batch precompute lives in the sibling
`methods.depmap_prism_precompute` — see its cli.py for the ingestion pipeline.

Answers the target-evaluation question: "Is there an existing compound that
targets this gene, and does it kill cell lines in a target-relevant pattern?"

The card carries its OWN release_pin (`prism-activity-v1`) separately from the
26q1 CRISPR substrate — PRISM is off-substrate. Manifest citation is explicit
per plan Q5.
"""
