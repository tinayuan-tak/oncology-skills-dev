"""hpa_pathology_cancer_ihc.read — antibody IHC protein-presence-in-tumor for a target x indication.

read_target_summary(target, indication) resolves the OncoTree indication to an HPA broad cancer type,
pyarrow-pushdown-reads the (gene_symbol, cancer_type) row from hpa-pathology-cancer-ihc-per-gene-v1,
and returns the presence summary. Absence-safe: a genuine 404 / gene-or-cancer miss -> data_unavailable;
a transient/creds/broken-env failure PROPAGATES as an honest _live_read_error (never a silent dead axis).
"""
from __future__ import annotations

import threading
from typing import Optional

from methods.catalog_query.read import bucket_key_for
from methods.target_id_sidecar import ensure_aws_profile, is_definitively_absent

METHOD_VERSION = "1.0.0"
DEFAULT_AWS_PROFILE = "cbg"
DERIVED_MANIFEST_ID = "hpa-pathology-cancer-ihc-per-gene-v1"
S3_BUCKET, DERIVED_S3_KEY = bucket_key_for(DERIVED_MANIFEST_ID)

# OncoTree indication -> HPA broad cancer type (one of 20). HPA's cancer axis is COARSER than OncoTree
# (no LUAD/LUSC split under 'lung cancer'; no COAD/READ split under 'colorectal cancer'), so several
# OncoTree codes map to one HPA type — the reader reports the HPA type it used + a granularity caveat.
# Mirrors the inline map discipline of cptac_protein_deg.INDICATION_TO_CPTAC.
INDICATION_TO_HPA_CANCER = {
    "BRCA": "breast cancer", "BREAST": "breast cancer",
    "COADREAD": "colorectal cancer", "COAD": "colorectal cancer", "READ": "colorectal cancer",
    "NSCLC": "lung cancer", "LUAD": "lung cancer", "LUSC": "lung cancer", "LUNG": "lung cancer",
    "PRAD": "prostate cancer", "PROSTATE": "prostate cancer",
    "GBM": "glioma", "LGG": "glioma", "GLIOMA": "glioma",
    "SKCM": "melanoma", "MEL": "melanoma", "MELANOMA": "melanoma",
    "OV": "ovarian cancer", "OVARIAN": "ovarian cancer",
    "PAAD": "pancreatic cancer", "PDAC": "pancreatic cancer",
    "CESC": "cervical cancer", "CERVICAL": "cervical cancer",
    "UCEC": "endometrial cancer", "ENDOMETRIAL": "endometrial cancer",
    "BLCA": "urothelial cancer", "UROTHELIAL": "urothelial cancer",
    "KIRC": "renal cancer", "KIRP": "renal cancer", "KICH": "renal cancer",
    "CCRCC": "renal cancer", "RENAL": "renal cancer",
    "LIHC": "liver cancer", "HCC": "liver cancer", "LIVER": "liver cancer",
    "STAD": "stomach cancer", "STOMACH": "stomach cancer", "GASTRIC": "stomach cancer",
    "TGCT": "testis cancer", "THCA": "thyroid cancer",
    "HNSC": "head and neck cancer", "HNSCC": "head and neck cancer",
    "DLBCL": "lymphoma", "LYMPHOMA": "lymphoma",
}

_S3FS = None
_S3FS_LOCK = threading.Lock()
_DERIVED_STATUS: Optional[bool] = None

_SUMMARY_FIELDS = (
    "protein_presence_class", "fraction_detected", "fraction_moderate_strong", "staining_score",
    "n_high", "n_medium", "n_low", "n_not_detected", "n_patients_total",
    "prognostic_type", "prognostic_is_significant", "prognostic_p_value",
)


def _get_s3fs():
    global _S3FS
    if _S3FS is None:
        with _S3FS_LOCK:
            if _S3FS is None:
                ensure_aws_profile()
                import pyarrow.fs as fs
                _S3FS = fs.S3FileSystem(region="us-east-1")
    return _S3FS


def _empty(note: str, cancer_type: Optional[str] = None) -> dict:
    return {
        "protein_presence_class": "data_unavailable",
        "hpa_cancer_type": cancer_type,
        "_data_note": note,
        "_data_source": DERIVED_MANIFEST_ID,
        "method_version": METHOD_VERSION,
    }


def read_target_summary(target: str, indication: str = None) -> dict:
    """HPA IHC protein-presence for `target` in `indication`. `indication` IS consumed (OncoTree ->
    HPA cancer type). No indication / unmapped indication / gene-or-cancer absent -> data_unavailable
    (honest). Transient/creds errors propagate as _live_read_error."""
    sym = (target or "").upper().strip()
    if not sym:
        return _empty("no target symbol")
    if not indication:
        return _empty("no indication supplied (HPA IHC presence is per cancer type)")
    cancer_type = INDICATION_TO_HPA_CANCER.get(indication.upper().strip())
    if cancer_type is None:
        return _empty(f"indication {indication!r} has no HPA cancer-type mapping "
                      f"(HPA covers 20 broad types)")

    import pyarrow.parquet as pq
    uri = f"{S3_BUCKET}/{DERIVED_S3_KEY}"
    try:
        tbl = pq.read_table(uri, filesystem=_get_s3fs(),
                            filters=[("gene_symbol", "=", sym)])
    except Exception as e:  # noqa: BLE001 — distinguish definitive-absence from transient
        if is_definitively_absent(e):
            return _empty(f"{DERIVED_MANIFEST_ID} not found (404)", cancer_type)
        raise  # transient/creds/broken-env -> honest _live_read_error at the live-read seam
    if tbl.num_rows == 0:
        return _empty(f"{sym} absent from HPA pathology product", cancer_type)

    rows = tbl.to_pylist()
    match = next((r for r in rows if str(r.get("cancer_type", "")).strip().lower()
                  == cancer_type.lower()), None)
    if match is None:
        return _empty(f"{sym} not scored in HPA cancer type {cancer_type!r}", cancer_type)

    out = {k: match.get(k) for k in _SUMMARY_FIELDS}
    out["hpa_cancer_type"] = cancer_type
    out["indication"] = indication
    out["presence_context"] = (
        f"hpa-pathology-cancer-ihc antibody staining; indication {indication} -> HPA type "
        f"{cancer_type!r} (HPA cancer axis is coarser than OncoTree)")
    out["_data_source"] = DERIVED_MANIFEST_ID
    out["method_version"] = METHOD_VERSION
    return out
