"""cooccurrence_fisher_pancohort.read — panel-intersect Fisher co-mutation reader.

Consumer: co-mutation-and-mutual-exclusivity evidence card (Phase E) via
differentiation-landscape skill.

Reviewer BLOCKER fix discipline (2026-07-08): pooled Q-values are emitted
ONLY for gene pairs where BOTH the target and partner are covered on ALL
GENIE panels contributing to the pooled cohort. Genes outside the panel-
intersect gene set get per-source (TCGA MC3 only) Q-values with
`pooled_eligible: False` marked per row.

Iter-1 wiring approach:
  - Reads derived parquet at
    s3://onc-compbio/data-catalog/derived/pancohort-cooccurrence-fisher-v1/
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
DERIVED_MANIFEST_ID = "pancohort-cooccurrence-fisher-v1"
DERIVED_S3_KEY = (
    "data-catalog/derived/pancohort-cooccurrence-fisher-v1/"
    "cooccurrence_fisher.parquet"
)

CACHE_DIR = Path.home() / ".cache" / "framework-cooccurrence-fisher"
CACHE_PARQUET = CACHE_DIR / "cooccurrence_fisher.parquet"

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
        except Exception:
            _DERIVED_STATUS = False
            return None
    return None


@lru_cache(maxsize=1)
def _load_indexed() -> dict:
    """Load Fisher parquet, index by target_gene_symbol → list of pair-rows."""
    path = _ensure_derived_cached()
    if path is None:
        return {}
    try:
        import pandas as pd
        df = pd.read_parquet(path)
    except Exception:
        return {}
    if df.empty:
        return {}
    idx: dict[str, list[dict]] = {}
    for _, row in df.iterrows():
        sym = str(row.get("target_gene_symbol", "")).strip().upper()
        if sym:
            idx.setdefault(sym, []).append(row.to_dict())
    return idx


def _classify_cooccurrence(rows: list[dict]) -> str:
    """Derive the primary co-occurrence class from the target's row set.

    Precedence rules (governance-tuned):
      - strong_cooccurring: q<0.001 AND log2_or > 1.0
      - modest_cooccurring: q<0.05 AND log2_or > 0.5
      - strong_mutually_exclusive: q<0.001 AND log2_or < -1.0
      - modest_mutually_exclusive: q<0.05 AND log2_or < -0.5
      - both_patterns_present: has both strong_cooccurring AND strong_mutex
      - ns: no significant signal
    """
    strong_cooc = False
    modest_cooc = False
    strong_mutex = False
    modest_mutex = False
    for r in rows:
        q = float(r.get("bh_q_value") or 1.0)
        log2_or = float(r.get("log2_odds_ratio") or 0.0)
        if q < 0.001:
            if log2_or > 1.0:
                strong_cooc = True
            elif log2_or < -1.0:
                strong_mutex = True
        if q < 0.05:
            if log2_or > 0.5:
                modest_cooc = True
            elif log2_or < -0.5:
                modest_mutex = True
    if strong_cooc and strong_mutex:
        return "both_patterns_present"
    if strong_cooc:
        return "strong_cooccurring"
    if strong_mutex:
        return "strong_mutually_exclusive"
    if modest_cooc:
        return "modest_cooccurring"
    if modest_mutex:
        return "modest_mutually_exclusive"
    return "ns"


def read_target_summary(target: str, indication: str = None) -> dict:
    try:
        idx = _load_indexed()
    except Exception as e:
        return _empty(f"cooccurrence_load_failed: {type(e).__name__}: {e}")
    if not idx:
        return _empty("cooccurrence_data_unavailable")

    sym = target.upper().strip()
    rows = idx.get(sym, [])
    if not rows:
        return _empty("target_not_in_cooccurrence_scan")

    # Partition rows into per-source vs pooled
    per_source = [r for r in rows if str(r.get("source", "")).lower() != "pooled"]
    pooled = [r for r in rows if str(r.get("source", "")).lower() == "pooled"]

    # Top-cooccurring + top-mutually-exclusive lists (ranked by ranking_score
    # if available, else by -log10(q) * sign(log2_or))
    def _rank(r):
        rs = r.get("ranking_score")
        if rs is not None:
            try:
                return float(rs)
            except (ValueError, TypeError):
                pass
        q = float(r.get("bh_q_value") or 1.0)
        log2_or = float(r.get("log2_odds_ratio") or 0.0)
        import math
        return -math.log10(max(q, 1e-300)) * (1 if log2_or > 0 else -1 if log2_or < 0 else 0)

    def _stripped(r: dict) -> dict:
        return {
            "partner_gene_symbol": r.get("partner_gene_symbol"),
            "log2_odds_ratio": r.get("log2_odds_ratio"),
            "bh_q_value": r.get("bh_q_value"),
            "source": r.get("source"),
            "pooled_eligible": bool(r.get("pooled_eligible", False)),
        }

    # Use the higher-quality source per pair: prefer pooled when available,
    # fall back to TCGA MC3 for panel-ineligible pairs.
    seen: dict[str, dict] = {}
    for r in pooled + per_source:
        partner = str(r.get("partner_gene_symbol", "")).strip().upper()
        if partner and partner not in seen:
            seen[partner] = r

    top_cooc = sorted(
        (v for v in seen.values() if float(v.get("log2_odds_ratio") or 0) > 0),
        key=lambda r: -_rank(r)
    )
    top_mutex = sorted(
        (v for v in seen.values() if float(v.get("log2_odds_ratio") or 0) < 0),
        key=lambda r: _rank(r)
    )

    n_sig_cooc = sum(1 for r in top_cooc
                      if float(r.get("bh_q_value") or 1) < 0.05
                      and float(r.get("log2_odds_ratio") or 0) > 0.5)
    n_sig_mutex = sum(1 for r in top_mutex
                       if float(r.get("bh_q_value") or 1) < 0.05
                       and float(r.get("log2_odds_ratio") or 0) < -0.5)

    return {
        "cooccurrence_class": _classify_cooccurrence(rows),
        "n_significant_cooccurring": n_sig_cooc,
        "n_significant_mutually_exclusive": n_sig_mutex,
        "n_pairs_panel_intersect_eligible": sum(1 for r in rows
                                                  if bool(r.get("pooled_eligible", False))),
        "n_pairs_per_source_only": sum(1 for r in rows
                                         if not bool(r.get("pooled_eligible", False))),
        "top_cooccurring": [_stripped(r) for r in top_cooc[:10]],
        "top_mutually_exclusive": [_stripped(r) for r in top_mutex[:10]],
        "has_cooccurring_driver": any(float(r.get("bh_q_value") or 1) < 0.001
                                        and float(r.get("log2_odds_ratio") or 0) > 1.0
                                        for r in rows),
        "has_mutually_exclusive_driver": any(float(r.get("bh_q_value") or 1) < 0.001
                                               and float(r.get("log2_odds_ratio") or 0) < -1.0
                                               for r in rows),
        "method_version": "0.1.0",
        "_data_source": DERIVED_MANIFEST_ID,
    }


def _empty(note: str) -> dict:
    return {
        "cooccurrence_class": "data_unavailable",
        "n_significant_cooccurring": 0,
        "n_significant_mutually_exclusive": 0,
        "n_pairs_panel_intersect_eligible": 0,
        "n_pairs_per_source_only": 0,
        "top_cooccurring": [],
        "top_mutually_exclusive": [],
        "has_cooccurring_driver": False,
        "has_mutually_exclusive_driver": False,
        "method_version": "0.1.0",
        "_data_note": note,
    }
