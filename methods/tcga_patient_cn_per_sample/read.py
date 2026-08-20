"""Per-gene pushdown reader for tcga-patient-cn-per-sample-v1.

read_patient_cn_per_sample(target, indication=None) -> dict:
  {case_barcode: gistic_call} for the target gene, optionally restricted to an indication's
  TCGA cancer-type cohort. The per-patient CN substrate for the cis-feature-coherence S4
  patient arm (join case_barcode <-> tcga-sample-id-crosswalk-v1.case_barcode to reach
  patient expression).

Absence discipline mirrors tcga_patient_cn.read: a gene genuinely absent from GISTIC (empty
slice) or a NoSuchKey/404 on the product -> {}; a transient/creds/broken-env failure re-raises
so the live-read seam surfaces an honest error instead of a silent empty join.
"""
from __future__ import annotations

import io
import os
from functools import lru_cache

S3_BUCKET = "onc-compbio"
PRODUCT_KEY = "data-catalog/derived/tcga-patient-cn-per-sample-v1/tcga_patient_cn_per_sample.parquet"
DEFAULT_AWS_PROFILE = "cbg"

# indication -> TCGA `cancer type` code(s); mirrors tcga_patient_cn.read.INDICATION_TO_TCGA.
INDICATION_TO_TCGA = {
    "COADREAD": ("COAD", "READ"), "COAD": ("COAD",), "READ": ("READ",),
    "NSCLC": ("LUAD", "LUSC"), "LUAD": ("LUAD",), "LUSC": ("LUSC",),
    "PAAD": ("PAAD",), "PDAC": ("PAAD",), "GC": ("STAD",), "STAD": ("STAD",),
    "BRCA": ("BRCA",), "HNSC": ("HNSC",), "HNSCC": ("HNSC",), "ESCA": ("ESCA",),
    "OV": ("OV",), "PRAD": ("PRAD",), "SKCM": ("SKCM",), "UCEC": ("UCEC",),
}


def _s3_read_bytes(key: str) -> bytes:
    import boto3
    from methods.target_id_sidecar import ensure_aws_profile
    ensure_aws_profile()
    s3 = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", DEFAULT_AWS_PROFILE)).client("s3")
    return s3.get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()


@lru_cache(maxsize=256)
def _read_gene(target: str):
    """Per-gene slice of the product via parquet predicate pushdown. Returns a tuple of
    (case_barcode, gistic_call, cancer_type). Empty tuple only on genuine absence."""
    import pandas as pd
    from methods.target_id_sidecar import is_definitively_absent
    try:
        raw = _s3_read_bytes(PRODUCT_KEY)
        df = pd.read_parquet(io.BytesIO(raw),
                             columns=["gene_symbol", "case_barcode", "gistic_call", "cancer_type"],
                             filters=[("gene_symbol", "==", target)])
        if df.empty:
            return tuple()
        return tuple((str(r.case_barcode), int(r.gistic_call),
                      (str(r.cancer_type) if pd.notna(r.cancer_type) else None))
                     for r in df.itertuples(index=False))
    except Exception as e:  # noqa: BLE001
        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return tuple()
        raise


def read_patient_cn_per_sample(target: str, indication: str | None = None) -> dict[str, int]:
    """{case_barcode: gistic_call} for `target`, restricted to `indication`'s TCGA cohort when given.

    An unknown indication (not in INDICATION_TO_TCGA) returns the pan-cancer map unfiltered — the
    caller decides whether to require a cohort. gistic_call is the discrete GISTIC value {-2..2}."""
    rows = _read_gene(target)
    if not rows:
        return {}
    if indication is None:
        return {case: call for case, call, _ct in rows}
    codes = INDICATION_TO_TCGA.get(indication.upper())
    if not codes:
        return {case: call for case, call, _ct in rows}
    codeset = set(codes)
    return {case: call for case, call, ct in rows if ct in codeset}
