"""cptac_protein_deg.read — CPTAC protein tumor-vs-normal DEG reader.

Consumer: protein-presence-cptac + surface-abundance-density evidence cards
(Phase A + F). Emits per-(target, cohort) protein-level tumor-vs-normal
differential expression stats from CPTAC-PDC mass-spec data (10 cohorts).

Cohorts: BRCA, CCRCC, COAD, GBM, HNSCC, LSCC, LUAD, OV, PDAC, UCEC.

Runtime discipline (v2, 2026-07-10):
  - Column-array iteration to build (cohort, gene) index (NOT df.iterrows —
    the pattern the kinome-atlas PR #7 refactored away from).
  - Lazy per-target row materialization: keep DataFrame in memory,
    materialize only the row(s) for a specific target at query time.
  - @lru_cache(maxsize=1) on load+index — cold path runs ONCE per process.
  - Module-level negative cache when derived not on S3.

Reads: derived parquet at
    s3://onc-compbio/data-catalog/derived/cptac-protein-tumor-vs-normal-per-cohort-v1/
Falls back to `data_unavailable` gracefully when derived product not on S3.
"""
from __future__ import annotations

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
def _load_indexed():
    """Load derived parquet + build (cohort, gene) index + gene-only index.

    Returns (df, cohort_gene_idx, gene_idx):
        - df: pandas.DataFrame with all rows (~180K rows across 10 cohorts,
          fits trivially in memory).
        - cohort_gene_idx: dict[(cohort, gene_upper) -> row_index_in_df]
        - gene_idx: dict[gene_upper -> list[row_index_in_df]] (across cohorts)
        Empty structures if load failed.
    """
    path = _ensure_derived_cached()
    if path is None:
        import pandas as pd
        return pd.DataFrame(), {}, {}

    try:
        import pandas as pd
        df = pd.read_parquet(path)
    except Exception:
        import pandas as pd
        return pd.DataFrame(), {}, {}

    if df.empty:
        return df, {}, {}

    # Column-array iteration (NOT iterrows). Direct numpy access.
    cohort_gene_idx: dict[tuple, int] = {}
    gene_idx: dict[str, list[int]] = {}

    cohort_col = df["cohort"].values
    gene_col = df["gene_symbol"].values
    for idx in range(len(df)):
        cohort = str(cohort_col[idx]).strip().upper()
        gene = str(gene_col[idx]).strip().upper()
        if not cohort or not gene:
            continue
        cohort_gene_idx[(cohort, gene)] = idx
        gene_idx.setdefault(gene, []).append(idx)

    return df, cohort_gene_idx, gene_idx


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
        "stat_test_used": row.get("stat_test_used", "msstatstmt_limma_ebayes_moderated"),
        "method_version": row.get("method_version", "1.0.0"),
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
        "method_version": "1.0.0",
        "_data_note": note,
    }


def read_target_summary(target: str, indication: str = None) -> dict:
    """Per-target CPTAC protein tumor-vs-normal DEG summary.

    Args:
        target: HGNC gene symbol.
        indication: If given, restrict to the CPTAC cohort mapped from this
            indication. Otherwise return the largest-|effect_size| row
            across cohorts.
    """
    try:
        df, cohort_gene_idx, gene_idx = _load_indexed()
    except Exception as e:
        return _empty(f"cptac_load_failed: {type(e).__name__}: {e}")
    if df is None or df.empty:
        return _empty("cptac_data_unavailable")

    sym = target.upper().strip()

    # Resolve indication → CPTAC cohort
    cohort = None
    if indication:
        cohort = INDICATION_TO_CPTAC.get(indication.upper().strip())

    # Primary path: indication-specific lookup
    if cohort:
        idx = cohort_gene_idx.get((cohort, sym))
        if idx is None:
            return _empty(f"target_not_in_cptac_cohort_{cohort}")
        row = df.iloc[idx].to_dict()
        return _row_to_summary(row, matched_cohort=cohort)

    # Fallback: no indication or non-CPTAC indication → aggregate across
    # all cohorts, return "best-effect" row (largest |effect_size|)
    indices = gene_idx.get(sym, [])
    if not indices:
        return _empty("target_not_in_any_cptac_cohort")

    rows = df.iloc[indices].to_dict(orient="records")
    best_row = max(rows, key=lambda r: abs(float(r.get("protein_effect_size", 0) or 0)))
    return _row_to_summary(best_row, matched_cohort=str(best_row.get("cohort", "")).upper())
