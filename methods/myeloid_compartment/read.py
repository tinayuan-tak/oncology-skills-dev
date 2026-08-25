"""Per-gene reader over the pan-cancer tumour-infiltrating MYELOID-state pseudobulk product.

Reads sc-pseudobulk-myeloid-cheng-v1 (one row per gene_symbol x cancer_type x myeloid_subtype, from
the Cheng et al. 2021 pan-cancer myeloid atlas GSE154763 — see data-catalog
scripts/derive_cheng_myeloid_pseudobulk.py). The product is gene-SORTED (sort key == read filter key
== gene_symbol), so a per-gene read uses pyarrow S3FileSystem + predicate-pushdown to touch a few
row-groups rather than the full file — the same gene-keyed-product invariant the sibling
sc_tumor_expression_celltype reader relies on.

Dependencies are pyarrow/pandas/boto3 ONLY — NO scanpy/anndata/cellxgene-census at read time. The
single-cell machinery lives in the data-catalog emit step; this reads the already-pseudobulked parquet.

Credential discipline: pyarrow's default cred chain honours AWS_PROFILE=cbg (the read-capable profile;
the default SSO role lacks GetObject on onc-compbio). Mirrors sc_tumor_expression_celltype/read.py.

VERDICT-INERT: this is a display/context reader (immune-context suppressive-TME lens). It emits a
`myeloid_expression_class` PRIMARY categorical for provenance/availability accounting, but NO
interpretation rule consumes it — it moves no gate verdict.
"""
from __future__ import annotations

from typing import Optional

from methods.catalog_query.read import bucket_key_for

MANIFEST_ID = "sc-pseudobulk-myeloid-cheng-v1"
S3_BUCKET = "onc-compbio"

# Columns pulled from the parquet (the read filter key + the two single-cell-native statistics + grain).
_PARQUET_COLS = ["gene_symbol", "myeloid_subtype", "cancer_type",
                 "n_cells", "detection_fraction", "abundance_log1p_cp10k"]

# Detection-fraction cutoffs (dropout-aware — scRNA under-detects, so these sit below bulk TPM-fraction
# cutoffs; anchored to the sibling sc_tumor_expression_celltype reader's thresholds).
_BROADLY_DETECTED_MIN = 0.5     # a myeloid state expressing in >= 50% of its cells
_SUBSET_DETECTED_MIN = 0.10     # a real expressing myeloid-cell subset
_EXPRESSING_MIN = 0.25          # a (subtype, cancer) group counts as "expressing" this gene

# Canonical myeloid / suppressive-TAM target-antigen family (the lens this product exists to serve:
# CSF1R-axis, TREM2, SPP1, SIRPA/CD47-axis, ...). Presence flags the gene as a myeloid-target antigen;
# absence is not a negative signal. Verdict-inert.
_MYELOID_TARGET_FAMILY = frozenset({
    "CSF1R", "CSF1", "TREM2", "SPP1", "SIRPA", "CD47", "MRC1", "CD68", "MARCO",
    "LILRB1", "LILRB2", "VSIG4", "SLC11A1", "APOE", "C1QC", "FCGR3A", "CD163",
})


def _summarize(rows) -> dict:
    """Roll the per-(cancer_type, myeloid_subtype) rows for one gene up to a per-gene myeloid-state
    summary. `rows` is a non-empty pandas DataFrame with _PARQUET_COLS."""
    df = rows
    det = df["detection_fraction"].astype(float)
    idx_max = det.idxmax()
    max_det = float(det.loc[idx_max])
    expressing = df[det >= _EXPRESSING_MIN]
    expressing_subtypes = sorted(expressing["myeloid_subtype"].astype(str).unique().tolist())

    if max_det >= _BROADLY_DETECTED_MIN:
        cls = "myeloid_broadly_detected"
    elif max_det >= _SUBSET_DETECTED_MIN:
        cls = "myeloid_subset_detected"
    else:
        cls = "myeloid_low"

    return {
        "myeloid_expression_class": cls,
        "max_detection_fraction": round(max_det, 4),
        "max_detection_myeloid_subtype": str(df.loc[idx_max, "myeloid_subtype"]),
        "max_detection_cancer_type": str(df.loc[idx_max, "cancer_type"]),
        "median_detection_fraction": round(float(det.median()), 4),
        "max_abundance_log1p_cp10k": round(float(df["abundance_log1p_cp10k"].astype(float).max()), 4),
        "n_myeloid_subtypes_expressing": int(len(expressing_subtypes)),
        "n_myeloid_groups_measured": int(len(df)),
        "n_cancer_types_expressing": int(expressing["cancer_type"].astype(str).nunique()),
        "expressing_myeloid_subtypes": expressing_subtypes,
    }


