"""read_expression_purity_confound — per-sample target expression vs tumor purity (Q9).

Join {case: log2_tpm} (recount3 tumor, case-bridged) ⋈ {case: purity} (ABSOLUTE) on TCGA case
barcode, correlate, classify the confound direction. data_unavailable-safe. Pure classifier split
out for unit-testing without S3.
"""

from __future__ import annotations

import io
import logging
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)

S3_BUCKET = "onc-compbio"
PANCAN_PREFIX = "data-catalog/sources/gdc-pancanatlas/2018-snapshot-2026-06-27"
ABS_TABLES_KEY = f"{PANCAN_PREFIX}/TCGA_mastercalls.abs_tables_JSedit.fixed.txt"

DEFAULT_AWS_PROFILE = "cbg"

# correlation thresholds (target expression vs tumor purity). POSITIVE r = tumor-intrinsic;
# NEGATIVE r = microenvironment-derived confound.
INTRINSIC_R = 0.3  # r >= INTRINSIC_R (significant) → tumor_intrinsic
CONFOUND_R = -0.3  # r <= CONFOUND_R (significant) → microenvironment_confounded
MIN_PAIRED_SAMPLES = 30
SIGNIFICANCE_ALPHA = 0.05

# Purity-SPREAD power gate. Detecting a purity confound REQUIRES the purity regressor to vary:
# a narrow purity band cannot resolve an expression↔purity association, so a `purity_independent`
# call from a tight band is UNDER-POWERED, not reassuring (cf. card caveat — "in high-purity
# cohorts the purity range may be too narrow to resolve a confound"). The n>=MIN_PAIRED_SAMPLES
# and near-zero-variance guards do NOT catch this: a cohort can have 100+ paired cases with real
# (non-zero) but tightly-concentrated purity and still be blind to a confound.
#
# MIN_PURITY_IQR chosen from the observed corpus distribution of the paired-purity IQR across the
# 31 TCGA indications this method serves (broadly-expressed proxy, purity is target-independent):
#   IQR percentiles  p0=0.153  p10=0.190  p25=0.220  p50=0.250  p75=0.282  p90=0.358  p100=0.380
# The narrow tail is the small HIGH-purity cohorts (median purity 0.85-0.86): ACC 0.153, KICH 0.160,
# UCS 0.172 — then a clear gap to OV 0.190. 0.18 sits in that gap, flagging exactly the unambiguous
# "high-purity cohort, band too narrow to resolve a confound" case the card warns about, without
# flagging the mid-spread majority (honest, not conservative-to-a-fault). Emitted as an advisory
# qualifier field alongside the raw `purity_range_iqr` — the class vocabulary is unchanged, so a
# genuine wide-spread `purity_independent` still grades cleanly; a consumer keys the flag to decide
# how confidently to read a `purity_independent` call.
MIN_PURITY_IQR = 0.18


from onc_methods.target_id_sidecar import ensure_aws_profile, s3_client


def _tcga_case(barcode: str) -> str:
    parts = str(barcode).split("-")
    return "-".join(parts[:3]) if len(parts) >= 3 else str(barcode)


def collapse_purity_by_case(samples, purities) -> dict:
    """{case_barcode: purity} collapsing sample-level ABSOLUTE purity to ONE value per TCGA case
    by MEAN over the case's samples — pure (no I/O), so it is unit-testable from stored raw rows.

    Replaces a `dict(zip(...))` that kept only the LAST row's purity when a case had multiple
    ABSOLUTE samples (primary+metastasis / multiple aliquots) with differing purity; because the
    rows are unsorted the "winner" was input-order-dependent and could flip a borderline pearson_r
    across the ±0.3 class cut. Mean here MATCHES the mean-expression collapse the caller pairs it
    against (read_expression_purity_confound step 3)."""
    import pandas as pd

    df = pd.DataFrame({"sample": list(samples), "purity": pd.to_numeric(list(purities), errors="coerce")})
    df = df.dropna(subset=["sample", "purity"])
    df["case"] = df["sample"].map(_tcga_case)
    return df.groupby("case")["purity"].mean().to_dict()


@lru_cache(maxsize=1)
def _load_purity_by_case() -> dict:
    """{case_barcode: purity} from ABSOLUTE abs_tables. One purity per case (mean over the case's
    samples, see collapse_purity_by_case).

    Returns {} ONLY when the ABSOLUTE table is genuinely absent from the bucket (S3 404 /
    NoSuchKey / NoSuchBucket) — a real coverage gap the caller surfaces as data_unavailable
    ("ABSOLUTE purity table unavailable"). Any OTHER failure (missing dependency, absent/expired
    credentials, throttling, a corrupt or schema-changed table) is an ENVIRONMENT break and is
    RAISED, never masked as "no purity data": silently degrading a broken env to data_unavailable
    is the bare-except trap that quietly kills an axis (cf. the missing-openpyxl env-mask bug class).
    The parse is deliberately OUTSIDE the try so a schema drift on a PRESENT table fails loudly too.

    NOTE (lru_cache): a genuine {} absence is pinned process-wide, so an ABSOLUTE table that appears
    mid-process is not re-read. This is intentional (the table is a static snapshot); raises are NOT
    memoized, so a transient env break still re-attempts on the next call.

    S3 read goes through the shared s3_client() helper: it falls back from the (dev-only) `cbg`
    profile to the ambient credential chain when the profile is absent (CI / prod / instance-role) —
    so client construction no longer raises ProfileNotFound — and adds adaptive retry that absorbs
    throttling/SlowDown on the purity read."""
    import pandas as pd
    from botocore.exceptions import ClientError

    try:
        raw = s3_client().get_object(Bucket=S3_BUCKET, Key=ABS_TABLES_KEY)["Body"].read()
    except ClientError as e:
        code = str(e.response.get("Error", {}).get("Code", ""))
        if code in ("NoSuchKey", "NoSuchBucket", "404"):
            return {}  # genuine absence → typed no-data upstream
        raise  # 403 / AccessDenied / SlowDown / anything else = env break → fail loudly
    df = pd.read_csv(io.BytesIO(raw), sep="\t", usecols=["sample", "purity"])
    return collapse_purity_by_case(df["sample"], df["purity"])


