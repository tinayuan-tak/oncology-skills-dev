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

# indication code → landed spatial co-localization product(s). Kept in step with the imaging single-cell
# spatial ingests. COADREAD = CosMx CRC atlas (GSE303070, data-catalog #382), the pilot. Adding an
# indication = emit its spatial-coloc product (data-catalog) + one line here.
# A value may be a single product id (str) OR a list (multiple datasets for the indication). DEPTH
# datasets (a 2nd+ cohort for an indication) are mode-C INFERRED-compartment products (evidence_tier
# inferred). Under the spatial_colocalization tier_dominant policy the reader NEVER pools measured +
# inferred donors into one median (that would be the forbidden cross-tier averaging, Rule 5): it reads
# the MEASURED tier first and consults the INFERRED tier ONLY when the measured tier has no rows for the
# target (target off every measured panel, or the indication is pure-inferred). Adding a dataset = emit
# its spatial-coloc product (data-catalog), append it here, and (if mode-C) list it in _INFERRED_PRODUCTS.
_CRC = ["spatial-coloc-tumor-crc-coadread-v1",   # COADREAD lead — CosMx CRC atlas (GSE303070; measured)
        "spatial-coloc-tumor-crc-gse335552-v1"]  # + depth — Xenium CRC liver-mets (GSE335552; inferred, met-site)
_PAAD = ["spatial-coloc-tumor-paad-v1",          # PAAD lead — Xenium PDAC atlas (GSE280634; measured)
         "spatial-coloc-tumor-paad-gse313662-v1", # + depth — Xenium PDAC 5K, 6 donors (GSE313662; inferred)
         "spatial-coloc-tumor-paad-gse310352-v1"] # + depth — CosMx PDAC, 7 slides (GSE310352; inferred)
_NSCLC = ["spatial-coloc-tumor-nsclc-v1",        # NSCLC lead — Xenium-5K (GSE311609; inferred)
          "spatial-coloc-tumor-nsclc-gse319755-v1"]  # + depth — Xenium NSCLC multi-region (GSE319755; inferred)
INDICATION_TO_SPATIAL_COLOC = {
    "COADREAD": _CRC, "COAD": _CRC, "READ": _CRC,
    "STAD": "spatial-coloc-tumor-stad-v1",     # gastric — CosMx (GSE308624); net-new indication (Phase 2)
    "PAAD": _PAAD,                             # pancreatic — GI facet (Phase 4) + depth
    "HNSC": "spatial-coloc-tumor-hnsc-v1",     # head&neck — Xenium (GSE300147); INFERRED compartments (mode C, lower tier)
    "NSCLC": _NSCLC,                           # lung — adeno+squamous; INFERRED (mode C) + depth
    "LUAD": _NSCLC,                            # covered by the NSCLC product(s) (both histologies)
    "LUSC": _NSCLC,
}

# mode-C INFERRED-compartment products (marker-inferred neighbours: scanpy Leiden + marker-score argmax,
# NOT author-curated cell-type labels). Under tier_dominant these are LOWER tier than the measured leads
# and are read only as a fallback. Everything mapped that is NOT listed here is author-curated = measured.
_INFERRED_PRODUCTS = frozenset({
    "spatial-coloc-tumor-hnsc-v1",           # Xenium HNSC (GSE300147); pure-inferred indication
    "spatial-coloc-tumor-nsclc-v1",          # Xenium-5K NSCLC (GSE311609); pure-inferred indication
    "spatial-coloc-tumor-nsclc-gse319755-v1",# Xenium NSCLC multi-region depth (GSE319755)
    "spatial-coloc-tumor-paad-gse313662-v1", # Xenium PDAC 5K depth (GSE313662)
    "spatial-coloc-tumor-paad-gse310352-v1", # CosMx PDAC depth (GSE310352; mode-C inference on CSV->h5ad)
    "spatial-coloc-tumor-crc-gse335552-v1",  # Xenium CRC liver-mets depth (GSE335552)
})

