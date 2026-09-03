"""read_expression_purity_confound — per-sample target expression vs tumor purity (Q9).

Join {case: log2_tpm} (recount3 tumor, case-bridged) ⋈ {case: purity} (ABSOLUTE) on TCGA case
barcode, correlate, classify the confound direction. data_unavailable-safe. Pure classifier split
out for unit-testing without S3.
"""
from __future__ import annotations

import io
from functools import lru_cache
from typing import Optional

S3_BUCKET = "onc-compbio"
PANCAN_PREFIX = "data-catalog/sources/gdc-pancanatlas/2018-snapshot-2026-06-27"
ABS_TABLES_KEY = f"{PANCAN_PREFIX}/TCGA_mastercalls.abs_tables_JSedit.fixed.txt"

DEFAULT_AWS_PROFILE = "cbg"

# correlation thresholds (target expression vs tumor purity). POSITIVE r = tumor-intrinsic;
# NEGATIVE r = microenvironment-derived confound.
INTRINSIC_R = 0.3         # r >= INTRINSIC_R (significant) → tumor_intrinsic
CONFOUND_R = -0.3         # r <= CONFOUND_R (significant) → microenvironment_confounded
MIN_PAIRED_SAMPLES = 30
SIGNIFICANCE_ALPHA = 0.05


from methods.target_id_sidecar import ensure_aws_profile


def _boto3():
    import boto3
    return boto3.Session().client("s3")


def _tcga_case(barcode: str) -> str:
    parts = str(barcode).split("-")
    return "-".join(parts[:3]) if len(parts) >= 3 else str(barcode)


@lru_cache(maxsize=1)
def _load_purity_by_case() -> dict:
    """{case_barcode: purity} from ABSOLUTE abs_tables. One purity per case (last wins; consistent
    within case).

    Returns {} ONLY when the ABSOLUTE table is genuinely absent from the bucket (S3 404 /
    NoSuchKey / NoSuchBucket) — a real coverage gap the caller surfaces as data_unavailable
    ("ABSOLUTE purity table unavailable"). Any OTHER failure (missing dependency, absent/expired
    credentials, throttling, a corrupt or schema-changed table) is an ENVIRONMENT break and is
    RAISED, never masked as "no purity data": silently degrading a broken env to data_unavailable
    is the bare-except trap that quietly kills an axis (cf. the missing-openpyxl env-mask bug class).
    The parse is deliberately OUTSIDE the try so a schema drift on a PRESENT table fails loudly too."""
    import pandas as pd
    from botocore.exceptions import ClientError
    try:
        raw = _boto3().get_object(Bucket=S3_BUCKET, Key=ABS_TABLES_KEY)["Body"].read()
    except ClientError as e:
        code = str(e.response.get("Error", {}).get("Code", ""))
        if code in ("NoSuchKey", "NoSuchBucket", "404"):
            return {}          # genuine absence → typed no-data upstream
        raise                  # 403 / AccessDenied / SlowDown / anything else = env break → fail loudly
    df = pd.read_csv(io.BytesIO(raw), sep="\t", usecols=["sample", "purity"])
    df["purity"] = pd.to_numeric(df["purity"], errors="coerce")
    df = df.dropna(subset=["sample", "purity"])
    df["case"] = df["sample"].map(_tcga_case)
    return dict(zip(df["case"], df["purity"]))


def classify_purity_confound(pearson_r: Optional[float], pearson_p: Optional[float],
                             n_paired: int) -> str:
    """Pure classifier — purity-confound class from the expression↔purity correlation. No I/O.

      tumor_intrinsic            — significant POSITIVE r (expression rises with tumor content)
      microenvironment_confounded — significant NEGATIVE r (expression higher in low-purity tumors)
      purity_independent          — no significant correlation either direction
      insufficient_paired_samples — < MIN_PAIRED_SAMPLES paired tumors
    """
    if n_paired < MIN_PAIRED_SAMPLES:
        return "insufficient_paired_samples"
    if pearson_r is None:
        return "data_unavailable"
    significant = pearson_p is None or pearson_p <= SIGNIFICANCE_ALPHA
    if significant and pearson_r >= INTRINSIC_R:
        return "tumor_intrinsic"
    if significant and pearson_r <= CONFOUND_R:
        return "microenvironment_confounded"
    return "purity_independent"


