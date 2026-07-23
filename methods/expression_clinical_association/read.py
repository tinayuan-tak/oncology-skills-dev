"""read_expression_clinical_association — median-split OS log-rank by target expression (Q11).

Join {case: log2_tpm} (recount3 tumor) ⋈ {case: (OS, OS.time)} (TCGA-CDR) on TCGA patient barcode,
median-split expression, log-rank test + hazard direction. data_unavailable-safe. Self-contained
log-rank (no lifelines dependency). Pure classifier split out for unit-testing.
"""
from __future__ import annotations

import io
import os
from functools import lru_cache
from typing import Optional

S3_BUCKET = "onc-compbio"
PANCAN_PREFIX = "data-catalog/sources/gdc-pancanatlas/2018-snapshot-2026-06-27"
CDR_KEY = f"{PANCAN_PREFIX}/TCGA-CDR-SupplementalTableS1.xlsx"

DEFAULT_AWS_PROFILE = "cbg"

MIN_EVENTS = 10          # minimum deaths (events) for a meaningful log-rank
MIN_PER_ARM = 15         # minimum patients per expression arm
SIGNIFICANCE_ALPHA = 0.05


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


def _boto3():
    import boto3
    return boto3.Session().client("s3")


def _tcga_case(barcode: str) -> str:
    parts = str(barcode).split("-")
    return "-".join(parts[:3]) if len(parts) >= 3 else str(barcode)


@lru_cache(maxsize=1)
def _load_cdr():
    """TCGA-CDR as {case_barcode: (OS_event, OS_time)}. OS ∈ {0,1}, OS.time in days. Empty on failure."""
    import pandas as pd
    try:
        raw = _boto3().get_object(Bucket=S3_BUCKET, Key=CDR_KEY)["Body"].read()
        df = pd.read_excel(io.BytesIO(raw), sheet_name=0,
                           usecols=["bcr_patient_barcode", "OS", "OS.time"])
        df = df.dropna(subset=["bcr_patient_barcode", "OS", "OS.time"])
        df["OS"] = pd.to_numeric(df["OS"], errors="coerce")
        df["OS.time"] = pd.to_numeric(df["OS.time"], errors="coerce")
        df = df.dropna(subset=["OS", "OS.time"])
        return {_tcga_case(b): (int(o), float(t))
                for b, o, t in zip(df["bcr_patient_barcode"], df["OS"], df["OS.time"])}
    except Exception:  # noqa: BLE001
        return {}


def _logrank(times_a, events_a, times_b, events_b):
    """Two-group log-rank test from primitives (no lifelines). Returns (chi2, p, hazard_direction).
    hazard_direction: +1 = group A has MORE hazard (worse survival), -1 = less. Uses the standard
    Mantel-Haenszel observed-minus-expected over the pooled event times."""
    import numpy as np
    from scipy import stats
    # build the risk table over unique event times in the pooled sample
    t_all = np.concatenate([times_a, times_b])
    e_all = np.concatenate([events_a, events_b])
    grp = np.concatenate([np.zeros(len(times_a)), np.ones(len(times_b))])  # 0=A, 1=B
    order = np.argsort(t_all)
    t_all, e_all, grp = t_all[order], e_all[order], grp[order]

    event_times = np.unique(t_all[e_all == 1])
    O_a = 0.0; E_a = 0.0; V = 0.0
    for t in event_times:
        at_risk = t_all >= t
        n = at_risk.sum()
        n_a = ((grp == 0) & at_risk).sum()
        d = ((t_all == t) & (e_all == 1)).sum()          # deaths at t (both groups)
        d_a = ((t_all == t) & (e_all == 1) & (grp == 0)).sum()  # deaths at t in A
        if n <= 1:
            continue
        exp_a = d * (n_a / n)
        var = d * (n_a / n) * (1 - n_a / n) * ((n - d) / (n - 1))
        O_a += d_a; E_a += exp_a; V += var
    if V <= 0:
        return 0.0, 1.0, 0
    chi2 = (O_a - E_a) ** 2 / V
    p = float(stats.chi2.sf(chi2, df=1))
    # hazard direction for group A (low-expression arm is A by convention in the caller)
    direction = 1 if (O_a - E_a) > 0 else (-1 if (O_a - E_a) < 0 else 0)
    return float(chi2), p, direction


