"""read.py — runtime reader for the co-essentiality substrate.

Single entry point: read_coessential_partners(target, top_n, ...).
Reads the gene-sorted parquet with predicate pushdown — only the row-groups
for the queried gene are loaded (< 1 s per call on a cold parquet, < 200 ms warm).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pyarrow.parquet as pq

from . import METHOD_VERSION

DEFAULT_AWS_PROFILE = "cbg"
MANIFEST_ID = "depmap-coessentiality-26q1-v1"
_CACHE_DIR = Path.home() / ".cache" / "framework-depmap-26q1-parquet"
_CACHED_PATH = _CACHE_DIR / "coessentiality_edges.parquet"


def _resolve_s3_uri() -> str:
    """Resolve the manifest-authoritative S3 URI at call time (not at import)."""
    from methods.catalog_query.read import s3_uri_for
    return s3_uri_for(MANIFEST_ID)


def _ensure_aws_profile() -> None:
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


def _local_path() -> Optional[Path]:
    """Return a local-cache hit, or None."""
    return _CACHED_PATH if _CACHED_PATH.exists() else None


def read_coessential_partners(
    target: str,
    top_n: int = 25,
    min_abs_r: float = 0.0,
    parquet_path: Optional[str] = None,
    aws_profile: str = DEFAULT_AWS_PROFILE,
) -> dict:
    """Return top-N co-essential partners for a gene from the pre-built substrate.

    Args:
        target:       HGNC gene symbol (e.g. "KRAS").
        top_n:        Number of partners to return (ranked by |r|, default 25).
                      Capped at what is available (the substrate stores top-100).
        min_abs_r:    Optional additional |r| floor applied at read-time.
        parquet_path: Override the default S3/cache path (local path or s3:// URI).
        aws_profile:  AWS profile for S3 reads (default: cbg).

    Returns a dict with:
        gene_symbol:      queried symbol
        partners:         list of dicts [{symbol, pearson_r, abs_rank, direction}]
        n_partners:       number of partners returned
        n_cell_lines:     DepMap 26Q1 cell lines used in the pre-build
        method_version:   MODULE_VERSION from __init__
        substrate_uri:    resolved path used
        _data_unavailable: present (True) if the substrate could not be read
    """
    _ensure_aws_profile()
    local = _local_path() if not parquet_path else None
    if parquet_path:
        path = parquet_path
    elif local:
        path = str(local)
    else:
        path = _resolve_s3_uri()

    try:
        # Predicate pushdown: only row-groups covering this gene are read.
        table = pq.read_table(
            path,
            filters=[("gene_symbol", "==", target)],
            columns=["gene_symbol", "partner_symbol", "pearson_r", "abs_rank", "n_cell_lines"],
        )
    except Exception as exc:
        return {
            "gene_symbol": target,
            "partners": [],
            "n_partners": 0,
            "_data_unavailable": True,
            "_error": str(exc),
            "method_version": METHOD_VERSION,
            "substrate_uri": path,
        }

    if len(table) == 0:
        return {
            "gene_symbol": target,
            "partners": [],
            "n_partners": 0,
            "_data_unavailable": True,
            "_reason": f"gene '{target}' not found in coessentiality substrate",
            "method_version": METHOD_VERSION,
            "substrate_uri": path,
        }

    df = table.to_pandas()

    # Optional extra |r| filter (substrate already stores >=0.2 by default)
    if min_abs_r > 0:
        df = df[df["pearson_r"].abs() >= min_abs_r]

    # Sort by abs_rank (already sorted, but honour override filter re-rank)
    df = df.sort_values("abs_rank").head(top_n)

    n_cell_lines = int(df["n_cell_lines"].iloc[0]) if len(df) else 0

    partners = [
        {
            "symbol": row.partner_symbol,
            "pearson_r": round(float(row.pearson_r), 4),
            "abs_rank": int(row.abs_rank),
            "direction": "co-essential" if row.pearson_r >= 0 else "anti-correlated",
        }
        for row in df.itertuples(index=False)
    ]

    return {
        "gene_symbol": target,
        "partners": partners,
        "n_partners": len(partners),
        "n_cell_lines": n_cell_lines,
        "method_version": METHOD_VERSION,
        "substrate_uri": path,
    }
