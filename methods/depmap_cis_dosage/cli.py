#!/usr/bin/env python3
"""depmap_cis_dosage CLI — cis-feature → own-expression coupling compute.

Computes the cross-cell-line correlation between target T's OWN relative copy-number and its OWN
log2(TPM+1) expression across the DepMap panel (cis-dosage), classifies the coupling, and reports an
amplified-vs-neutral expression contrast for interpretability. Pure compute over two loaded dicts; the
statistic (Spearman primary, robust to CN outliers; Pearson reported) mirrors depmap_expression_dependency.

This module owns only the CN↔expression correlation, the coupling classification, and the output field
names. It reads NO Chronos — dependency (leg-2) is owned by the reused cards.
"""

from __future__ import annotations

METHOD_VERSION = "0.1.0"

# --- classification thresholds (mirror cards/cis-feature-expression-coherence.card.yaml) ---
STRONG_DOSAGE_SPEARMAN_R = 0.4  # cn_dosage_coupled_strong
MODERATE_DOSAGE_SPEARMAN_R = 0.25  # cn_dosage_coupled_moderate
SIGNIFICANCE_ALPHA = 0.01
MIN_CELL_LINES_FOR_CORRELATION = 50
# CN-variance floor → below this the panel is near-diploid = untestable (cn_invariant_panel).
# Keyed on the p90-p10 spread, NOT the IQR: focal-amplification oncogenes (ERBB2/MYC) are bulk-diploid
# with an amplified TAIL, so their IQR (middle 50%) is ~0 even though the tail carries real, significant
# rank-correlation signal. The IQR gate mis-classified ERBB2 (IQR 0.18 but Spearman r=0.26, p=1e-15,
# 71 amplified lines) as invariant. p90-p10 captures the tail (ERBB2 p90-p10 = 0.55) while staying
# robust to a single extreme outlier. (calibration finding 2026-08-20.)
MIN_RELATIVE_CN_P10_P90_SPREAD = 0.2
# Focal-amplification convention (relative CN, diploid ~ 1.0; NOT log2). 1.5 = the distribution card's
# focal-amp bin edge (depmap_cn_distribution.FOCAL_AMP), used for the descriptive amplified-vs-neutral
# expression contrast AND (below) the focal-amplification subset ESCAPE.
AMPLIFICATION_THRESHOLD = 1.5

# --- focal-amplification SUBSET escape (calibration finding 2026-09-12) --------------------------------
# cis-dosage is intrinsically a TAIL phenomenon for focal-amplification oncogenes: the panel is
# bulk-diploid with an amplified TAIL, so the pan-panel Spearman is DILUTED by the ~diploid body and
# under-calls a genuine amplification-driven dosage jump. ERBB2 is the archetype — Spearman r=0.23
# (< the 0.25 moderate gate → cn_dosage_uncoupled) DESPITE +2.28 log2TPM in 155 amplified lines, which
# then let a spurious minority-methylation subset override it to a (biologically absurd) epigenetic-
# silencing verdict. Mirror the depmap_methylation_silencing subset-primary design: when the pan-panel
# correlation is below the moderate gate BUT the amplified subset OVER-expresses strongly and
# significantly (one-sided Mann-Whitney, amplified > neutral), classify coupled via the subset path.
# cis_dosage_driver records which path drove the call (pan_panel_correlation | focal_amplification_subset).
MIN_AMPLIFIED_FOR_SUBSET = 20  # min amplified (rel CN > 1.5) lines to run the focal-amp subset contrast
MIN_NEUTRAL_COMPARATOR = 30  # min non-amplified comparator lines
STRONG_FOCAL_AMP_DELTA = 2.0  # mean log2TPM (amplified - neutral); strong over-expression → coupled_strong
MODERATE_FOCAL_AMP_DELTA = 1.0  # moderate over-expression → coupled_moderate