def classify_purity_confound(pearson_r: Optional[float], pearson_p: Optional[float], n_paired: int) -> str:
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


def purity_spread_iqr(purity_values) -> Optional[float]:
    """IQR (Q75-Q25) of the paired ABSOLUTE purity vector — an honest spread/power qualifier.

    Pure (no I/O), so it is unit-testable from a stored raw purity vector. Returns None when fewer
    than two finite values are present (spread undefined)."""
    import numpy as np

    p = np.asarray(list(purity_values), dtype=float)
    p = p[np.isfinite(p)]
    if p.size < 2:
        return None
    q25, q75 = np.percentile(p, [25, 75])
    return float(q75 - q25)


def is_purity_spread_underpowered(purity_range_iqr: Optional[float]) -> bool:
    """True when the paired purity band is too narrow (IQR < MIN_PURITY_IQR) to resolve a confound.

    A None IQR (undefined spread) is NOT flagged as under-powered here — that degenerate case is
    already routed to data_unavailable by the near-zero-variance guard upstream."""
    return purity_range_iqr is not None and purity_range_iqr < MIN_PURITY_IQR


def read_purity_points(target: str, indication: str):
    """Per-paired-tumor (expression, purity) points for the scatter figure — the SAME case-level join
    read_expression_purity_confound correlates. Returns (expr_list, purity_list) or None (no data /
    read error). Used by cli.emit_svg to draw the scatter when no persisted points are passed."""
    try:
        ensure_aws_profile()
        from onc_methods.tcga_gtex_expression_distribution.read import read_tumor_samples_with_case

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
    except Exception as e:  # absence-discipline: exempt -- figure-only best-effort, post-verdict; a read failure just yields no scatter, noqa: BLE001
        # Figure-only (called AFTER the real class is computed) → cannot produce a false verdict, so a
        # failure degrades to "no scatter" rather than propagating. Log it instead of swallowing blindly
        # so the dropped figure is diagnosable.
        logger.debug("read_purity_points(%s, %s) failed, no scatter: %s", target, indication, e)
        return None


def read_expression_purity_confound(target: str, indication: str) -> dict:
    """Q9 — correlate target per-sample tumor expression with tumor purity for a (target,indication).
    Returns the confound class + stats. data_unavailable-safe."""
    ensure_aws_profile()
    sym = target.upper().strip()
    base = {"target": target, "indication": indication, "purity_source": "pancanatlas_absolute"}

    # 1) per-sample tumor expression, case-bridged (reuse the Q1/subtype reader)
    from onc_methods.tcga_gtex_expression_distribution.read import read_tumor_samples_with_case

    # Absence discipline (#832): read_tumor_samples_with_case already applies the absence discipline
    # internally (genuine NoSuchKey/404/FileNotFound -> EMPTY frame; transient/creds/broken-env
    # re-raised), so genuine absence arrives here as an empty frame and is handled by the len(expr)==0
    # guard below. A broad except here would only mask a transient fault as
    # purity_confound_class=data_unavailable — let it PROPAGATE (honest _live_read_error at the compose
    # seam) instead.
    expr = read_tumor_samples_with_case(sym, indication)
    if expr is None or len(expr) == 0:
        base.update(
            {
                "purity_confound_class": "data_unavailable",
                "_data_note": f"no per-sample tumor expression for {sym} in {indication}",
            }
        )
        return base

    # 2) per-case purity (ABSOLUTE)
    purity_by_case = _load_purity_by_case()
    if not purity_by_case:
        base.update({"purity_confound_class": "data_unavailable", "_data_note": "ABSOLUTE purity table unavailable"})
        return base

    # 3) join on case, correlate. A case may have multiple tumor samples → mean expression per case.
    import numpy as np

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
        base.update(
            {
                "purity_confound_class": "data_unavailable",
                "_data_note": "no variance in expression or purity — correlation undefined",
            }
        )
        return base
    pearson_r, pearson_p = stats.pearsonr(e, p)
    spearman_r, spearman_p = stats.spearmanr(e, p)
    cls = classify_purity_confound(float(pearson_r), float(pearson_p), n_paired)
    purity_iqr = purity_spread_iqr(p)
    base.update(
        {
            "purity_confound_class": cls,
            "expression_purity_pearson_r": round(float(pearson_r), 4),
            "expression_purity_pearson_p": float(f"{pearson_p:.3g}"),
            "expression_purity_spearman_r": round(float(spearman_r), 4),
            "median_purity": round(float(np.median(p)), 4),
            # honest SPREAD qualifier: median_purity conveys location, this conveys whether the
            # design could resolve a confound at all. A narrow band (underpowered) means a
            # purity_independent call abstains rather than reassures — the class stays unchanged.
            "purity_range_iqr": round(purity_iqr, 4) if purity_iqr is not None else None,
            "purity_spread_underpowered": is_purity_spread_underpowered(purity_iqr),
            # honest limits: bulk cannot resolve cell-of-origin; a purity-independent / confounded call is
            # a FLAG for interpretation, not proof — CIBERSORT immune-cell attribution is a later enrichment.
            "cellular_source": "unresolved_from_bulk",
        }
    )
    return base
