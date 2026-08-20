"""pair_selectivity_gate.bulk_read — target-centric READER for the materialized bulk pair-selectivity
product (`bispecific-bulk-pair-selectivity-per-indication-v1`).

The card's methods.entrypoint. Mirrors surfaceome_cohort_ranking.read: download the product parquet
(S3 cache), then roll up to the BEST (most selective) partner per gate for a target×indication — a
target_indication-grain summary that carries the winning target_pair inside, so it fits the single-target
verdict spine (the same pattern surface-colocalization-avidity uses). data_unavailable-safe: any load /
absence failure returns an honest empty summary, never raises.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .derive_batch import best_partner_rollup
from .gates import AVIDITY_CAVEAT

DERIVED_MANIFEST_ID = "bispecific-bulk-pair-selectivity-per-indication-v1"
S3_BUCKET = "onc-compbio"
DERIVED_S3_KEY = (
    "data-catalog/derived/bispecific-bulk-pair-selectivity-per-indication-v1/"
    "bispecific_bulk_pair_selectivity.parquet"
)
CACHE_DIR = Path.home() / ".cache" / "framework-bispecific-bulk-pair-selectivity"
CACHE_PARQUET = CACHE_DIR / "bispecific_bulk_pair_selectivity.parquet"

_DERIVED_STATUS: Optional[bool] = None


def _ensure_derived_cached() -> Optional[Path]:
    """Download the product to a local cache (once). None on definitive absence (product not published);
    re-raises transient/creds failures via the sidecar's absence discriminator (like the surfaceome reader)."""
    global _DERIVED_STATUS
    if _DERIVED_STATUS is False:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if CACHE_PARQUET.exists() and CACHE_PARQUET.stat().st_size > 0:
        _DERIVED_STATUS = True
        return CACHE_PARQUET
    try:
        from methods.target_id_sidecar import s3_client as _boto3_client, is_definitively_absent
        _boto3_client().download_file(S3_BUCKET, DERIVED_S3_KEY, str(CACHE_PARQUET))
        _DERIVED_STATUS = True
        return CACHE_PARQUET
    except Exception as e:  # noqa: BLE001
        try:
            from methods.target_id_sidecar import is_definitively_absent
            if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
                _DERIVED_STATUS = False
        except Exception:  # noqa: BLE001
            pass
        return None


def read_target_bulk_pair_selectivity(target: str, indication: str = None) -> dict:
    """Best AND/OR/NOT partner (by selectivity) for `target` in `indication`, from the materialized product.
    Returns an empty-but-shaped summary (all-None best_* + a note) when the product is unavailable or the
    target has no scored pairs — never raises. Carries the mandatory avidity caveat."""
    if not indication:
        return _empty(target, None, "indication_required (product is per-indication)")
    path = _ensure_derived_cached()
    if path is None:
        return _empty(target, indication, "bulk_pair_selectivity_data_unavailable (product not published)")
    try:
        import pandas as pd
        df = pd.read_parquet(path)
    except Exception as e:  # noqa: BLE001
        return _empty(target, indication, f"bulk_pair_selectivity_load_failed: {type(e).__name__}: {e}")
    tgt, ind = target.upper().strip(), indication.upper().strip()
    rows = df[(df["target"] == tgt) & (df["indication"] == ind)].to_dict("records")
    if not rows:
        return _empty(target, indication, "target_not_in_bulk_pair_selectivity_for_indication")
    roll = best_partner_rollup(rows, tgt, ind)
    roll["method_version"] = str(df["method_version"].iloc[0]) if "method_version" in df.columns and len(df) else None
    roll["_data_source"] = DERIVED_MANIFEST_ID
    roll["_avidity_caveat"] = AVIDITY_CAVEAT
    return roll


def _empty(target, indication, note) -> dict:
    return {
        "target": target, "indication": indication, "n_partners_scanned": 0,
        "best_and_partner": None, "best_and_selectivity": None,
        "best_not_partner": None, "best_not_selectivity": None,
        "best_or_partner": None, "best_or_selectivity": None,
        "_data_source": DERIVED_MANIFEST_ID, "_data_note": note, "_avidity_caveat": AVIDITY_CAVEAT,
    }


__all__ = ["read_target_bulk_pair_selectivity", "DERIVED_MANIFEST_ID", "DERIVED_S3_KEY"]