def compute_cis_dosage(
    cn_by_model: dict,
    tpm_by_model: dict,
    strong_r: float = STRONG_DOSAGE_SPEARMAN_R,
    moderate_r: float = MODERATE_DOSAGE_SPEARMAN_R,
    significance_alpha: float = SIGNIFICANCE_ALPHA,
    min_cell_lines: int = MIN_CELL_LINES_FOR_CORRELATION,
    min_cn_spread: float = MIN_RELATIVE_CN_P10_P90_SPREAD,
    amplification_threshold: float = AMPLIFICATION_THRESHOLD,
) -> dict:
    """Compute the cis-feature-expression-coherence summary_fields.

    Evaluated universe = lines with BOTH relative CN AND log2TPM present. cis_dosage_class is driven by
    the CN↔expression Spearman correlation; a near-diploid panel (CN p90-p10 spread < min) is
    cn_invariant_panel (untestable), NOT cn_dosage_uncoupled. Higher CN → higher expression = POSITIVE
    r = coupled. The invariant gate keys on the p90-p10 spread (tail-sensitive), NOT the IQR, so
    focal-amplification oncogenes (bulk-diploid + amplified tail; ERBB2/MYC) are correctly testable.
    """
    import numpy as np
    from scipy import stats

    evaluated = sorted(set(cn_by_model) & set(tpm_by_model))
    n = len(evaluated)

    def _base(cls: str, **extra) -> dict:
        out = {
            "n_cell_lines_evaluated": n,
            "cn_expr_spearman_r": None,
            "cn_expr_spearman_p": None,
            "cn_expr_pearson_r": None,
            "cn_expr_pearson_p": None,
            "cn_expr_slope_log2tpm_per_cn": None,
            "relative_cn_iqr": None,
            "relative_cn_p10_p90_spread": None,
            "log2tpm_iqr": None,
            "median_relative_cn": None,
            "median_log2tpm": None,
            "n_amplified": 0,
            "mean_log2tpm_amplified": None,
            "mean_log2tpm_neutral": None,
            "delta_log2tpm_amplified_vs_neutral": None,
            "amplification_threshold_relative_cn": float(amplification_threshold),
            "subset_delta_log2tpm_amplified_vs_neutral": None,  # median-based (the focal-amp subset driver)
            "subset_mannwhitney_p": None,
            "cis_dosage_driver": None,  # pan_panel_correlation | focal_amplification_subset
            "cis_dosage_class": cls,
        }
        out.update(extra)
        return out

    if n < min_cell_lines:
        # Too few jointly-measured lines to estimate a cis-dosage correlation honestly.
        return _base("data_unavailable")

    cn = np.array([cn_by_model[m] for m in evaluated], dtype=float)
    tpm = np.array([tpm_by_model[m] for m in evaluated], dtype=float)

    cn_q25, cn_q75 = np.quantile(cn, [0.25, 0.75])
    cn_p10, cn_p90 = np.quantile(cn, [0.10, 0.90])
    tpm_q25, tpm_q75 = np.quantile(tpm, [0.25, 0.75])
    cn_iqr = float(cn_q75 - cn_q25)  # provenance only (NOT the invariant gate)
    cn_p10_p90 = float(cn_p90 - cn_p10)  # the tail-sensitive spread the invariant gate uses
    tpm_iqr = float(tpm_q75 - tpm_q25)

    # Amplified-vs-neutral expression contrast (interpretability aid; not the class driver).
    amp_tpm = tpm[cn > amplification_threshold]
    neutral_tpm = tpm[cn <= amplification_threshold]
    n_amp = int(amp_tpm.size)
    mean_amp = float(amp_tpm.mean()) if amp_tpm.size else None
    mean_neutral = float(neutral_tpm.mean()) if neutral_tpm.size else None
    delta_amp = (mean_amp - mean_neutral) if (mean_amp is not None and mean_neutral is not None) else None

    common = dict(
        relative_cn_iqr=cn_iqr,
        relative_cn_p10_p90_spread=cn_p10_p90,
        log2tpm_iqr=tpm_iqr,
        median_relative_cn=float(np.median(cn)),
        median_log2tpm=float(np.median(tpm)),
        n_amplified=n_amp,
        mean_log2tpm_amplified=mean_amp,
        mean_log2tpm_neutral=mean_neutral,
        delta_log2tpm_amplified_vs_neutral=delta_amp,
    )

    # Untestable: no CN variation → the cis-dosage question cannot be asked (near-diploid panel).
    # Gated on the p90-p10 spread (tail-sensitive), NOT the IQR — else focal-amp oncogenes with a
    # bulk-diploid body + amplified tail (ERBB2/MYC) are wrongly called invariant. Distinct from
    # cn_dosage_uncoupled (measured CN variation, but no expression coupling).
    if cn_p10_p90 < min_cn_spread or cn.std() < 1e-9 or tpm.std() < 1e-9:
        return _base("cn_invariant_panel", **common)

    spearman_r, spearman_p = stats.spearmanr(cn, tpm)
    pearson_r, pearson_p = stats.pearsonr(cn, tpm)
    slope = float(np.polyfit(cn, tpm, deg=1)[0])

    # === PRIMARY: pan-panel Spearman (broadly copy-varying genes) ===
    driver = None
    if spearman_r >= strong_r and spearman_p <= significance_alpha:
        cls, driver = "cn_dosage_coupled_strong", "pan_panel_correlation"
    elif spearman_r >= moderate_r and spearman_p <= significance_alpha:
        cls, driver = "cn_dosage_coupled_moderate", "pan_panel_correlation"
    else:
        cls = "cn_dosage_uncoupled"

    # === FOCAL-AMPLIFICATION SUBSET escape (the tail the pan-panel Spearman dilutes) ===
    # Only ever PROMOTES an otherwise-uncoupled call: a focal-amp oncogene (bulk-diploid body + amplified
    # tail; ERBB2/MYC) whose amplified subset OVER-expresses strongly + significantly is cis-dosage-coupled
    # even when the panel-wide rank correlation is diluted below the moderate gate. Never demotes a
    # pan-panel-coupled call. Mirrors depmap_methylation_silencing's subset-primary design (one-sided
    # Mann-Whitney, amplified > neutral).
    subset_p = None
    subset_delta_med = None
    amp_mask = cn > amplification_threshold
    n_amp_lines = int(amp_mask.sum())
    n_neutral_lines = int((~amp_mask).sum())
    if (
        cls == "cn_dosage_uncoupled"
        and n_amp_lines >= MIN_AMPLIFIED_FOR_SUBSET
        and n_neutral_lines >= MIN_NEUTRAL_COMPARATOR
    ):
        amp_grp = tpm[amp_mask]
        neutral_grp = tpm[~amp_mask]
        try:
            _u, subset_p = stats.mannwhitneyu(amp_grp, neutral_grp, alternative="greater")
            subset_p = float(subset_p)
        except ValueError:
            subset_p = None
        subset_delta_med = float(np.median(amp_grp) - np.median(neutral_grp))
        if subset_p is not None and subset_p <= significance_alpha and subset_delta_med >= MODERATE_FOCAL_AMP_DELTA:
            cls = (
                "cn_dosage_coupled_strong"
                if subset_delta_med >= STRONG_FOCAL_AMP_DELTA
                else "cn_dosage_coupled_moderate"
            )
            driver = "focal_amplification_subset"

    return _base(
        cls,
        cn_expr_spearman_r=float(spearman_r),
        cn_expr_spearman_p=float(spearman_p),
        cn_expr_pearson_r=float(pearson_r),
        cn_expr_pearson_p=float(pearson_p),
        cn_expr_slope_log2tpm_per_cn=slope,
        subset_delta_log2tpm_amplified_vs_neutral=subset_delta_med,
        subset_mannwhitney_p=subset_p,
        cis_dosage_driver=driver,
        **common,
    )
