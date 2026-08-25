"""Per-gene reader over the pan-cancer CANCER-ASSOCIATED-FIBROBLAST (CAF) state pseudobulk product.

Reads sc-pseudobulk-caf-luo-pancancer-v1 (one row per gene_symbol x caf_subtype x cancer_type, from
the Luo et al. 2022 pan-cancer CAF atlas GSE210347 — see data-catalog
scripts/derive_caf_scrna_pseudobulk.py). The product is gene-SORTED (sort key == read filter key ==
gene_symbol), so a per-gene read uses pyarrow S3FileSystem + predicate-pushdown to touch a few
row-groups — the gene-keyed-product invariant the sibling sc_tumor_expression_celltype reader relies on.

Dependencies are pyarrow/pandas/boto3 ONLY — NO scanpy/anndata at read time. Credential discipline:
pyarrow's default cred chain honours AWS_PROFILE=cbg. Mirrors sc_tumor_expression_celltype/read.py.

VERDICT-INERT: a stromal-lens display/context reader (immune-context CAF lane). It emits a
`caf_expression_class` PRIMARY categorical for provenance/availability accounting, but NO
interpretation rule consumes it — it moves no gate verdict.
"""
from __future__ import annotations

from typing import Optional

from methods.catalog_query.read import bucket_key_for

MANIFEST_ID = "sc-pseudobulk-caf-luo-pancancer-v1"
S3_BUCKET = "onc-compbio"

_PARQUET_COLS = ["gene_symbol", "caf_subtype", "cancer_type",
                 "n_cells", "detection_fraction", "abundance_log1p_cp10k"]

# Dropout-aware detection cutoffs (mirror the sibling sc reader; below bulk TPM-fraction cutoffs).
_BROADLY_DETECTED_MIN = 0.5     # a CAF state expressing in >= 50% of its cells
_SUBSET_DETECTED_MIN = 0.10     # a real expressing CAF-cell subset
_EXPRESSING_MIN = 0.25          # a (subtype, cancer) group counts as "expressing" this gene


def _summarize(rows) -> dict:
    """Roll the per-(caf_subtype, cancer_type) rows for one gene up to a per-gene CAF-state summary.
    `rows` is a non-empty pandas DataFrame with _PARQUET_COLS."""
    df = rows
    det = df["detection_fraction"].astype(float)
    idx_max = det.idxmax()
    max_det = float(det.loc[idx_max])
    expressing = df[det >= _EXPRESSING_MIN]
    expressing_subtypes = sorted(expressing["caf_subtype"].astype(str).unique().tolist())

    if max_det >= _BROADLY_DETECTED_MIN:
        cls = "caf_broadly_detected"
    elif max_det >= _SUBSET_DETECTED_MIN:
        cls = "caf_subset_detected"
    else:
        cls = "caf_low"

    return {
        "caf_expression_class": cls,
        "max_detection_fraction": round(max_det, 4),
        "max_detection_caf_subtype": str(df.loc[idx_max, "caf_subtype"]),
        "max_detection_cancer_type": str(df.loc[idx_max, "cancer_type"]),
        "median_detection_fraction": round(float(det.median()), 4),
        "max_abundance_log1p_cp10k": round(float(df["abundance_log1p_cp10k"].astype(float).max()), 4),
        "n_caf_subtypes_expressing": int(len(expressing_subtypes)),
        "n_caf_groups_measured": int(len(df)),
        "n_cancer_types_expressing": int(expressing["cancer_type"].astype(str).nunique()),
        "expressing_caf_subtypes": expressing_subtypes,
    }


def _read_gene_rows(target: str):
    """Per-(caf_subtype, cancer_type) rows for one gene. Returns a pandas DataFrame (possibly empty
    when the gene is absent), or None when the landed product cannot be found (404). Transient S3
    faults propagate (absence discipline)."""
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
    """Per-gene pan-cancer CAF-state summary (immune-context stromal/CAF lens). VERDICT-INERT display
    facet.

    indication is accepted for the generic-dispatch reader contract but NOT used to filter: the Luo
    atlas cancer_type axis (lung/PDAC/bladder/thyroid/colorectal/gastric/breast/ovarian/prostate/ICC)
    is a pan-cancer stromal readout, not a framework-indication scope, so the summary spans all
    measured cancer types. data_unavailable-safe on both "no landed product" and "gene absent"."""
    ind = str(indication).upper().strip() if indication else None
    rows = _read_gene_rows(target)
    if rows is None:
        return _data_unavailable(ind, note=f"No landed sc-pseudobulk CAF product ({MANIFEST_ID}).")
    if rows.empty:
        return _data_unavailable(ind,
                                 note=f"{str(target).upper().strip()} absent from {MANIFEST_ID} "
                                      f"(not measured in the Luo CAF atlas).")
    out = _summarize(rows)
    out["indication"] = ind
    out["product_id"] = MANIFEST_ID
    return out


def _data_unavailable(indication: Optional[str], note: str) -> dict:
    """Honest coverage-gap payload — primary `caf_expression_class: data_unavailable` + a note."""
    return {
        "caf_expression_class": "data_unavailable",
        "max_detection_fraction": None,
        "max_detection_caf_subtype": None,
        "max_detection_cancer_type": None,
        "median_detection_fraction": None,
        "max_abundance_log1p_cp10k": None,
        "n_caf_subtypes_expressing": 0,
        "n_caf_groups_measured": 0,
        "n_cancer_types_expressing": 0,
        "expressing_caf_subtypes": [],
        "indication": indication,
        "product_id": MANIFEST_ID,
        "_data_note": note,
    }
