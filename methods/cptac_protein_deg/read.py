"""cptac_protein_deg.read — CPTAC protein tumor-vs-normal DEG reader.

Consumer: protein-presence-cptac + surface-abundance-density evidence cards
(Phase A + F). Emits per-(target, cohort) protein-level tumor-vs-normal
differential expression stats from CPTAC-PDC mass-spec data (10 cohorts).

Cohorts: BRCA, CCRCC, COAD, GBM, HNSCC, LSCC, LUAD, OV, PDAC, UCEC.

Reviewer-driven governance discipline (2026-07-08): protein-level
tumor-vs-normal is the reviewer-flagged missing evidence layer for ADC/TCE
decisions. This method makes it available at the per-target read layer.

Iter-1 wiring approach:
  - Reads derived parquet at
    s3://onc-compbio/data-catalog/derived/cptac-protein-tumor-vs-normal-per-cohort-v1/
  - Falls back to `data_unavailable` gracefully when derived product not on S3.

Runtime discipline: @lru_cache + module-level negative cache.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional


DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"
DERIVED_MANIFEST_ID = "cptac-protein-tumor-vs-normal-per-cohort-v1"
DERIVED_S3_KEY = (
    "data-catalog/derived/cptac-protein-tumor-vs-normal-per-cohort-v1/"
    "cptac_protein_deg.parquet"
)

CACHE_DIR = Path.home() / ".cache" / "framework-cptac"
CACHE_PARQUET = CACHE_DIR / "cptac_protein_deg.parquet"

_DERIVED_STATUS: Optional[bool] = None

# Indication → CPTAC cohort code mapping (some indications share codes)
INDICATION_TO_CPTAC = {
    "BRCA": "BRCA", "CCRCC": "CCRCC", "COAD": "COAD", "COADREAD": "COAD",
    "GBM": "GBM", "HNSC": "HNSCC", "HNSCC": "HNSCC",
    "LUSC": "LSCC", "LSCC": "LSCC",  # CPTAC uses LSCC for lung squamous
    "LUAD": "LUAD", "OV": "OV", "PAAD": "PDAC", "PDAC": "PDAC",
    "UCEC": "UCEC",
}


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
        except Exception:
            _DERIVED_STATUS = False
            return None
    return None


@lru_cache(maxsize=1)
def _load_indexed() -> dict:
    """Load CPTAC DEG parquet, index by (cohort, gene_symbol) → row.
    Also builds a gene_symbol → list-of-cohorts secondary index.
    """
    path = _ensure_derived_cached()
    if path is None:
        return {"by_cohort_gene": {}, "by_gene": {}}
    try:
        import pandas as pd
        df = pd.read_parquet(path)
    except Exception:
        return {"by_cohort_gene": {}, "by_gene": {}}
    if df.empty:
        return {"by_cohort_gene": {}, "by_gene": {}}
    by_cohort_gene: dict[tuple, dict] = {}
    by_gene: dict[str, list[dict]] = {}
    for _, row in df.iterrows():
        rec = row.to_dict()
        cohort = str(rec.get("cohort", "")).strip().upper()
        sym = str(rec.get("gene_symbol", "")).strip().upper()
        if cohort and sym:
            by_cohort_gene[(cohort, sym)] = rec
            by_gene.setdefault(sym, []).append(rec)
    return {"by_cohort_gene": by_cohort_gene, "by_gene": by_gene}


def read_target_summary(target: str, indication: str = None) -> dict:
    try:
        idx = _load_indexed()
    except Exception as e:
        return _empty(f"cptac_load_failed: {type(e).__name__}: {e}")
    if not idx.get("by_cohort_gene"):
        return _empty("cptac_data_unavailable")

    sym = target.upper().strip()

    # Resolve indication → CPTAC cohort
    cohort = None
    if indication:
        cohort = INDICATION_TO_CPTAC.get(indication.upper().strip())

    # Primary path: indication-specific lookup
    if cohort:
        row = idx["by_cohort_gene"].get((cohort, sym))
        if row is None:
            # Cohort maps to CPTAC but target not in that cohort's data
            return _empty(f"target_not_in_cptac_cohort_{cohort}")
        return _row_to_summary(row, matched_cohort=cohort)

    # Fallback: no indication or non-CPTAC indication → aggregate across
    # all cohorts (returns "best-effect" row for governance context)
    rows = idx["by_gene"].get(sym, [])
    if not rows:
        return _empty("target_not_in_any_cptac_cohort")

    # Return the row with the largest absolute effect size (governance signal)
    best_row = max(rows, key=lambda r: abs(float(r.get("protein_effect_size", 0) or 0)))
    return _row_to_summary(best_row, matched_cohort=str(best_row.get("cohort", "")).upper())


def _row_to_summary(row: dict, matched_cohort: str) -> dict:
    return {
        "cohort": matched_cohort,
        "protein_expression_class": row.get("protein_expression_class", "ns"),
        "protein_effect_size": row.get("protein_effect_size"),
        "protein_bh_q_value": row.get("protein_bh_q_value"),
        "protein_p_value": row.get("protein_p_value"),
        "protein_median_log2_tumor": row.get("protein_median_log2_tumor"),
        "protein_median_log2_normal": row.get("protein_median_log2_normal"),
        "n_tumor_samples": row.get("n_tumor_samples"),
        "n_normal_samples": row.get("n_normal_samples"),
        "stat_test_used": row.get("stat_test_used", "welch_t"),
        "method_version": "0.1.0",
        "_data_source": DERIVED_MANIFEST_ID,
    }


def _empty(note: str) -> dict:
    return {
        "cohort": None,
        "protein_expression_class": "data_unavailable",
        "protein_effect_size": None,
        "protein_bh_q_value": None,
        "protein_p_value": None,
        "protein_median_log2_tumor": None,
        "protein_median_log2_normal": None,
        "n_tumor_samples": None,
        "n_normal_samples": None,
        "stat_test_used": "skipped_low_n",
        "method_version": "0.1.0",
        "_data_note": note,
    }
