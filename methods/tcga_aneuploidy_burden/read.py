"""tcga_aneuploidy_burden.read — per-indication genome-instability burden summary.

Reads PanCanAtlas seg_based_scores.tsv (per-sample frac_altered = fraction of genome CN-altered),
scopes to an indication's TCGA project(s) via merged_sample_quality_annotations (patient_barcode →
cancer type — the SAME join functional_gene_state uses), and summarizes the cohort's aneuploidy
burden distribution + a coarse cohort class. Indication-level (aneuploidy is genome-wide, not per-gene).
"""
from __future__ import annotations

import io
import os
from functools import lru_cache
from typing import Optional

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"
PANCAN_PREFIX = "data-catalog/sources/gdc-pancanatlas/2018-snapshot-2026-06-27"
SEG_SCORES_KEY = f"{PANCAN_PREFIX}/seg_based_scores.tsv"
SAMPLE_ANNOT_KEY = f"{PANCAN_PREFIX}/merged_sample_quality_annotations.tsv"

# framework indication → TCGA `cancer type` code(s) in merged_sample_quality_annotations
# (mirrors functional_gene_state.INDICATION_TO_TCGA; kept local to avoid cross-method coupling).
INDICATION_TO_TCGA = {
    "COADREAD": ("COAD", "READ"), "COAD": ("COAD",), "READ": ("READ",),
    "NSCLC": ("LUAD", "LUSC"), "LUAD": ("LUAD",), "LUSC": ("LUSC",),
    "PAAD": ("PAAD",), "PDAC": ("PAAD",), "GC": ("STAD",), "STAD": ("STAD",),
    "BRCA": ("BRCA",), "HNSC": ("HNSC",), "HNSCC": ("HNSC",), "ESCA": ("ESCA",),
    "OV": ("OV",), "PRAD": ("PRAD",), "SKCM": ("SKCM",),
}
# Cohort aneuploidy-burden class cutoffs on MEDIAN frac_altered (fraction of genome CN-altered).
# Anchored to the pan-cancer spread (Taylor 2018: quiet genomes ~<0.1, highly aneuploid >~0.4).
_HIGH_MEDIAN = 0.40
_LOW_MEDIAN = 0.10


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


def _s3_read_bytes(key: str) -> bytes:
    import boto3
    _ensure_aws_profile()
    s3 = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", DEFAULT_AWS_PROFILE)).client("s3")
    return s3.get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()


def _barcode_to_patient(sample: str) -> str:
    """seg_based_scores Sample is a 4-segment barcode (TCGA-02-0001-01); the annotation table keys
    on the 3-segment patient barcode (TCGA-02-0001). Truncate to join."""
    parts = str(sample).split("-")
    return "-".join(parts[:3]) if len(parts) >= 3 else str(sample)


@lru_cache(maxsize=1)
def _load_sample_cancer_types() -> dict:
    """{patient_barcode: cancer_type} from merged_sample_quality_annotations. Empty on failure."""
    import pandas as pd
    try:
        raw = _s3_read_bytes(SAMPLE_ANNOT_KEY)
        df = pd.read_csv(io.BytesIO(raw), sep="\t", usecols=["patient_barcode", "cancer type"], dtype=str)
        df = df.dropna(subset=["patient_barcode", "cancer type"])
        return dict(zip(df["patient_barcode"], df["cancer type"]))
    except Exception:  # noqa: BLE001
        return {}


@lru_cache(maxsize=1)
def _load_seg_scores():
    """seg_based_scores.tsv → DataFrame (Sample, frac_altered, n_segs, n_extrema). Empty on failure."""
    import pandas as pd
    try:
        raw = _s3_read_bytes(SEG_SCORES_KEY)
        return pd.read_csv(io.BytesIO(raw), sep="\t")
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


def _classify_burden(median_frac: Optional[float]) -> str:
    if median_frac is None:
        return "data_unavailable"
    if median_frac >= _HIGH_MEDIAN:
        return "highly_aneuploid"
    if median_frac <= _LOW_MEDIAN:
        return "quiet_genome"
    return "intermediate_aneuploidy"


def aneuploidy_burden_for_indication(indication: str) -> dict:
    """Per-indication genome-instability burden summary from PanCanAtlas seg-based scores.

    Returns cohort aneuploidy_burden_class {highly_aneuploid / intermediate_aneuploidy /
    quiet_genome / data_unavailable} + the frac_altered distribution (median/p25/p75/n_samples).
    Indication-level (genome-wide phenotype); target-independent context. data_unavailable when the
    file/indication is unresolvable."""
    import numpy as np
    codes = INDICATION_TO_TCGA.get(str(indication or "").upper().strip())
    if not codes:
        return _unavailable(f"no TCGA project mapping for indication={indication!r}")
    seg = _load_seg_scores()
    if seg is None or seg.empty or "frac_altered" not in seg.columns:
        return _unavailable("seg_based_scores unavailable")
    cancer = _load_sample_cancer_types()
    if not cancer:
        return _unavailable("sample→cancer-type annotation unavailable")

    seg = seg.copy()
    seg["_patient"] = seg["Sample"].map(_barcode_to_patient)
    seg["_ctype"] = seg["_patient"].map(cancer)
    sub = seg[seg["_ctype"].isin(set(codes))]
    vals = sub["frac_altered"].dropna().astype(float)
    if len(vals) == 0:
        return _unavailable(f"no seg-score samples for {indication} ({codes})")

    median = float(np.median(vals))
    return {
        "aneuploidy_burden_class": _classify_burden(median),
        "median_fraction_genome_altered": median,
        "p25_fraction_genome_altered": float(np.percentile(vals, 25)),
        "p75_fraction_genome_altered": float(np.percentile(vals, 75)),
        "n_samples": int(len(vals)),
        "aneuploidy_burden_context": (
            f"{indication}: median {median:.2f} of the genome CN-altered across {len(vals)} "
            f"PanCanAtlas samples (per-sample seg-based frac_altered; genome-wide CIN burden, "
            f"target-independent)"
        ),
        "method_version": "0.1.0",
        "_data_source": "gdc-pancanatlas-cnv-2018",
    }


def _unavailable(note: str) -> dict:
    return {
        "aneuploidy_burden_class": "data_unavailable",
        "median_fraction_genome_altered": None,
        "p25_fraction_genome_altered": None,
        "p75_fraction_genome_altered": None,
        "n_samples": 0,
        "aneuploidy_burden_context": None,
        "method_version": "0.1.0",
        "_data_note": note,
    }
