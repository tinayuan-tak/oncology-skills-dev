"""pancan_mutation_ccf.read — card-side reader for the per-(gene, indication) clonality product.

Reads the MATERIALIZED combined clonality table (one row per (indication, gene); the standard
single-payload derived-schema shape mirroring genie-registry-per-sample-maf-v1 / precog) and returns
the per-(gene, indication) summary the target-clonality card consumes. Genuinely TARGET-dependent, so
both `gene` and `indication` filter. Graceful data_unavailable when the gene is not recurrently mutated
in-indication (below the aggregator's MIN_MUTANT_SAMPLES floor → not in the product) or the product /
indication is absent. Mirrors precog_prognostic.read's S3-resolve pattern (aws s3 cp → pandas).
"""
from __future__ import annotations

import io
from functools import lru_cache
from typing import Optional

_DERIVED_S3 = ("s3://onc-compbio/data-catalog/derived/"
               "pancan-mutation-clonality-per-gene-v1/pancan_mutation_clonality_per_gene.parquet")

_UNAVAILABLE = {
    "clonality_class": "data_unavailable",
    "clonal_fraction": None,
    "median_ccf": None,
    "n_mutant_samples": 0,
    "evidence_tier": "inferred_diploid",
}


from methods.target_id_sidecar import ensure_aws_profile, is_definitively_absent


@lru_cache(maxsize=2)
def _load_product(product_path: "Optional[str]" = None):
    """Load the combined clonality product (local product_path override for tests, else S3).

    Absence-discipline: a genuinely-missing product/object returns None (honest data_unavailable),
    but a transient / creds / broken-env error re-raises instead of masking as absence — a silent
    None here would drop the clonality facet for every target on a broken S3, indistinguishable
    from the object simply not existing.
    """
    import pandas as pd
    if product_path:
        from pathlib import Path
        return pd.read_parquet(product_path) if Path(product_path).exists() else None
    ensure_aws_profile()
    import boto3
    bucket, key = _DERIVED_S3[len("s3://"):].split("/", 1)
    try:
        obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
        return pd.read_parquet(io.BytesIO(obj["Body"].read()))
    except Exception as e:  # noqa: BLE001
        if not is_definitively_absent(e):
            raise
        return None


def read_clonality(gene: "Optional[str]" = None, indication: "Optional[str]" = None,
                   product_path: "Optional[str]" = None, *, target: "Optional[str]" = None) -> dict:
    """Per-(gene, indication) clonality summary for the target-clonality card. VERDICT-INERT signal.

    Accepts `target` as an alias for `gene` to satisfy the compose-dashboard generic-dispatch contract
    (_live_readers._generic_dispatch calls every reader as fn(target=, indication=), where `target` is
    the gene symbol). Without this the card silently errored to data_unavailable in every live
    composition."""
    gene = gene or target
    df = _load_product(product_path)
    if df is None or df.empty:
        return dict(_UNAVAILABLE, _missing_reason="no clonality product materialized/reachable")
    hit = df[(df["gene_symbol"] == gene) & (df["indication"] == indication)]
    if hit.empty:
        return dict(_UNAVAILABLE,
                    _missing_reason=f"{gene} not recurrently mutated in {indication} (below floor) "
                                    f"or indication not materialized")
    row = hit.iloc[0]

    def _f(v):
        return None if v is None or (isinstance(v, float) and v != v) else float(v)   # NaN-safe

    return {
        "clonality_class": row["clonality_class"],
        "clonal_fraction": _f(row["clonal_fraction"]),
        "median_ccf": _f(row["median_ccf"]),
        "n_mutant_samples": int(row["n_mutant_samples"]),
        "evidence_tier": row["evidence_tier"],
    }
