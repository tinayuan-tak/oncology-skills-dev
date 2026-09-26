"""depmap_predictability — thin lookup card method (E5).

Reads a single row from the frozen derived parquet
`s3://onc-compbio/data-catalog/derived/depmap-predictability-26q3-v4/predictability_per_gene.parquet`
via pyarrow predicate pushdown. NO sklearn at framework run-time; the precompute
pipeline `depmap_predictability_precompute` produced the parquet.

Public API for the live-reader dispatcher:
    read_predictability(target, indication=None, release_pin=...) -> dict
"""

__version__ = "0.2.0"

from .read import read_predictability

__all__ = ["read_predictability"]
