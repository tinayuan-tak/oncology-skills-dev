"""pair_selectivity_gate.bulk_read — target-centric READER for the materialized bulk pair-selectivity
product (`bispecific-bulk-pair-selectivity-per-indication-v1`).

The card's methods.entrypoint. STREAMS the product parquet from S3 via a pyarrow S3FileSystem with a
target pushdown (the manifest's query_optimization.primary_filter_column = `target`) — no whole-file
download — then rolls up to the BEST (most selective) partner per gate for a target×indication: a
target_indication-grain summary that carries the winning target_pair inside, so it fits the single-target
verdict spine (the same pattern surface-colocalization-avidity uses). data_unavailable-safe: any load /
absence failure returns an honest empty summary, never raises.
"""

from __future__ import annotations

from typing import Optional

from .derive_batch import best_partner_rollup
from .gates import AVIDITY_CAVEAT

DERIVED_MANIFEST_ID = "bispecific-bulk-pair-selectivity-per-indication-v1"
# Pushdown key = derived manifest's query_optimization.primary_filter_column.
PUSHDOWN_KEY = "target"
DERIVED_S3_KEY = (
    "data-catalog/derived/bispecific-bulk-pair-selectivity-per-indication-v1/bispecific_bulk_pair_selectivity.parquet"
)

# False = the product object is DEFINITIVELY absent (NoSuchKey/404) — latched so we don't re-probe S3
# every call. None = not yet determined; True = a successful stream has been served. (Offline test seam:
# set _DERIVED_STATUS = False to force the data_unavailable path without touching S3.)
_DERIVED_STATUS: Optional[bool] = None


def _read_target_rows(target: str) -> Optional[list]:
    """STREAMED pyarrow S3 pushdown read of the product for one `target` (primary_filter_column).
    Returns a list of row dicts (possibly empty if the target has no scored pairs), or None on a
    DEFINITIVE product absence (NoSuchKey/404 / pyarrow FileNotFoundError) — which latches
    _DERIVED_STATUS=False. RE-RAISES transient/creds/broken-env failures (NOT latched) so the caller's
    boundary records the true cause instead of a silent dead axis. No whole-file download."""
    global _DERIVED_STATUS
    if _DERIVED_STATUS is False:
        return None
    tgt = (target or "").upper().strip()
    try:
        import pyarrow.fs as fs
        import pyarrow.parquet as pq

        from methods.catalog_query.read import bucket_key_for

        bucket, key = bucket_key_for(DERIVED_MANIFEST_ID)
        tbl = pq.read_table(
            f"{bucket}/{key}", filesystem=fs.S3FileSystem(region="us-east-1"), filters=[(PUSHDOWN_KEY, "=", tgt)]
        )
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent

        # Genuine no-object (NoSuchKey/404 or pyarrow FileNotFoundError) -> definitive absence: latch
        # and return None. A transient/creds/broken-env failure is NOT absence -> re-raise so the
        # caller's boundary surfaces the REAL cause; NOT latched, so a later call still retries.
        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            _DERIVED_STATUS = False
            return None
        raise
    _DERIVED_STATUS = True
    return tbl.to_pylist()


def read_target_bulk_pair_selectivity(target: str, indication: str = None) -> dict:
    """Best AND/OR/NOT partner (by selectivity) for `target` in `indication`, from the materialized product.
    Returns an empty-but-shaped summary (all-None best_* + a note) when the product is unavailable or the
    target has no scored pairs — never raises. Carries the mandatory avidity caveat."""
    if not indication:
        return _empty(target, None, "indication_required (product is per-indication)")
    try:
        target_rows = _read_target_rows(target)  # None = definitive absence; raises on transient
    except Exception as e:  # noqa: BLE001 — graceful boundary: never propagate a read blip past the
        # public entrypoint (the card contract is "never raises"; degrade to data_unavailable + a
        # cause-accurate breadcrumb). The S3 read in _read_target_rows already discriminates definitive
        # absence from transient and re-raises the latter; this boundary catch is that re-raise's sink.
        return _empty(target, indication, f"bulk_pair_selectivity_load_failed: {type(e).__name__}: {e}")
    if target_rows is None:
        return _empty(target, indication, "bulk_pair_selectivity_data_unavailable (product not published)")
    tgt, ind = target.upper().strip(), indication.upper().strip()
    rows = [r for r in target_rows if r.get("indication") == ind]
    if not rows:
        return _empty(target, indication, "target_not_in_bulk_pair_selectivity_for_indication")
    roll = best_partner_rollup(rows, tgt, ind)
    roll["method_version"] = str(rows[0]["method_version"]) if "method_version" in rows[0] else None
    roll["_data_source"] = DERIVED_MANIFEST_ID
    roll["_avidity_caveat"] = AVIDITY_CAVEAT
    return roll


def _empty(target, indication, note) -> dict:
    return {
        "target": target,
        "indication": indication,
        "n_partners_scanned": 0,
        "best_and_partner": None,
        "best_and_selectivity": None,
        "best_and_call_class": "data_unavailable",
        "best_not_partner": None,
        "best_not_selectivity": None,
        "best_or_partner": None,
        "best_or_selectivity": None,
        "_data_source": DERIVED_MANIFEST_ID,
        "_data_note": note,
        "_avidity_caveat": AVIDITY_CAVEAT,
    }


__all__ = ["read_target_bulk_pair_selectivity", "DERIVED_MANIFEST_ID", "DERIVED_S3_KEY"]