_PARQUET_COLS = ["gene_symbol", "dataset_id", "donor_id", "neighbor_cell_type",
                 "n_malignant_cells", "target_pos_fraction", "adjacency_fraction", "enrichment_vs_random"]


def _product_ids(indication: str) -> list:
    """The spatial-coloc product id(s) for an indication. A map value may be a single product id (str)
    OR a list of product ids (multiple datasets for the indication). Returns [] if the indication has no
    landed product."""
    v = INDICATION_TO_SPATIAL_COLOC.get(str(indication).upper().strip())
    if not v:
        return []
    return [v] if isinstance(v, str) else list(v)


def _tier_of(product_id: str) -> str:
    """measured (author-curated compartment labels) vs inferred (mode-C marker inference)."""
    return "inferred" if product_id in _INFERRED_PRODUCTS else "measured"


def read_target_neighbor_rows(target: str, indication: str):
    """Per-(dataset, donor, neighbor_cell_type) rows for one target, TIER-DOMINANT across an indication's
    spatial products. Returns (frame, tier): the MEASURED tier's products are read first and, if any
    yield rows for the target, ONLY those rows are returned (tier='measured'); the INFERRED tier is
    consulted ONLY when the measured tier is empty (target off every measured panel, or a pure-inferred
    indication) and returns its rows with tier='inferred'. Measured and inferred donors are NEVER pooled
    into one median — that cross-tier averaging is forbidden by the tier_dominant policy (Rule 5).

    Returns (None, None) when the indication has no landed product; (empty DataFrame, None) when products
    exist but the target is on no panel of either tier — the caller distinguishes 'no product' from
    'gene not on any panel'."""
    prods = _product_ids(indication)
    if not prods:
        return None, None
    import pandas as pd
    import pyarrow.fs as fs
    import pyarrow.parquet as pq
    s3fs = fs.S3FileSystem(region="us-east-1")
    filters = [("gene_symbol", "==", str(target).upper().strip())]

    def _read_tier(tier_prods):
        frames = []
        for prod in tier_prods:
            key = bucket_key_for(prod)[1]    # resolved from the product manifest (single source of truth)
            try:
                tbl = pq.read_table(f"{S3_BUCKET}/{key}", filesystem=s3fs, filters=filters, columns=_PARQUET_COLS)
            except FileNotFoundError:
                continue                     # a listed product not yet on S3 — skip, don't fail the read
            df = tbl.to_pandas()
            if not df.empty:
                frames.append(df)
        return pd.concat(frames, ignore_index=True) if frames else None

    for tier in ("measured", "inferred"):
        df = _read_tier([p for p in prods if _tier_of(p) == tier])
        if df is not None and not df.empty:
            return df, tier
    # products exist for the indication, but the target is on no panel of either tier
    return pd.DataFrame(columns=_PARQUET_COLS), None


def read_spatial_colocalization(target: str, indication: str) -> dict:
    """Assemble the spatial tumour-neighbourhood co-localization summary for a (target, indication).

    Rolls the per-donor spatial-coloc rows up to per-neighbour / per-compartment cross-donor medians
    (donor-is-replicate) and classifies into `spatial_coloc_class`. data_unavailable-safe on both 'no
    landed product for this indication' and 'target not on the spatial panel'."""
    rows, tier = read_target_neighbor_rows(target, indication)
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
    # report the product(s) that actually contributed (the winning tier), not the raw indication map value
    out["product_id"] = [p for p in _product_ids(indication) if _tier_of(p) == tier]
    out["target_pos_fraction_median"] = round(float(rows["target_pos_fraction"].median()), 5)
    # tier faithfully reflects which provider tier answered (tier_dominant): measured leads dominate;
    # inferred (mode-C marker inference) only when the target is off every measured panel / pure-inferred.
    out["_evidence_tier"] = "spatial_measured" if tier == "measured" else "spatial_inferred"
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
