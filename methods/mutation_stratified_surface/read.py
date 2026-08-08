"""mutation_stratified_surface.read — per-target mutation-stratified surface-antigen window (E4-A2).

Answers: is surface antigen {target} elevated in a DRIVER's MUTANT tumor subset (vs WT) — a
biologics handle on the driver-mutant patient subset that the gene-level-averaged tumor-vs-normal
window dilutes away? Reads mutation-stratified-surface-window-v1 (gene-symbol keyed; carries
driver_gene + indication columns).

COVERAGE (v1): the product is the KRAS x NSCLC archetype only. A (target, driver, indication) outside
that slice returns not_in_product (an honest coverage gap — NOT not_stratified). driver/indication
default to KRAS/NSCLC; a caller may pass others once the product covers them.

mutant_stratified_surface_class (from the product):
  mutant_up_surface     antigen ELEVATED in the driver-mutant subset (q<=0.10, delta_log2>=0.5)
  mutant_down_surface   antigen DEPLETED in the mutant subset
  not_stratified        tested, not significant / small effect
  underpowered          arm below the sample floor (inadmissible, not a negative)
  not_in_product        target/driver/indication outside the built slice (coverage gap)
  data_unavailable      the product read RAISED (S3 outage / expired creds / renamed key) —
                        an infra failure, NOT a coverage gap. Carries a `_live_read_error`
                        breadcrumb. Distinct from not_in_product so a broken environment is
                        never silently reported as a benign absence.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

PRODUCT_MANIFEST_ID = "mutation-stratified-surface-window-v1"
METHOD_VERSION = "0.1.0"
DEFAULT_DRIVER = "KRAS"
DEFAULT_INDICATION = "NSCLC"


class _ReadError:
    """Sentinel returned by _read_row when the S3 read RAISED — distinct from a genuine
    0-row absence (None). Carries the exception message for the `_live_read_error` breadcrumb.
    Mirrors combo_drug_anchor's None-on-exception-vs-tuple()-on-empty discipline: a read
    failure must NEVER masquerade as a benign coverage gap (the "bare-except masks broken
    env" failure class)."""
    __slots__ = ("msg",)

    def __init__(self, msg: str):
        self.msg = msg


def _read_row(target: str, driver: str, indication: str):
    """Pushdown-read the product for (gene_symbol, driver_gene, indication).

    Returns the row dict on a hit, None when the row is GENUINELY ABSENT from the built
    slice (0 rows), or a `_ReadError` sentinel (carrying the exception message) when the
    read RAISED (infra failure — never a coverage gap)."""
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from methods.catalog_query.read import bucket_key_for
        import pyarrow.parquet as pq
        import pyarrow.fs as fs
        bucket, key = bucket_key_for(PRODUCT_MANIFEST_ID)
        tbl = pq.read_table(f"{bucket}/{key}", filesystem=fs.S3FileSystem(),
                            filters=[("gene_symbol", "=", (target or "").strip().upper()),
                                     ("driver_gene", "=", driver),
                                     ("indication", "=", indication)])
    except Exception as e:  # noqa: BLE001
        return _ReadError(f"{type(e).__name__}: {e}")
    if tbl.num_rows == 0:
        return None
    return tbl.to_pylist()[0]


def read_mutation_stratified_surface(target: str, driver: str = DEFAULT_DRIVER,
                                     indication: str = DEFAULT_INDICATION,
                                     row: Optional[dict] = None) -> dict:
    """Per-target mutation-stratified surface window. `row` may be injected for tests.

    Absent from the built slice -> not_in_product (coverage gap, never a negative).
    Read RAISED -> data_unavailable + a `_live_read_error` breadcrumb (infra failure,
    never a coverage gap)."""
    rec = row if row is not None else _read_row(target, driver, indication)
    if isinstance(rec, _ReadError):
        return {
            "mutant_stratified_surface_class": "data_unavailable",
            "driver_gene": driver,
            "indication": indication,
            "delta_log2": None,
            "q_value": None,
            "n_mutant": None,
            "n_wt": None,
            "mutation_stratified_context": (
                f"{target!r}: mutation-stratified surface product unavailable for "
                f"{driver}/{indication} (read error — infra failure, NOT a coverage gap)."),
            "method_version": METHOD_VERSION,
            "_data_source": PRODUCT_MANIFEST_ID,
            "_live_read_error": rec.msg or "mutation_stratified_surface_read_failed",
        }
    if rec is None:
        return {
            "mutant_stratified_surface_class": "not_in_product",
            "driver_gene": driver,
            "indication": indication,
            "delta_log2": None,
            "q_value": None,
            "n_mutant": None,
            "n_wt": None,
            "mutation_stratified_context": (
                f"{target!r} not in the mutation-stratified surface product for "
                f"{driver}/{indication} (coverage gap; v1 covers KRAS/NSCLC only)."),
            "method_version": METHOD_VERSION,
            "_data_source": PRODUCT_MANIFEST_ID,
        }
    klass = rec.get("mutant_stratified_surface_class", "not_stratified")
    return {
        "mutant_stratified_surface_class": klass,
        "driver_gene": rec.get("driver_gene", driver),
        "indication": rec.get("indication", indication),
        "delta_log2": rec.get("delta_log2"),
        "q_value": rec.get("q_value"),
        "n_mutant": rec.get("n_mutant"),
        "n_wt": rec.get("n_wt"),
        "mutation_stratified_context": _context(target, klass, rec),
        "method_version": METHOD_VERSION,
        "_data_source": PRODUCT_MANIFEST_ID,
    }


def _context(target: str, klass: str, rec: dict) -> Optional[str]:
    d = rec.get("delta_log2"); q = rec.get("q_value")
    drv = rec.get("driver_gene"); ind = rec.get("indication")
    if klass == "mutant_up_surface":
        return (f"{target}: elevated on the surface in {drv}-mutant {ind} "
                f"(delta_log2={d:+.2f}, q={q:.1e}) — a biologics handle enriched in the "
                f"{drv}-mutant patient subset.")
    if klass == "mutant_down_surface":
        return (f"{target}: depleted in {drv}-mutant {ind} (delta_log2={d:+.2f}, q={q:.1e}).")
    if klass == "underpowered":
        return f"{target}: {drv}-mutant or WT arm below the sample floor in {ind} (inadmissible)."
    if klass == "not_stratified":
        return (f"{target}: no significant {drv}-mutant-vs-WT surface difference in {ind} "
                f"(the gene-level window applies).")
    return None
