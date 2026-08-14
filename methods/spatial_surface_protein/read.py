"""Per-target reader over the spatial region-PROTEIN product + the compartment assembler.

Reads spatial-surface-protein-{indication}-v1 (one row per gene_symbol × donor × compartment, from
data-catalog scripts/aggregate_spatial_region_protein.py; NanoString GeoMx DSP protein). Gene-SORTED →
predicate-pushdown per target. pyarrow/pandas/boto3 ONLY — no GeoMx tooling at read time (that lives in
the emit step).

Reports the MEASURED in-situ protein abundance of a target in the TUMOUR compartment vs the TME — a
distinct claim from the bulk-CPTAC×HPA copies/cell estimate (Axis-3). Region-level, NOT copies/cell.
"""
from __future__ import annotations

from typing import Optional

from . import stats as _stats
from methods.catalog_query.read import bucket_key_for

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"

# indication -> ORDERED list of landed spatial region-protein products (GeoMx DSP), consumed as a
# within-indication FALLBACK CHAIN: the reader returns the FIRST product that resolves the target, so the
# primary panel wins and later panels only RESCUE targets it cannot resolve. The panels have DIFFERENT
# normalizations, so they are NOT pooled (cross-panel abundance is not on a common scale).
#   HNSC = [GSE288406 580-plex (primary), GSE200601 68-plex IO panel (rescues the IO/surface targets the
#           un-crosswalked 580-plex drops: PD-L1/Her2/EpCAM/B7-H3/Tim-3)]
#   NSCLC/LUAD/LUSC = [GSE221322 68-plex IO panel] (both lung histologies).
# Adding a panel = emit its spatial-surface-protein product (data-catalog) + one list entry here.
INDICATION_TO_SURFACE_PROTEIN = {
    "HNSC": ["spatial-surface-protein-hnsc-v1", "spatial-surface-protein-hnsc-gse200601-v1"],
    "NSCLC": ["spatial-surface-protein-nsclc-v1"],   # lung — GeoMx IO panel (GSE221322)
    "LUAD": ["spatial-surface-protein-nsclc-v1"],     # covered by the NSCLC product (both histologies)
    "LUSC": ["spatial-surface-protein-nsclc-v1"],
}

_PARQUET_COLS = ["gene_symbol", "donor_id", "compartment", "abundance_lcpm", "detected"]


def _products(indication: str):
    """Ordered product list for an indication (primary first). [] when none landed."""
    return list(INDICATION_TO_SURFACE_PROTEIN.get(str(indication).upper().strip(), []))


def _read_one(product_id: str, target: str):
    """Rows for one target in ONE product; empty DataFrame if off that panel, None if the object is absent."""
    import pyarrow.fs as fs
    import pyarrow.parquet as pq
    key = bucket_key_for(product_id)[1]
    s3fs = fs.S3FileSystem(region="us-east-1")
    filters = [("gene_symbol", "==", str(target).upper().strip())]
    try:
        tbl = pq.read_table(f"{S3_BUCKET}/{key}", filesystem=s3fs, filters=filters, columns=_PARQUET_COLS)
    except FileNotFoundError:
        return None
    return tbl.to_pandas()


def read_target_protein_rows(target: str, indication: str):
    """FALLBACK-CHAIN read: the first product (in priority order) that resolves the target.

    Returns (rows_df, product_id): (None, None) when the indication has NO landed product; (empty_df, None)
    when products exist but the target is on NONE of their panels; (rows, product_id) for the first hit."""
    products = _products(indication)
    if not products:
        return None, None
    empty = None
    for pid in products:
        rows = _read_one(pid, target)
        if rows is None:
            continue                                 # object missing — try the next panel
        if not rows.empty:
            return rows, pid                          # first panel that resolves the target wins
        empty = rows                                  # remember a shape for the "on no panel" branch
    return (empty if empty is not None else None), None


def read_spatial_surface_protein(target: str, indication: str) -> dict:
    """Assemble the spatial region-protein tumour-compartment summary for a (target, indication).

    Cross-donor median TUMOUR vs TME abundance + spatial_protein_class, from the first GeoMx panel (in the
    indication's fallback chain) that resolves the target. data_unavailable-safe on 'no product for
    indication' and 'target not a resolved protein on any of the indication's GeoMx panels'."""
    rows, product_id = read_target_protein_rows(target, indication)
    if rows is None and product_id is None:
        return _data_unavailable(target, indication, product_id=None,
                                 note=f"No spatial region-protein product landed for indication "
                                      f"{indication}; spatial_protein is a named capability gap here.")
    if rows is None or rows.empty:
        panels = ", ".join(_products(indication))
        return _data_unavailable(target, indication, product_id=None,
                                 note=f"{target} not a resolved protein on any GeoMx panel for "
                                      f"{indication} ({panels}; antibody-named panels — not all targets map).")
    recs = rows.to_dict("records")
    summ = _stats.summarize_protein(recs)
    classed = _stats.classify_surface_protein(summ, recs)
    out = dict(classed)
    out["target"] = str(target).upper().strip()
    out["indication"] = str(indication).upper().strip()
    out["product_id"] = product_id                    # the panel that actually supplied the data
    out["_evidence_tier"] = "spatial_protein_measured"
    return out


def _data_unavailable(target: str, indication: str, note: str, product_id: Optional[str] = None) -> dict:
    return {
        "spatial_protein_class": "data_unavailable",
        "tumour_abundance_lcpm": None,
        "tme_abundance_lcpm": None,
        "tumour_vs_tme_delta": None,
        "detected_tumour": None,
        "n_donors": 0,
        "n_datasets": 0,
        "target": str(target).upper().strip(),
        "indication": str(indication).upper().strip(),
        "product_id": product_id,
        "_data_note": note,
    }
