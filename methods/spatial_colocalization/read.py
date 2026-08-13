"""Per-target reader over the spatial co-localization product + the neighbourhood assembler.

Reads spatial-coloc-tumor-{indication}-v1 (one row per gene_symbol × donor × neighbor_cell_type, from
data-catalog scripts/aggregate_spatial_neighborhood.py). The product is gene-SORTED (sort key + read
filter key == gene_symbol), so a per-target read uses pyarrow S3FileSystem + predicate-pushdown to touch
a few row-groups — the same gene-keyed-product invariant the sc / bulk readers rely on.

Dependencies are pyarrow/pandas/numpy/boto3 ONLY — NO squidpy/anndata/scanpy at read time. All spatial
machinery (per-FOV RDS, squidpy graph) lives in the data-catalog emit step; this method reads the
already-reduced parquet.

Credential discipline: pyarrow S3FileSystem honours AWS_PROFILE=cbg (the default SSO role lacks GetObject
on onc-compbio).
"""
from __future__ import annotations

from typing import Optional

from . import stats as _stats
from methods.catalog_query.read import bucket_key_for

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"

# indication code → landed spatial co-localization product. Kept in step with the imaging single-cell
# spatial ingests. COADREAD = CosMx CRC atlas (GSE303070, data-catalog #382), the pilot. Adding an
# indication = emit its spatial-coloc product (data-catalog) + one line here.
INDICATION_TO_SPATIAL_COLOC = {
    "COADREAD": "spatial-coloc-tumor-crc-coadread-v1",
    "COAD": "spatial-coloc-tumor-crc-coadread-v1",
    "READ": "spatial-coloc-tumor-crc-coadread-v1",
}

_PARQUET_COLS = ["gene_symbol", "dataset_id", "donor_id", "neighbor_cell_type",
                 "n_malignant_cells", "target_pos_fraction", "adjacency_fraction", "enrichment_vs_random"]


def _product_key(indication: str) -> Optional[str]:
    prod = INDICATION_TO_SPATIAL_COLOC.get(str(indication).upper().strip())
    if not prod:
        return None
    return bucket_key_for(prod)[1]           # resolved from the product manifest (single source of truth)


def read_target_neighbor_rows(target: str, indication: str):
    """Per-(donor, neighbor_cell_type) rows for one target gene in one indication's spatial product.

    Returns a pandas DataFrame (possibly empty) with _PARQUET_COLS. Empty (0 rows) when the gene is
    absent from the panel, None when the indication has no landed product — the caller distinguishes
    'no product' (None) from 'gene not on panel' (empty)."""
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


def read_spatial_colocalization(target: str, indication: str) -> dict:
    """Assemble the spatial tumour-neighbourhood co-localization summary for a (target, indication).

    Rolls the per-donor spatial-coloc rows up to per-neighbour / per-compartment cross-donor medians
    (donor-is-replicate) and classifies into `spatial_coloc_class`. data_unavailable-safe on both 'no
    landed product for this indication' and 'target not on the spatial panel'."""
    rows = read_target_neighbor_rows(target, indication)
    if rows is None:
        return _data_unavailable(target, indication,
                                 note=f"No spatial co-localization product landed for indication "
                                      f"{indication}; spatial_transcriptomics is a named capability gap here.")
    if rows.empty:
        return _data_unavailable(target, indication,
                                 note=f"{target} absent from the spatial panel for {indication} "
                                      f"(not on the CosMx/imaging gene panel).")
    recs = rows.to_dict("records")
    nsum = _stats.neighbor_summary(recs)
    classed = _stats.classify_spatial_coloc(nsum, recs)
    out = dict(classed)
    out["target"] = str(target).upper().strip()
    out["indication"] = str(indication).upper().strip()
    out["product_id"] = INDICATION_TO_SPATIAL_COLOC.get(str(indication).upper().strip())
    out["target_pos_fraction_median"] = round(float(rows["target_pos_fraction"].median()), 5)
    out["_evidence_tier"] = "spatial_measured"
    return out


def _data_unavailable(target: str, indication: str, note: str) -> dict:
    return {
        "spatial_coloc_class": "data_unavailable",
        "top_enriched_compartment": None,
        "top_enriched_value": None,
        "per_compartment": {},
        "per_neighbor": [],
        "immune_adjacency_fraction": None,
        "stromal_adjacency_fraction": None,
        "normal_epithelium_adjacency_fraction": None,
        "target_pos_fraction_median": None,
        "n_donors": 0,
        "n_datasets": 0,
        "target": str(target).upper().strip(),
        "indication": str(indication).upper().strip(),
        "product_id": INDICATION_TO_SPATIAL_COLOC.get(str(indication).upper().strip()),
        "_data_note": note,
    }
