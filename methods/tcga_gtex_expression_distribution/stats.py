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


# GTEx tissues whose expression carries the highest on-target-off-tumor LIABILITY — a
# target highly expressed in one of these is a therapeutic-window red flag regardless of
# tumor abundance. Names match the recount3/GTEx tissue vocabulary (uppercased, in the
# gtex-long product's `tissue` column). Curated, declared here (not hardcoded downstream)
# so the card's thresholds/vocab can reference it. Vital/dose-limiting organs.
CRITICAL_NORMAL_TISSUES = (
    "HEART", "BRAIN", "LIVER", "LUNG", "KIDNEY", "NERVE",
    "MUSCLE", "BLOOD", "BONE_MARROW", "ARTERY", "PANCREAS",
)


def normal_tissue_liability(tissue_to_values: dict, high=HIGH_LOG2TPM,
                            critical=CRITICAL_NORMAL_TISSUES) -> dict:
    """Q3 normal-tissue-liability summary over the GTEx atlas (per-tissue log2(TPM+1) vectors).

    The therapeutic-window question: WHERE is the target expressed in normal tissue, and does
    any CRITICAL organ carry high expression (an on-target-off-tumor red flag)?

    Returns:
      highest_tissue / highest_tissue_median      — the top-expressing normal tissue
      critical_organ_max / critical_organ_argmax  — max median among CRITICAL tissues + which
      n_tissues_high                               — # tissues with median >= HIGH cutoff
      n_tissues_detectable                         — # tissues with median >= DETECTABLE
      n_tissues_tested
      tissue_breadth_fraction                      — n_detectable / n_tested (0..1; breadth of normal expression)
    data-gap-safe: empty atlas → all-None."""
    import numpy as np
    rows = []
    for tissue, vals in (tissue_to_values or {}).items():
        arr = np.asarray(vals, dtype=float); arr = arr[~np.isnan(arr)]
        if arr.size == 0:
            continue
        rows.append((str(tissue).upper(), float(np.median(arr)), int(arr.size)))
    if not rows:
        return {"highest_tissue": None, "highest_tissue_median": None,
                "critical_organ_max": None, "critical_organ_argmax": None,
                "n_tissues_high": None, "n_tissues_detectable": None,
                "n_tissues_tested": 0, "tissue_breadth_fraction": None}
    rows.sort(key=lambda r: r[1], reverse=True)
    top_tissue, top_med, _ = rows[0]
    crit = [(t, m) for t, m, _ in rows if t in set(critical)]
    crit_max = max(crit, key=lambda x: x[1]) if crit else None
    n_high = sum(1 for _, m, _ in rows if m >= high)
    n_detect = sum(1 for _, m, _ in rows if m >= DETECTABLE_LOG2TPM)
    return {
        "highest_tissue": top_tissue, "highest_tissue_median": round(top_med, 4),
        "critical_organ_max": (round(crit_max[1], 4) if crit_max else None),
        "critical_organ_argmax": (crit_max[0] if crit_max else None),
        "n_tissues_high": n_high, "n_tissues_detectable": n_detect,
        "n_tissues_tested": len(rows),
        "tissue_breadth_fraction": round(n_detect / len(rows), 4),
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


# Effect-size cutoffs for ε² (epsilon-squared, KW variance-explained). Cohen-style bands
# adapted to ε²: ~0.14 = large, ~0.06 = moderate, below = negligible. The CLASS bins on
# ε² ONLY (effect size) — the p-value is display-only (at TCGA n's KW p is near-always
# significant, so significance ≠ actionability; effect size is the decision-relevant quantity).
EPSILON_SQUARED_LARGE = 0.14
EPSILON_SQUARED_MODERATE = 0.06


def kruskal_epsilon_squared(subtype_vectors: dict, min_group_n: int = 2,
                            min_groups: int = 2) -> dict:
    """Across-subtype omnibus test: is expression DIFFERENT across molecular subtypes, and
    HOW MUCH of the total expression variance does subtype explain?

    Kruskal-Wallis H (non-parametric one-way ANOVA on ranks — log2TPM is non-normal +
    heteroscedastic, so KW is preferred over parametric ANOVA) + the epsilon-squared
    variance-explained EFFECT SIZE (the decision-relevant quantity: "is subtype a
    patient-selection axis for this target, and how strong?") + which strata sit at the
    extremes.

    `subtype_vectors`: {stratum_id: [log2tpm, ...]}. Only strata with >= min_group_n
    finite samples are included; the test needs >= min_groups such strata.

    Returns (data_unavailable-safe — every field present, None when not computable):
      subtype_omnibus_kruskal_h   float|None  — the H statistic
      subtype_omnibus_p           float|None  — asymptotic chi-square p (DISPLAY-ONLY)
      subtype_variance_explained  float|None  — epsilon-squared ε² ∈ [0,1]
      subtype_effect_size_class   str         — large / moderate / negligible / data_unavailable
      which_subtypes_separate     {highest, lowest} stratum ids by median (or None)
      n_subtypes_tested / n_samples_tested
    """
    import numpy as np

    groups, medians = [], {}
    for sid, vals in (subtype_vectors or {}).items():
        a = np.asarray(vals, dtype=float)
        a = a[np.isfinite(a)]
        if a.size >= min_group_n:
            groups.append((sid, a))
            medians[sid] = float(np.median(a))

    base = {"subtype_omnibus_kruskal_h": None, "subtype_omnibus_p": None,
            "subtype_variance_explained": None,
            "subtype_effect_size_class": "data_unavailable",
            "which_subtypes_separate": None,
            "n_subtypes_tested": len(groups),
            "n_samples_tested": int(sum(a.size for _sid, a in groups))}
    if len(groups) < min_groups:
        return base

    # Kruskal-Wallis H on the POOLED mid-ranks (ties → average rank), the standard formula.
    all_vals = np.concatenate([a for _sid, a in groups])
    N = all_vals.size
    ranks = _average_ranks(all_vals)
    # split ranks back per group (concatenation order preserved)
    idx, rank_sums, tie_term = 0, [], 0.0
    for _sid, a in groups:
        r = ranks[idx:idx + a.size]
        rank_sums.append((r.sum(), a.size))
        idx += a.size
    H = (12.0 / (N * (N + 1))) * sum((rs * rs) / n for rs, n in rank_sums) - 3.0 * (N + 1)
    # tie correction: divide H by (1 - Σ(t³-t)/(N³-N))
    _, counts = np.unique(all_vals, return_counts=True)
    ties = counts[counts > 1]
    if ties.size:
        tie_term = float(np.sum(ties ** 3 - ties)) / (N ** 3 - N)
    if tie_term and tie_term < 1.0:
        H = H / (1.0 - tie_term)
    k = len(groups)

    # epsilon-squared: ε² = (H - k + 1) / (N - k). Bounded to [0,1] (H below its df floor
    # → tiny negative from noise; clamp to 0). The variance-explained effect size.
    denom = (N - k)
    eps2 = (H - k + 1) / denom if denom > 0 else None
    if eps2 is not None:
        eps2 = float(min(1.0, max(0.0, eps2)))

    # p-value from the chi-square survival function (df = k-1). DISPLAY-ONLY — see the
    # class-binning note; scipy is used only as the test oracle, so compute p ourselves.
    p = _chisq_sf(H, k - 1)

    hi = max(medians, key=medians.get)
    lo = min(medians, key=medians.get)
    base.update({
        "subtype_omnibus_kruskal_h": float(H),
        "subtype_omnibus_p": (float(p) if p is not None else None),
        "subtype_variance_explained": eps2,
        "subtype_effect_size_class": _classify_effect_size(eps2),
        "which_subtypes_separate": {"highest": hi, "lowest": lo},
    })
    return base


def _average_ranks(values):
    """1-based average (mid) ranks of `values` (ties share the mean of their rank span) —
    the Kruskal-Wallis ranking convention. Pure numpy."""
    import numpy as np
    a = np.asarray(values, dtype=float)
    order = a.argsort(kind="mergesort")
    ranks = np.empty(a.size, dtype=float)
    sorted_a = a[order]
    i = 0
    while i < a.size:
        j = i
        while j + 1 < a.size and sorted_a[j + 1] == sorted_a[i]:
            j += 1
        avg = (i + j) / 2.0 + 1.0   # 1-based average rank over the tie span [i, j]
        ranks[order[i:j + 1]] = avg
        i = j + 1
    return ranks


def _classify_effect_size(eps2) -> str:
    """Bin ε² into the card categorical (effect size ONLY — p is display-only)."""
    if eps2 is None:
        return "data_unavailable"
    if eps2 >= EPSILON_SQUARED_LARGE:
        return "large"
    if eps2 >= EPSILON_SQUARED_MODERATE:
        return "moderate"
    return "negligible"


def _chisq_sf(x, df):
    """Chi-square survival function P(χ²_df > x) for the display-only omnibus p. Uses the
    regularized upper incomplete gamma via math.gamma-free series (math.lgamma) so it needs
    no scipy at runtime (scipy is the TEST oracle only). Returns None on degenerate df."""
    import math
    if x is None or df is None or df < 1 or x < 0:
        return None
    if x == 0:
        return 1.0
    a = df / 2.0
    xx = x / 2.0
    # Lower regularized incomplete gamma P(a, xx) via series (xx < a+1) or continued
    # fraction (else); Q = 1 - P is the survival function.
    if xx < a + 1.0:
        term = 1.0 / a
        summ = term
        n = 1
        while n < 1000:
            term *= xx / (a + n)
            summ += term
            if abs(term) < abs(summ) * 1e-12:
                break
            n += 1
        p_lower = summ * math.exp(-xx + a * math.log(xx) - math.lgamma(a))
        return float(max(0.0, min(1.0, 1.0 - p_lower)))
    # continued fraction for Q(a, xx) (Lentz)
    tiny = 1e-300
    b = xx + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    i = 1
    while i < 1000:
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-12:
            break
        i += 1
    q = math.exp(-xx + a * math.log(xx) - math.lgamma(a)) * h
    return float(max(0.0, min(1.0, q)))
