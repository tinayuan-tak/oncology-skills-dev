"""surfaceome_cohort_ranking.read — per-indication whole-surfaceome ranking.

Consumer: surfaceome-cohort-ranking evidence card + skill (Phase F target-
scan hook). Emits per-target percentile-context lookup within the ranked
surfaceome for a given indication.

Iter-1 wiring approach:
  - Reads derived parquet at
    s3://onc-compbio/data-catalog/derived/surfaceome-cohort-ranking-per-indication-v1/
  - Falls back to `data_unavailable` gracefully when derived product not on S3.
  - The upstream compute composes over all 18 wired tumor-vs-normal
    sensitivity products, filters cells_supporting >= 3, ranks per
    indication — this method is a per-target lookup into the result.

Runtime discipline: @lru_cache + module-level negative cache.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional


DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"
DERIVED_MANIFEST_ID = "surfaceome-cohort-ranking-per-indication-v1"
DERIVED_S3_KEY = (
    "data-catalog/derived/surfaceome-cohort-ranking-per-indication-v1/"
    "surfaceome_cohort_ranking.parquet"
)

CACHE_DIR = Path.home() / ".cache" / "framework-surfaceome-ranking"
CACHE_PARQUET = CACHE_DIR / "surfaceome_cohort_ranking.parquet"

_DERIVED_STATUS: Optional[bool] = None


def _boto3_client():
    import boto3
    return boto3.Session(profile_name=DEFAULT_AWS_PROFILE).client("s3")


def _ensure_derived_cached() -> Optional[Path]:
    global _DERIVED_STATUS
    if _DERIVED_STATUS is False:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if CACHE_PARQUET.exists() and CACHE_PARQUET.stat().st_size > 0:
        _DERIVED_STATUS = True
        return CACHE_PARQUET
    if _DERIVED_STATUS is None:
        try:
            s3 = _boto3_client()
            s3.download_file(S3_BUCKET, DERIVED_S3_KEY, str(CACHE_PARQUET))
            _DERIVED_STATUS = True
            return CACHE_PARQUET
        except Exception as e:
            # Distinguish "genuinely not published yet" (a definitive 404 /
            # NoSuchKey / access-denied) from a TRANSIENT failure (expired
            # creds, network blip, throttling). Only latch _DERIVED_STATUS =
            # False on the definitive case — that safely short-circuits every
            # later call in the process. For a transient error, LEAVE
            # _DERIVED_STATUS = None so a subsequent call retries instead of
            # poisoning the whole process with a false data_unavailable.
            resp = getattr(e, "response", None)
            code = resp.get("Error", {}).get("Code") if isinstance(resp, dict) else None
            definitive = (code in ("404", "NoSuchKey", "403", "AccessDenied")
                          or e.__class__.__name__ in ("NoSuchKey", "404"))
            if definitive:
                _DERIVED_STATUS = False
            return None
    return None


@lru_cache(maxsize=1)
def _load_indexed() -> dict:
    """Index by (indication, gene_symbol) → ranking row.
    Also builds a gene-only fallback index for cross-indication lookups.
    """
    path = _ensure_derived_cached()
    if path is None:
        return {"by_ind_gene": {}, "by_gene": {}}
    try:
        import pandas as pd
        df = pd.read_parquet(path)
    except Exception:
        return {"by_ind_gene": {}, "by_gene": {}}
    if df.empty:
        return {"by_ind_gene": {}, "by_gene": {}}
    by_ind_gene: dict[tuple, dict] = {}
    by_gene: dict[str, list[dict]] = {}
    for _, row in df.iterrows():
        rec = row.to_dict()
        ind = str(rec.get("indication", "")).strip().upper()
        sym = str(rec.get("gene_symbol", "")).strip().upper()
        if ind and sym:
            by_ind_gene[(ind, sym)] = rec
            by_gene.setdefault(sym, []).append(rec)
    return {"by_ind_gene": by_ind_gene, "by_gene": by_gene}


def read_target_summary(target: str, indication: str = None) -> dict:
    try:
        idx = _load_indexed()
    except Exception as e:
        return _empty(f"cohort_ranking_load_failed: {type(e).__name__}: {e}")
    if not idx.get("by_ind_gene"):
        return _empty("cohort_ranking_data_unavailable")

    sym = target.upper().strip()

    # Indication-specific lookup
    if indication:
        ind = indication.upper().strip()
        row = idx["by_ind_gene"].get((ind, sym))
        if row is None:
            # Try gene-only fallback (any indication)
            rows = idx["by_gene"].get(sym, [])
            if not rows:
                return _empty("target_not_in_ranking_any_indication")
            return _empty(f"target_not_in_ranking_for_{ind}")
        return _row_to_summary(row)

    # No indication → return best-percentile row across all indications
    rows = idx["by_gene"].get(sym, [])
    if not rows:
        return _empty("target_not_in_any_ranking")
    best = max(rows, key=lambda r: float(r.get("tissue_percentile_rna", 0) or 0))
    return _row_to_summary(best)


def _row_to_summary(row: dict) -> dict:
    return {
        "indication": str(row.get("indication", "")).upper(),
        "cohort_rank_class": row.get("cohort_rank_class", "below_25_percent"),
        "tissue_rank": row.get("tissue_rank"),
        "tissue_percentile_rna": row.get("tissue_percentile_rna"),
        "tissue_percentile_protein": row.get("tissue_percentile_protein"),
        "rna_protein_concordance": row.get("rna_protein_concordance", "no_protein"),
        "ranking_score": row.get("ranking_score"),
        "cells_supporting": row.get("cells_supporting"),
        "max_abs_log2fc": row.get("max_abs_log2fc"),
        "surface_protein_family": row.get("surface_protein_family"),
        "method_version": "0.1.0",
        "_data_source": DERIVED_MANIFEST_ID,
    }


def _empty(note: str) -> dict:
    return {
        "indication": None,
        "cohort_rank_class": "data_unavailable",
        "tissue_rank": None,
        "tissue_percentile_rna": None,
        "tissue_percentile_protein": None,
        "rna_protein_concordance": "no_protein",
        "ranking_score": None,
        "cells_supporting": None,
        "max_abs_log2fc": None,
        "surface_protein_family": None,
        "method_version": "0.1.0",
        "_data_note": note,
    }
