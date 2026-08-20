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
STRONG_DOSAGE_SPEARMAN_R = 0.4        # cn_dosage_coupled_strong
MODERATE_DOSAGE_SPEARMAN_R = 0.25     # cn_dosage_coupled_moderate
SIGNIFICANCE_ALPHA = 0.01
MIN_CELL_LINES_FOR_CORRELATION = 50
MIN_RELATIVE_CN_IQR = 0.2             # CN-variance floor; below → cn_invariant_panel (untestable)
# Focal-amplification convention (relative CN, diploid ~ 1.0; NOT log2). 1.5 = the distribution card's
# focal-amp bin edge (depmap_cn_distribution.FOCAL_AMP), used ONLY for the descriptive amplified-vs-
# neutral expression contrast — NOT the class driver (the class is driven by the correlation).
AMPLIFICATION_THRESHOLD = 1.5


def compute_cis_dosage(cn_by_model: dict, tpm_by_model: dict,
                       strong_r: float = STRONG_DOSAGE_SPEARMAN_R,
                       moderate_r: float = MODERATE_DOSAGE_SPEARMAN_R,
                       significance_alpha: float = SIGNIFICANCE_ALPHA,
                       min_cell_lines: int = MIN_CELL_LINES_FOR_CORRELATION,
                       min_cn_iqr: float = MIN_RELATIVE_CN_IQR,
                       amplification_threshold: float = AMPLIFICATION_THRESHOLD) -> dict:
    """Compute the cis-feature-expression-coherence summary_fields.

    Evaluated universe = lines with BOTH relative CN AND log2TPM present. cis_dosage_class is driven by
    the CN↔expression Spearman correlation; a near-diploid panel (CN IQR < min) is cn_invariant_panel
    (untestable), NOT cn_dosage_uncoupled. Higher CN → higher expression = POSITIVE r = coupled.
    """
    import numpy as np
    from scipy import stats

    evaluated = sorted(set(cn_by_model) & set(tpm_by_model))
    n = len(evaluated)

    def _base(cls: str, **extra) -> dict:
        out = {
            "n_cell_lines_evaluated": n,
            "cn_expr_spearman_r": None, "cn_expr_spearman_p": None,
            "cn_expr_pearson_r": None, "cn_expr_pearson_p": None,
            "cn_expr_slope_log2tpm_per_cn": None,
            "relative_cn_iqr": None, "log2tpm_iqr": None,
            "median_relative_cn": None, "median_log2tpm": None,
            "n_amplified": 0, "mean_log2tpm_amplified": None, "mean_log2tpm_neutral": None,
            "delta_log2tpm_amplified_vs_neutral": None,
            "amplification_threshold_relative_cn": float(amplification_threshold),
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
    tpm_q25, tpm_q75 = np.quantile(tpm, [0.25, 0.75])
    cn_iqr = float(cn_q75 - cn_q25)
    tpm_iqr = float(tpm_q75 - tpm_q25)

    # Amplified-vs-neutral expression contrast (interpretability aid; not the class driver).
    amp_tpm = tpm[cn > amplification_threshold]
    neutral_tpm = tpm[cn <= amplification_threshold]
    n_amp = int(amp_tpm.size)
    mean_amp = float(amp_tpm.mean()) if amp_tpm.size else None
    mean_neutral = float(neutral_tpm.mean()) if neutral_tpm.size else None
    delta_amp = (mean_amp - mean_neutral) if (mean_amp is not None and mean_neutral is not None) else None

    common = dict(
        relative_cn_iqr=cn_iqr, log2tpm_iqr=tpm_iqr,
        median_relative_cn=float(np.median(cn)), median_log2tpm=float(np.median(tpm)),
        n_amplified=n_amp, mean_log2tpm_amplified=mean_amp, mean_log2tpm_neutral=mean_neutral,
        delta_log2tpm_amplified_vs_neutral=delta_amp,
    )

    # Untestable: no CN variance → the cis-dosage question cannot be asked (near-diploid panel).
    # Distinct from cn_dosage_uncoupled (measured CN variance, but no expression coupling).
    if cn_iqr < min_cn_iqr or cn.std() < 1e-9 or tpm.std() < 1e-9:
        return _base("cn_invariant_panel", **common)

    spearman_r, spearman_p = stats.spearmanr(cn, tpm)
    pearson_r, pearson_p = stats.pearsonr(cn, tpm)
    slope = float(np.polyfit(cn, tpm, deg=1)[0])

    if spearman_r >= strong_r and spearman_p <= significance_alpha:
        cls = "cn_dosage_coupled_strong"
    elif spearman_r >= moderate_r and spearman_p <= significance_alpha:
        cls = "cn_dosage_coupled_moderate"
    else:
        cls = "cn_dosage_uncoupled"

    return _base(
        cls,
        cn_expr_spearman_r=float(spearman_r), cn_expr_spearman_p=float(spearman_p),
        cn_expr_pearson_r=float(pearson_r), cn_expr_pearson_p=float(pearson_p),
        cn_expr_slope_log2tpm_per_cn=slope,
        **common,
    )