def _read_gene_rows(target: str):
    """Per-(cancer_type, myeloid_subtype) rows for one gene. Returns a pandas DataFrame (possibly
    empty when the gene is absent from the product), or None when the landed product cannot be found
    (404) — the caller maps both to data_unavailable, distinguishing "no product" (None) from "gene
    not in product" (empty). Transient S3 faults propagate (absence discipline)."""
    try:
        _, key = bucket_key_for(MANIFEST_ID)
    except FileNotFoundError:
        return None
    import pyarrow.fs as fs
    import pyarrow.parquet as pq
    s3fs = fs.S3FileSystem(region="us-east-1")   # default cred chain honours AWS_PROFILE=cbg
    filters = [("gene_symbol", "==", str(target).upper().strip())]
    try:
        tbl = pq.read_table(f"{S3_BUCKET}/{key}", filesystem=s3fs,
                            filters=filters, columns=_PARQUET_COLS)
    except FileNotFoundError:
        return None
    return tbl.to_pandas()


def read_target_summary(target: str, indication: Optional[str] = None) -> dict:
    """Per-gene pan-cancer tumour-infiltrating MYELOID-state summary (immune-context suppressive-TME /
    myeloid-target lens). VERDICT-INERT display facet.

    indication is accepted for the generic-dispatch reader contract but NOT used to filter: the Cheng
    atlas cancer_type axis (ESCA/KIDNEY/LYM/MYE/OV-FTC/PAAD/THCA/UCEC) is a pan-cancer myeloid readout,
    not a framework-indication scope, so the summary spans all measured cancer types. data_unavailable-
    safe on both "no landed product" and "gene absent from the product"."""
    ind = str(indication).upper().strip() if indication else None
    rows = _read_gene_rows(target)
    if rows is None:
        return _data_unavailable(target, ind,
                                 note=f"No landed sc-pseudobulk myeloid product ({MANIFEST_ID}).")
    if rows.empty:
        return _data_unavailable(target, ind,
                                 note=f"{str(target).upper().strip()} absent from {MANIFEST_ID} "
                                      f"(not measured in the Cheng myeloid atlas).")
    out = _summarize(rows)
    out["myeloid_target_family_flag"] = str(target).upper().strip() in _MYELOID_TARGET_FAMILY
    out["indication"] = ind
    out["product_id"] = MANIFEST_ID
    return out


def _data_unavailable(target: str, indication: Optional[str], note: str) -> dict:
    """The honest coverage-gap payload — a primary `myeloid_expression_class: data_unavailable`
    (which the skills resolver's data_unavailable detection honours) plus a human-readable note."""
    return {
        "myeloid_expression_class": "data_unavailable",
        "max_detection_fraction": None,
        "max_detection_myeloid_subtype": None,
        "max_detection_cancer_type": None,
        "median_detection_fraction": None,
        "max_abundance_log1p_cp10k": None,
        "n_myeloid_subtypes_expressing": 0,
        "n_myeloid_groups_measured": 0,
        "n_cancer_types_expressing": 0,
        "expressing_myeloid_subtypes": [],
        "myeloid_target_family_flag": str(target).upper().strip() in _MYELOID_TARGET_FAMILY,
        "indication": indication,
        "product_id": MANIFEST_ID,
        "_data_note": note,
    }