def read_purity_points(target: str, indication: str):
    """Per-paired-tumor (expression, purity) points for the scatter figure — the SAME case-level join
    read_expression_purity_confound correlates. Returns (expr_list, purity_list) or None (no data /
    read error). Used by cli.emit_svg to draw the scatter when no persisted points are passed."""
    try:
        ensure_aws_profile()
        from methods.tcga_gtex_expression_distribution.read import read_tumor_samples_with_case
        expr = read_tumor_samples_with_case(target.upper().strip(), indication)
        if expr is None or len(expr) == 0:
            return None
        purity_by_case = _load_purity_by_case()
        if not purity_by_case:
            return None
        df = expr.groupby("case", as_index=False)["log2_tpm"].mean()
        df["purity"] = df["case"].map(purity_by_case)
        df = df.dropna(subset=["purity"])
        if len(df) < 2:
            return None
        return (df["log2_tpm"].astype(float).tolist(), df["purity"].astype(float).tolist())
    except Exception:  # noqa: BLE001 — figure is best-effort; a read failure just yields no scatter
        return None


def read_expression_purity_confound(target: str, indication: str) -> dict:
    """Q9 — correlate target per-sample tumor expression with tumor purity for a (target,indication).
    Returns the confound class + stats. data_unavailable-safe."""
    ensure_aws_profile()
    sym = target.upper().strip()
    base = {"target": target, "indication": indication, "purity_source": "pancanatlas_absolute"}

    # 1) per-sample tumor expression, case-bridged (reuse the Q1/subtype reader)
    try:
        from methods.tcga_gtex_expression_distribution.read import read_tumor_samples_with_case
        expr = read_tumor_samples_with_case(sym, indication)
    except Exception as e:  # noqa: BLE001
        base.update({"purity_confound_class": "data_unavailable",
                     "_live_read_error": f"expr_read_failed:{type(e).__name__}"})
        return base
    if expr is None or len(expr) == 0:
        base.update({"purity_confound_class": "data_unavailable",
                     "_data_note": f"no per-sample tumor expression for {sym} in {indication}"})
        return base

    # 2) per-case purity (ABSOLUTE)
    purity_by_case = _load_purity_by_case()
    if not purity_by_case:
        base.update({"purity_confound_class": "data_unavailable",
                     "_data_note": "ABSOLUTE purity table unavailable"})
        return base

    # 3) join on case, correlate. A case may have multiple tumor samples → mean expression per case.
    import numpy as np
    import pandas as pd
    df = expr.groupby("case", as_index=False)["log2_tpm"].mean()
    df["purity"] = df["case"].map(purity_by_case)
    df = df.dropna(subset=["purity"])
    n_paired = len(df)
    base["n_paired_samples"] = n_paired
    base["n_expr_samples"] = int(expr["case"].nunique())
    if n_paired < MIN_PAIRED_SAMPLES:
        base["purity_confound_class"] = classify_purity_confound(None, None, n_paired)
        base["_data_note"] = f"only {n_paired} tumors have BOTH expression + purity (need {MIN_PAIRED_SAMPLES})"
        return base

    from scipy import stats
    e = df["log2_tpm"].to_numpy(dtype=float)
    p = df["purity"].to_numpy(dtype=float)
    if e.std() < 1e-9 or p.std() < 1e-9:
        base.update({"purity_confound_class": "data_unavailable",
                     "_data_note": "no variance in expression or purity — correlation undefined"})
        return base
    pearson_r, pearson_p = stats.pearsonr(e, p)
    spearman_r, spearman_p = stats.spearmanr(e, p)
    cls = classify_purity_confound(float(pearson_r), float(pearson_p), n_paired)
    base.update({
        "purity_confound_class": cls,
        "expression_purity_pearson_r": round(float(pearson_r), 4),
        "expression_purity_pearson_p": float(f"{pearson_p:.3g}"),
        "expression_purity_spearman_r": round(float(spearman_r), 4),
        "median_purity": round(float(np.median(p)), 4),
        # honest limits: bulk cannot resolve cell-of-origin; a purity-independent / confounded call is
        # a FLAG for interpretation, not proof — CIBERSORT immune-cell attribution is a later enrichment.
        "cellular_source": "unresolved_from_bulk",
    })
    return base