def classify_survival_association(p: Optional[float], high_expr_hazard_direction: Optional[int],
                                  n_events: int, n_low: int, n_high: int) -> str:
    """Pure classifier — survival-association class. No I/O.

    high_expr_hazard_direction: +1 = HIGH-expression arm has MORE hazard (worse survival), -1 = less.
      expression_high_worse_survival  — significant, high-expr arm worse
      expression_high_better_survival — significant, high-expr arm better
      no_survival_association          — not significant
      insufficient_survival_data       — too few events or too small arms
    """
    if n_events < MIN_EVENTS or n_low < MIN_PER_ARM or n_high < MIN_PER_ARM:
        return "insufficient_survival_data"
    if p is None:
        return "data_unavailable"
    if p <= SIGNIFICANCE_ALPHA and high_expr_hazard_direction == 1:
        return "expression_high_worse_survival"
    if p <= SIGNIFICANCE_ALPHA and high_expr_hazard_direction == -1:
        return "expression_high_better_survival"
    return "no_survival_association"


def read_expression_clinical_association(target: str, indication: str) -> dict:
    """Q11 — median-split OS log-rank by target expression for a (target, indication). Returns the
    association class + log-rank stats. data_unavailable-safe. Univariate/unadjusted (see caveats)."""
    _ensure_aws_profile()
    sym = target.upper().strip()
    base = {"target": target, "indication": indication, "endpoint": "OS",
            "survival_source": "pancanatlas_tcga_cdr"}

    # 1) per-sample tumor expression, case-bridged
    try:
        from methods.tcga_gtex_expression_distribution.read import read_tumor_samples_with_case
        expr = read_tumor_samples_with_case(sym, indication)
    except Exception as e:  # noqa: BLE001
        base.update({"survival_association_class": "data_unavailable",
                     "_live_read_error": f"expr_read_failed:{type(e).__name__}"})
        return base
    if expr is None or len(expr) == 0:
        base.update({"survival_association_class": "data_unavailable",
                     "_data_note": f"no per-sample tumor expression for {sym} in {indication}"})
        return base

    # 2) CDR survival
    cdr = _load_cdr()
    if not cdr:
        base.update({"survival_association_class": "data_unavailable",
                     "_data_note": "TCGA-CDR survival table unavailable"})
        return base

    # 3) join on case (mean expression per case), median-split, log-rank
    import numpy as np
    import pandas as pd
    df = expr.groupby("case", as_index=False)["log2_tpm"].mean()
    df["os"] = df["case"].map(lambda c: cdr.get(c, (None, None))[0])
    df["os_time"] = df["case"].map(lambda c: cdr.get(c, (None, None))[1])
    df = df.dropna(subset=["os", "os_time"])
    n_joined = len(df)
    base["n_patients"] = n_joined
    if n_joined < 2 * MIN_PER_ARM:
        base["survival_association_class"] = "insufficient_survival_data"
        base["_data_note"] = f"only {n_joined} patients with expression + OS (need >= {2*MIN_PER_ARM})"
        return base

    median_expr = float(df["log2_tpm"].median())
    low = df[df["log2_tpm"] <= median_expr]
    high = df[df["log2_tpm"] > median_expr]
    n_low, n_high = len(low), len(high)
    n_events = int(df["os"].sum())

    chi2, p, low_dir = _logrank(low["os_time"].to_numpy(float), low["os"].to_numpy(int),
                                high["os_time"].to_numpy(float), high["os"].to_numpy(int))
    # _logrank returns hazard direction for group A (=low arm); HIGH-arm direction is the inverse.
    high_dir = -low_dir
    cls = classify_survival_association(p, high_dir, n_events, n_low, n_high)

    # median survival per arm (days), for context
    def _median_surv(g):
        # crude: median OS.time among all (not KM median) — a context number, not the KM estimate
        return round(float(g["os_time"].median()), 1) if len(g) else None

    base.update({
        "survival_association_class": cls,
        "logrank_p": float(f"{p:.3g}"),
        "logrank_chi2": round(float(chi2), 3),
        "n_events": n_events,
        "n_high_expr": n_high,
        "n_low_expr": n_low,
        "median_split_log2tpm": round(median_expr, 4),
        "high_expr_hazard_direction": high_dir,   # +1 worse, -1 better, 0 none
        "median_ostime_high_days": _median_surv(high),
        "median_ostime_low_days": _median_surv(low),
    })
    return base
