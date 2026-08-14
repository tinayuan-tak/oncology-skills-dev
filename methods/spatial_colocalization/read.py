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
    "STAD": "spatial-coloc-tumor-stad-v1",     # gastric — CosMx (GSE308624); net-new indication (Phase 2)
    "PAAD": "spatial-coloc-tumor-paad-v1",     # pancreatic — Xenium (GSE280634); GI facet (Phase 4)
    "HNSC": "spatial-coloc-tumor-hnsc-v1",     # head&neck — Xenium (GSE300147); INFERRED compartments (mode C, lower tier)
    "NSCLC": "spatial-coloc-tumor-nsclc-v1",   # lung — Xenium-5K (GSE311609); adeno+squamous; INFERRED (mode C)
    "LUAD": "spatial-coloc-tumor-nsclc-v1",    # covered by the NSCLC product (both histologies)
    "LUSC": "spatial-coloc-tumor-nsclc-v1",
}

_PARQUET_COLS = ["gene_symbol", "dataset_id", "donor_id", "neighbor_cell_type",
                 "n_malignant_cells", "target_pos_fraction", "adjacency_fraction", "enrichment_vs_random"]


def _product_ids(indication: str) -> list:
    """The spatial-coloc product id(s) for an indication. A map value may be a single product id (str)
    OR a list of product ids (multiple datasets for the indication, merged at read time). Returns [] if
    the indication has no landed product."""
    v = INDICATION_TO_SPATIAL_COLOC.get(str(indication).upper().strip())
    if not v:
        return []
    return [v] if isinstance(v, str) else list(v)


def read_target_neighbor_rows(target: str, indication: str):
    """Per-(dataset, donor, neighbor_cell_type) rows for one target across ALL of an indication's spatial
    products (multiple datasets are concatenated — donors pool across datasets, and compartment roll-up
    happens downstream). Returns a DataFrame (possibly empty), or None when the indication has no landed
    product — the caller distinguishes 'no product' (None) from 'gene not on any panel' (empty)."""
    prods = _product_ids(indication)
    if not prods:
        return None
    import pandas as pd
    import pyarrow.fs as fs
    import pyarrow.parquet as pq
    s3fs = fs.S3FileSystem(region="us-east-1")
    filters = [("gene_symbol", "==", str(target).upper().strip())]
    frames = []
    for prod in prods:
        key = bucket_key_for(prod)[1]        # resolved from the product manifest (single source of truth)
        try:
            tbl = pq.read_table(f"{S3_BUCKET}/{key}", filesystem=s3fs, filters=filters, columns=_PARQUET_COLS)
        except FileNotFoundError:
            continue                         # a listed product not yet on S3 — skip, don't fail the read
        frames.append(tbl.to_pandas())
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)


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
