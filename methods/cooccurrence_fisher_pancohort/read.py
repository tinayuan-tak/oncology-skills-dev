"""cooccurrence_fisher_pancohort.read — panel-intersect Fisher co-mutation reader.

Consumer: co-mutation-and-mutual-exclusivity evidence card (Phase E) via
differentiation-landscape skill.

Reviewer BLOCKER fix discipline (2026-07-08): pooled Q-values are emitted
ONLY for gene pairs where BOTH the target and partner are covered on ALL
GENIE panels contributing to the pooled cohort. Genes outside the panel-
intersect gene set get per-source (TCGA MC3 only) Q-values with
`pooled_eligible: False` marked per row.

Wiring approach (data-layer hardening 2026-08-22 — streamed pushdown):
  - STREAMS the target's rows out of the derived parquet at
    s3://onc-compbio/data-catalog/derived/pancohort-cooccurrence-fisher-v1/
    via a pyarrow S3FileSystem with predicate pushdown on the manifest
    primary_filter_column (`target_gene_symbol`, the product's sort key) — only
    the target's row-groups transit the wire; NO whole-file download.
  - Emits `data_unavailable` gracefully only when the product object is
    DEFINITIVELY absent (NoSuchKey/404); transient/creds/broken-env failures
    surface a cause-accurate breadcrumb (absence discipline).

Runtime discipline: process-wide S3FileSystem singleton + per-target read cache
(+ a definitive-absence latch), so repeated targets don't re-hit S3.
"""
from __future__ import annotations

import threading
from typing import Optional


DERIVED_MANIFEST_ID = "pancohort-cooccurrence-fisher-v1"

# Pushdown key: the derived manifest's query_optimization.primary_filter_column, which is also its
# sort column. The product is SORTED by target_gene_symbol, so a per-target equality filter lets
# pyarrow skip non-matching row-groups — only the target's row-groups stream over the wire.
_PRIMARY_FILTER_COLUMN = "target_gene_symbol"

# Process-wide latch: True = product present, False = product DEFINITIVELY absent (NoSuchKey/404 —
# short-circuits every later target in the process), None = undetermined / transient failure (retry).
_DERIVED_STATUS: Optional[bool] = None

# Per-target streamed-read cache, keyed UPPER(target). Only SUCCESSFUL reads (incl. an empty list)
# are cached; a transient/creds/broken-env failure RAISES without caching so a later call retries —
# an @lru_cache over the raw read would memoize that failure into a permanent data_unavailable
# (mirrors methods/combo_drug_anchor).
_ROWS_CACHE: dict = {}

_S3FS = None
_S3FS_LOCK = threading.Lock()


def _get_s3fs():
    """Process-wide pyarrow S3FileSystem singleton (region pinned to us-east-1, the onc-compbio
    bucket, to skip the region-probe round-trip). Constructing one costs ~0.4s and this reader can
    fire for several targets per run (differentiation-landscape / target-profile fan-out), so build
    it ONCE. Double-checked locking so concurrent first-callers build a single instance. Mirrors
    the sibling dge_deseq2._get_s3fs / depmap_common.parquet._get_s3fs."""
    global _S3FS
    if _S3FS is None:
        with _S3FS_LOCK:
            if _S3FS is None:
                import pyarrow.fs as fs
                _S3FS = fs.S3FileSystem(region="us-east-1")
    return _S3FS


def _read_target_rows(sym: str) -> Optional[list]:
    """STREAMED pyarrow pushdown of ONE target's co-occurrence rows — replaces the former whole-file
    `download_file` + local `pd.read_parquet`. Pushes the manifest primary_filter_column
    (target_gene_symbol == sym) AND the original bh_q_value <= 0.5 predicate, so only the target's
    row-groups stream over the wire (no download). Returns a list-of-dict records — identical
    shape/dtypes to the former `df.iloc[...].to_dict(orient="records")` (same pyarrow->pandas path) —
    or None when the product object is DEFINITIVELY absent (NoSuchKey/404). RAISES on transient /
    creds / broken-env so the public boundary surfaces the real cause instead of a silent dead axis
    (absence discipline; mirrors methods/combo_drug_anchor + target_id_sidecar.is_definitively_absent).
    Successful reads (incl. an empty list) are cached per target."""
    global _DERIVED_STATUS
    if _DERIVED_STATUS is False:
        return None
    if sym in _ROWS_CACHE:
        return _ROWS_CACHE[sym]
    try:
        from methods.catalog_query.read import bucket_key_for
        import pyarrow.parquet as pq
        bucket, key = bucket_key_for(DERIVED_MANIFEST_ID)
        tbl = pq.read_table(
            f"{bucket}/{key}",
            filesystem=_get_s3fs(),
            filters=[(_PRIMARY_FILTER_COLUMN, "=", sym), ("bh_q_value", "<=", 0.5)],
        )
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent
        # Only a GENUINE no-object (NoSuchKey/404 or pyarrow FileNotFoundError) is absence -> latch
        # _DERIVED_STATUS False (short-circuits later targets) and return None. A transient/creds/
        # broken-env failure is NOT absence -> re-raise (neither cached nor latched, so a later call
        # retries) and let the public boundary record the real cause.
        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            _DERIVED_STATUS = False
            return None
        raise
    _DERIVED_STATUS = True
    # to_pandas().to_dict(orient="records") reproduces the exact records the former
    # pd.read_parquet(...).iloc[...].to_dict(orient="records") emitted (same dtypes).
    rows = tbl.to_pandas().to_dict(orient="records")
    _ROWS_CACHE[sym] = rows
    return rows


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
    sym = target.upper().strip()
    try:
        # Streamed per-target pushdown. None = product definitively absent (NoSuchKey/404);
        # RAISES on transient/creds/broken-env, caught below with a cause-accurate breadcrumb.
        rows = _read_target_rows(sym)
    except Exception as e:
        return _empty(f"cooccurrence_load_failed: {type(e).__name__}: {e}")
    if rows is None:
        return _empty("cooccurrence_data_unavailable")
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
