"""Per-target reader over the spatial region-RNA product + the compartment assembler.

Reads spatial-region-rna-{indication}-v1 (one row per gene_symbol × donor × compartment, from
data-catalog scripts/aggregate_spatial_region_rna.py; NanoString GeoMx DSP Whole Transcriptome Atlas).
Gene-SORTED → predicate-pushdown per target. pyarrow/pandas/boto3 ONLY — no GeoMx tooling at read time
(that lives in the emit step).

Reports the MEASURED, spatially-resolved RNA expression of a target in the TUMOUR compartment vs the TME
— region-level (ROI = a segmented tissue region), NOT single-cell. A distinct claim from the region
PROTEIN product (antibody signal) and from the dissociated scRNA products (no tissue architecture).
"""
from __future__ import annotations

from typing import Optional

from . import stats as _stats
from methods.catalog_query.read import bucket_key_for

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"

# indication -> landed spatial region-RNA product (GeoMx DSP). HNSC = GSE290057 (Whole Transcriptome
# Atlas, the WTA companion to the HNSC 580-plex region-PROTEIN product); NSCLC = GSE174743 (Cancer
# Transcriptome Atlas, ~1.7k-gene targeted panel) covering all three lung histologies. Adding an indication
# = emit its spatial-region-rna product (data-catalog) + one line here.
INDICATION_TO_REGION_RNA = {
    "HNSC": "spatial-region-rna-hnsc-v1",
    "NSCLC": "spatial-region-rna-nsclc-v1",   # lung — GeoMx Cancer Transcriptome Atlas (GSE174743)
    "LUAD": "spatial-region-rna-nsclc-v1",     # covered by the NSCLC product (both histologies)
    "LUSC": "spatial-region-rna-nsclc-v1",
    "COADREAD": "spatial-region-rna-coadread-v1",   # colorectal — GeoMx WTA (GSE281413); PanCK/CD45/Vimentin segments
    "PAAD": "spatial-region-rna-paad-v1",           # pancreatic — GeoMx WTA (GSE199102 Broad hPDAC); Epithelial/Immune/CAF segments
}

_PARQUET_COLS = ["gene_symbol", "donor_id", "compartment", "abundance_lcpm", "detected"]


def _product_key(indication: str) -> Optional[str]:
    prod = INDICATION_TO_REGION_RNA.get(str(indication).upper().strip())
    if not prod:
        return None
    return bucket_key_for(prod)[1]


def read_target_rna_rows(target: str, indication: str):
    """Per-(donor, compartment) region-RNA rows for one target gene in one indication's product.

    DataFrame (possibly empty) with _PARQUET_COLS; None when the indication has no landed product,
    empty when the target gene is not on the WTA (or off-panel for a targeted deposit)."""
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


def read_spatial_region_rna(target: str, indication: str) -> dict:
    """Assemble the spatial region-RNA tumour-compartment summary for a (target, indication).

    Cross-donor median TUMOUR vs TME abundance + spatial_rna_class. data_unavailable-safe on
    'no product for indication' and 'target gene not on the GeoMx panel'."""
    rows = read_target_rna_rows(target, indication)
    if rows is None:
        return _data_unavailable(target, indication,
                                 note=f"No spatial region-RNA product landed for indication "
                                      f"{indication}; spatial_rna is a named capability gap here.")
    if rows.empty:
        return _data_unavailable(target, indication,
                                 note=f"{target} not on the GeoMx panel for {indication} "
                                      f"(gene absent from the deposited matrix).")
    recs = rows.to_dict("records")
    summ = _stats.summarize_rna(recs)
    classed = _stats.classify_region_rna(summ, recs)
    out = dict(classed)
    out["target"] = str(target).upper().strip()
    out["indication"] = str(indication).upper().strip()
    out["product_id"] = INDICATION_TO_REGION_RNA.get(str(indication).upper().strip())
    out["_evidence_tier"] = "spatial_rna_measured"
    return out


def _data_unavailable(target: str, indication: str, note: str) -> dict:
    return {
        "spatial_rna_class": "data_unavailable",
        "tumour_abundance_lcpm": None,
        "tme_abundance_lcpm": None,
        "tumour_vs_tme_delta": None,
        "detected_tumour": None,
        "n_donors": 0,
        "n_datasets": 0,
        "target": str(target).upper().strip(),
        "indication": str(indication).upper().strip(),
        "product_id": INDICATION_TO_REGION_RNA.get(str(indication).upper().strip()),
        "_data_note": note,
    }
