"""pathway_stratified_surface.read — per-target pathway/stress-stratified surface window (E4-A3).

Sibling of mutation_stratified_surface (E4-A2). Answers: is surface antigen {target} elevated in a
tumor-STATE subset (e.g. the hypoxia-HIGH tertile) vs the pathway-LOW subset — a biologics handle on
that tumor compartment (the CA9 hypoxia-ADC archetype)? Reads pathway-stratified-surface-window-v1
(gene-symbol keyed; carries signature + indication columns).

COVERAGE (v1): the HALLMARK_HYPOXIA x NSCLC archetype only. A (target, signature, indication) outside
that slice returns not_in_product (a coverage gap — NOT not_stratified). signature/indication default
to HALLMARK_HYPOXIA/NSCLC.

pathway_stratified_surface_class (from the product):
  pathway_high_up_surface   antigen ELEVATED in the pathway-HIGH subset (q<=0.10, delta_log2>=0.5)
  pathway_high_down_surface antigen DEPLETED in the pathway-HIGH subset
  not_stratified            tested, not significant / small effect
  underpowered              tertile arm below the sample floor (inadmissible, not a negative)
  not_in_product            target/signature/indication outside the built slice (coverage gap)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

PRODUCT_MANIFEST_ID = "pathway-stratified-surface-window-v1"
METHOD_VERSION = "0.1.0"
DEFAULT_SIGNATURE = "HALLMARK_HYPOXIA"
DEFAULT_INDICATION = "NSCLC"


def _read_row(target: str, signature: str, indication: str) -> Optional[dict]:
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from methods.catalog_query.read import bucket_key_for
        import pyarrow.parquet as pq
        import pyarrow.fs as fs
        bucket, key = bucket_key_for(PRODUCT_MANIFEST_ID)
        tbl = pq.read_table(f"{bucket}/{key}", filesystem=fs.S3FileSystem(),
                            filters=[("gene_symbol", "=", (target or "").strip().upper()),
                                     ("signature", "=", signature),
                                     ("indication", "=", indication)])
    except Exception:  # noqa: BLE001
        return None
    if tbl.num_rows == 0:
        return None
    return tbl.to_pylist()[0]


def read_pathway_stratified_surface(target: str, signature: str = DEFAULT_SIGNATURE,
                                    indication: str = DEFAULT_INDICATION,
                                    row: Optional[dict] = None) -> dict:
    """Per-target pathway-stratified surface window. `row` may be injected for tests.

    Absent from the built slice -> not_in_product (coverage gap, never a negative)."""
    rec = row if row is not None else _read_row(target, signature, indication)
    if rec is None:
        return {
            "pathway_stratified_surface_class": "not_in_product",
            "signature": signature,
            "indication": indication,
            "delta_log2": None,
            "q_value": None,
            "n_high": None,
            "n_low": None,
            "pathway_stratified_context": (
                f"{target!r} not in the pathway-stratified surface product for "
                f"{signature}/{indication} (coverage gap; v1 covers HALLMARK_HYPOXIA/NSCLC only)."),
            "method_version": METHOD_VERSION,
            "_data_source": PRODUCT_MANIFEST_ID,
        }
    klass = rec.get("pathway_stratified_surface_class", "not_stratified")
    return {
        "pathway_stratified_surface_class": klass,
        "signature": rec.get("signature", signature),
        "indication": rec.get("indication", indication),
        "delta_log2": rec.get("delta_log2"),
        "q_value": rec.get("q_value"),
        "n_high": rec.get("n_high"),
        "n_low": rec.get("n_low"),
        "pathway_stratified_context": _context(target, klass, rec),
        "method_version": METHOD_VERSION,
        "_data_source": PRODUCT_MANIFEST_ID,
    }


def _context(target: str, klass: str, rec: dict) -> Optional[str]:
    d = rec.get("delta_log2"); q = rec.get("q_value")
    sig = rec.get("signature"); ind = rec.get("indication")
    if klass == "pathway_high_up_surface":
        return (f"{target}: elevated on the surface in the {sig}-HIGH subset of {ind} "
                f"(delta_log2={d:+.2f}, q={q:.1e}) — a biologics handle enriched in the "
                f"{sig}-high tumor compartment.")
    if klass == "pathway_high_down_surface":
        return (f"{target}: depleted in the {sig}-HIGH subset of {ind} (delta_log2={d:+.2f}, q={q:.1e}).")
    if klass == "underpowered":
        return f"{target}: a {sig} tertile arm below the sample floor in {ind} (inadmissible)."
    if klass == "not_stratified":
        return (f"{target}: no significant {sig}-high-vs-low surface difference in {ind} "
                f"(the gene-level window applies).")
    return None
