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

# indication -> landed spatial region-protein product (GeoMx DSP). HNSC = GSE288406 (580-plex, Phase 3
# pilot); NSCLC = GSE221322 (68-plex IO panel) covering all three lung histologies. Adding an indication
# = emit its spatial-surface-protein product (data-catalog) + one line here.
INDICATION_TO_SURFACE_PROTEIN = {
    "HNSC": "spatial-surface-protein-hnsc-v1",
    "NSCLC": "spatial-surface-protein-nsclc-v1",   # lung — GeoMx IO panel (GSE221322)
    "LUAD": "spatial-surface-protein-nsclc-v1",     # covered by the NSCLC product (both histologies)
    "LUSC": "spatial-surface-protein-nsclc-v1",
}

_PARQUET_COLS = ["gene_symbol", "donor_id", "compartment", "abundance_lcpm", "detected"]


def _product_key(indication: str) -> Optional[str]:
    prod = INDICATION_TO_SURFACE_PROTEIN.get(str(indication).upper().strip())
    if not prod:
        return None
    return bucket_key_for(prod)[1]


def read_target_protein_rows(target: str, indication: str):
    """Per-(donor, compartment) region-protein rows for one target in one indication's product.

    DataFrame (possibly empty) with _PARQUET_COLS; None when the indication has no landed product,
    empty when the target is not a resolved protein on the panel."""
    key = _product_key(indication)
    if key is None:
        return None
    import pyarrow.fs as fs
    import pyarrow.parquet as pq
    s3fs = fs.S3FileSystem(region="us-east-1")
    filters = [("gene_symbol", "==", str(target).upper().strip())]
    try:
        tbl = pq.read_table(f"{S3_BUCKET}/{key}", filesystem=s3fs, filters=filters, columns=_PARQUET_COLS)
    except FileNotFoundError:
        return None
    return tbl.to_pandas()


def read_spatial_surface_protein(target: str, indication: str) -> dict:
    """Assemble the spatial region-protein tumour-compartment summary for a (target, indication).

    Cross-donor median TUMOUR vs TME abundance + spatial_protein_class. data_unavailable-safe on
    'no product for indication' and 'target not a resolved protein on the GeoMx panel'."""
    rows = read_target_protein_rows(target, indication)
    if rows is None:
        return _data_unavailable(target, indication,
                                 note=f"No spatial region-protein product landed for indication "
                                      f"{indication}; spatial_protein is a named capability gap here.")
    if rows.empty:
        return _data_unavailable(target, indication,
                                 note=f"{target} not a resolved protein on the GeoMx panel for "
                                      f"{indication} (antibody-named panel; not all targets map).")
    recs = rows.to_dict("records")
    summ = _stats.summarize_protein(recs)
    classed = _stats.classify_surface_protein(summ, recs)
    out = dict(classed)
    out["target"] = str(target).upper().strip()
    out["indication"] = str(indication).upper().strip()
    out["product_id"] = INDICATION_TO_SURFACE_PROTEIN.get(str(indication).upper().strip())
    out["_evidence_tier"] = "spatial_protein_measured"
    return out


def _data_unavailable(target: str, indication: str, note: str) -> dict:
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
        "product_id": INDICATION_TO_SURFACE_PROTEIN.get(str(indication).upper().strip()),
        "_data_note": note,
    }
