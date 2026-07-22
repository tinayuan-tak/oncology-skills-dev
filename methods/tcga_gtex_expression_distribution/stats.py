"""Distribution primitives for the per-sample expression layer (numpy-only, no S3).

Shared across Q1 (tumor distribution), Q2 (tumor-vs-normal percentile-crossing enrichment), and Q3
(normal-tissue liability). Kept dependency-light + pure so it is unit-testable without any data read.

Cutoff convention (plan-decided, DUAL — routed by metric type):
  - ABSOLUTE questions (detectable/moderate/high fraction) → fixed TPM-anchored cutoffs on
    log2(TPM+1), anchored to DepMap's expressed/highly-expressed convention for cross-target/
    cross-indication consistency: detectable ≥1.0 (TPM≈1), moderate ≥3.46 (TPM≈10), high ≥5.67
    (TPM≈50).
  - ENRICHMENT questions (fraction of tumors above the Nth percentile of NORMAL) → normal-relative
    cutoffs, target-specific, tied to the therapeutic-window framing.
All cutoffs are parameters here and are surfaced in the card's `thresholds:` block (reviewable).
"""
from __future__ import annotations

# log2(TPM+1) absolute cutoffs anchored to DepMap's convention (detectable/high match
# depmap_expression_distribution; moderate added for the spec's detectable/moderate/high tiers).
DETECTABLE_LOG2TPM = 1.0      # TPM ≈ 1
MODERATE_LOG2TPM = 3.4594     # log2(11) ≈ TPM 10
HIGH_LOG2TPM = 5.6724         # log2(51) ≈ TPM 50


def five_number(values) -> dict:
    """min/q1/median/q3/max + p5/p95/p99 + mean/sd/n for a per-sample log2(TPM+1) vector.
    Empty input → all-None with n=0 (honest coverage gap, never a fabricated zero)."""
    import numpy as np
    a = np.asarray(values, dtype=float)
    a = a[~np.isnan(a)]
    if a.size == 0:
        keys = ("n", "min", "p5", "q1", "median", "q3", "p95", "p99", "max", "mean", "sd")
        return {k: (0 if k == "n" else None) for k in keys}
    return {
        "n": int(a.size),
        "min": float(np.min(a)), "p5": float(np.percentile(a, 5)),
        "q1": float(np.percentile(a, 25)), "median": float(np.median(a)),
        "q3": float(np.percentile(a, 75)), "p95": float(np.percentile(a, 95)),
        "p99": float(np.percentile(a, 99)), "max": float(np.max(a)),
        "mean": float(np.mean(a)), "sd": float(np.std(a)),
    }


def coefficient_of_variation(log2tpm_values) -> float:
    """CoV (sd/mean) on LINEAR TPM (undo log2(TPM+1) first — CoV on log values is meaningless).
    Divide-by-zero-safe: returns 0.0 when the linear mean is ~0 (all-unexpressed)."""
    import numpy as np
    a = np.asarray(log2tpm_values, dtype=float)
    a = a[~np.isnan(a)]
    if a.size == 0:
        return 0.0
    lin = np.clip(np.power(2.0, a) - 1.0, 0.0, None)
    mean = float(np.mean(lin))
    if mean <= 1e-9:
        return 0.0
    return float(np.std(lin) / mean)


def expression_fractions(log2tpm_values,
                         detectable=DETECTABLE_LOG2TPM,
                         moderate=MODERATE_LOG2TPM,
                         high=HIGH_LOG2TPM) -> dict:
    """Fraction of samples that are detectable / moderate+ / high+ (ABSOLUTE TPM-anchored cutoffs).
    The spec emphasizes the FRACTION above a biologically meaningful threshold over the median."""
    import numpy as np
    a = np.asarray(log2tpm_values, dtype=float)
    a = a[~np.isnan(a)]
    if a.size == 0:
        return {"detectable_fraction": None, "moderate_fraction": None, "high_fraction": None}
    return {
        "detectable_fraction": float(np.mean(a >= detectable)),
        "moderate_fraction": float(np.mean(a >= moderate)),
        "high_fraction": float(np.mean(a >= high)),
    }


def distribution_pattern(log2tpm_values, detectable=DETECTABLE_LOG2TPM, high=HIGH_LOG2TPM) -> str:
    """Classify shape → {continuous | bimodal | long_tail} via the dependency-light gap heuristic
    (mirrors depmap_expression_distribution + the dependency side; NOT a KDE/dip test — noise on
    small n). bimodal = substantial off-subset AND high-subset with a sparse middle (the target-
    high/-low split for patient selection); long_tail = rare high minority on a mostly-off panel;
    else continuous. n<8 → continuous (too few to call)."""
    import numpy as np
    a = np.asarray(log2tpm_values, dtype=float)
    a = a[~np.isnan(a)]
    if a.size < 8:
        return "continuous"
    frac_off = float(np.mean(a < detectable))
    frac_high = float(np.mean(a >= high))
    frac_mid = float(np.mean((a >= detectable) & (a < high)))
    if frac_off >= 0.20 and frac_high >= 0.20 and frac_mid < max(frac_off, frac_high):
        return "bimodal"
    if frac_high < 0.20 and frac_off >= 0.50 and frac_high > 0.0:
        return "long_tail"
    return "continuous"


def fraction_above_normal_percentile(tumor_log2tpm, normal_log2tpm, percentile=95) -> dict:
    """The spec's HEADLINE Q2 enrichment metric: the fraction of TUMOR samples whose expression
    exceeds the Nth percentile of NORMAL-tissue expression. More actionable than a fold change —
    it directly answers "how much of the tumor population separates from normal."

    Returns {normal_pN, fraction_tumor_above, n_tumor, n_normal} for the given percentile.
    None when either arm is empty (coverage gap)."""
    import numpy as np
    t = np.asarray(tumor_log2tpm, dtype=float); t = t[~np.isnan(t)]
    nrm = np.asarray(normal_log2tpm, dtype=float); nrm = nrm[~np.isnan(nrm)]
    if t.size == 0 or nrm.size == 0:
        return {"percentile": percentile, "normal_pN": None,
                "fraction_tumor_above": None, "n_tumor": int(t.size), "n_normal": int(nrm.size)}
    cutoff = float(np.percentile(nrm, percentile))
    return {
        "percentile": percentile,
        "normal_pN": cutoff,
        "fraction_tumor_above": float(np.mean(t > cutoff)),
        "n_tumor": int(t.size), "n_normal": int(nrm.size),
    }


def distribution_overlap(tumor_log2tpm, normal_log2tpm, bins=50) -> float:
    """Histogram overlap coefficient (OVL) of tumor vs normal distributions ∈ [0,1]: 0 = fully
    separated (clean therapeutic window), 1 = identical. Complements the percentile-crossing metric
    (which is one-sided). None when either arm is empty."""
    import numpy as np
    t = np.asarray(tumor_log2tpm, dtype=float); t = t[~np.isnan(t)]
    nrm = np.asarray(normal_log2tpm, dtype=float); nrm = nrm[~np.isnan(nrm)]
    if t.size == 0 or nrm.size == 0:
        return None
    lo = float(min(t.min(), nrm.min())); hi = float(max(t.max(), nrm.max()))
    if hi <= lo:
        return 1.0
    edges = np.linspace(lo, hi, bins + 1)
    th, _ = np.histogram(t, bins=edges, density=True)
    nh, _ = np.histogram(nrm, bins=edges, density=True)
    width = edges[1] - edges[0]
    return float(np.sum(np.minimum(th, nh)) * width)
