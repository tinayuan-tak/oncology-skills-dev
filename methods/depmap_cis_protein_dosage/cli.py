#!/usr/bin/env python3
"""depmap_cis_protein_dosage CLI — cis-feature → own-PROTEIN dosage coupling compute.

Computes the cross-cell-line correlation between target T's OWN relative copy-number and its OWN
Gygi-MS log2 protein abundance across the DepMap panel (protein cis-dosage), classifies the coupling,
and reports an amplified-vs-neutral abundance contrast for interpretability. Pure compute over two
loaded {ModelID -> value} dicts; the statistic (Spearman primary, robust to CN outliers; Pearson
reported) mirrors depmap_cis_dosage.compute_cis_dosage exactly, swapping log2TPM -> log2 protein.

This module owns only the CN↔protein correlation, the coupling classification, and the output field
names. It reads NO Chronos — protein → dependency (leg-b) is owned by the reused abundance-dependency card.
"""

from __future__ import annotations

METHOD_VERSION = "0.1.0"

# --- classification thresholds (mirror cards/cis-feature-protein-coherence.card.yaml) ---
# Kept identical to the mRNA sibling (depmap_cis_dosage) so the two legs are directly comparable and the
# slope ratio is interpreted on a like-for-like classification.
STRONG_DOSAGE_SPEARMAN_R = 0.4  # prot_dosage_coupled_strong
MODERATE_DOSAGE_SPEARMAN_R = 0.25  # prot_dosage_coupled_moderate
SIGNIFICANCE_ALPHA = 0.01
# Protein detection is sparser than mRNA (Gygi ~375 lines, per-protein detection drops further), so the
# jointly-measured CN∩protein universe is smaller than CN∩TPM — a lower floor than the mRNA leg's 50.
MIN_CELL_LINES_FOR_CORRELATION = 30
# CN-variance floor → below this the panel is near-diploid = untestable (cn_invariant_panel). Keyed on
# the p90-p10 spread, NOT the IQR: focal-amplification oncogenes (ERBB2/MYC) are bulk-diploid with an
# amplified TAIL, so their IQR (middle 50%) is ~0 even though the tail carries real rank-correlation
# signal (same calibration finding as the mRNA leg, 2026-08-20).
MIN_RELATIVE_CN_P10_P90_SPREAD = 0.2
# Focal-amplification convention (relative CN, diploid ~ 1.0; NOT log2). 1.5 = the distribution card's
# focal-amp bin edge, used ONLY for the descriptive amplified-vs-neutral abundance contrast — NOT the
# class driver (the class is driven by the correlation).
AMPLIFICATION_THRESHOLD = 1.5


def compute_cis_protein_dosage(
    cn_by_model: dict,
    prot_by_model: dict,
    strong_r: float = STRONG_DOSAGE_SPEARMAN_R,
    moderate_r: float = MODERATE_DOSAGE_SPEARMAN_R,
    significance_alpha: float = SIGNIFICANCE_ALPHA,
    min_cell_lines: int = MIN_CELL_LINES_FOR_CORRELATION,
    min_cn_spread: float = MIN_RELATIVE_CN_P10_P90_SPREAD,
    amplification_threshold: float = AMPLIFICATION_THRESHOLD,
) -> dict:
    """Compute the cis-feature-protein-coherence summary_fields.

    Evaluated universe = lines with BOTH relative CN AND Gygi protein abundance present.
    cis_protein_dosage_class is driven by the CN↔protein Spearman correlation; a near-diploid panel
    (CN p90-p10 spread < min) is cn_invariant_panel (untestable), NOT prot_dosage_uncoupled. Higher CN →
    higher protein = POSITIVE r = coupled. The invariant gate keys on the p90-p10 spread (tail-sensitive),
    NOT the IQR, so focal-amplification oncogenes (bulk-diploid + amplified tail; ERBB2/MYC) stay testable.
    """
    import numpy as np
    from scipy import stats

    evaluated = sorted(set(cn_by_model) & set(prot_by_model))
    n = len(evaluated)

    def _base(cls: str, **extra) -> dict:
        out = {
            "n_paired_models_cn_protein": n,
            "cn_prot_spearman_r": None,
            "cn_prot_spearman_p": None,
            "cn_prot_pearson_r": None,
            "cn_prot_pearson_p": None,
            "cn_prot_slope_log2abundance_per_cn": None,
            "relative_cn_iqr": None,
            "relative_cn_p10_p90_spread": None,
            "log2abundance_iqr": None,
            "median_relative_cn": None,
            "median_log2abundance": None,
            "n_amplified": 0,
            "mean_log2abundance_amplified": None,
            "mean_log2abundance_neutral": None,
            "delta_log2abundance_amplified_vs_neutral": None,
            "amplification_threshold_relative_cn": float(amplification_threshold),
            "cis_protein_dosage_class": cls,
        }
        out.update(extra)
        return out

    if n < min_cell_lines:
        # Too few jointly-measured lines (or the target is undetected in Gygi) to estimate a
        # protein cis-dosage correlation honestly.
        return _base("data_unavailable")

    cn = np.array([cn_by_model[m] for m in evaluated], dtype=float)
    prot = np.array([prot_by_model[m] for m in evaluated], dtype=float)

    cn_q25, cn_q75 = np.quantile(cn, [0.25, 0.75])
    cn_p10, cn_p90 = np.quantile(cn, [0.10, 0.90])
    prot_q25, prot_q75 = np.quantile(prot, [0.25, 0.75])
    cn_iqr = float(cn_q75 - cn_q25)  # provenance only (NOT the invariant gate)
    cn_p10_p90 = float(cn_p90 - cn_p10)  # the tail-sensitive spread the invariant gate uses
    prot_iqr = float(prot_q75 - prot_q25)

    # Amplified-vs-neutral abundance contrast (interpretability aid; not the class driver).
    amp_prot = prot[cn > amplification_threshold]
    neutral_prot = prot[cn <= amplification_threshold]
    n_amp = int(amp_prot.size)
    mean_amp = float(amp_prot.mean()) if amp_prot.size else None
    mean_neutral = float(neutral_prot.mean()) if neutral_prot.size else None
    delta_amp = (mean_amp - mean_neutral) if (mean_amp is not None and mean_neutral is not None) else None

    common = dict(
        relative_cn_iqr=cn_iqr,
        relative_cn_p10_p90_spread=cn_p10_p90,
        log2abundance_iqr=prot_iqr,
        median_relative_cn=float(np.median(cn)),
        median_log2abundance=float(np.median(prot)),
        n_amplified=n_amp,
        mean_log2abundance_amplified=mean_amp,
        mean_log2abundance_neutral=mean_neutral,
        delta_log2abundance_amplified_vs_neutral=delta_amp,
    )

    # Untestable: no CN variation → the cis-dosage question cannot be asked (near-diploid panel).
    # Gated on the p90-p10 spread (tail-sensitive), NOT the IQR — else focal-amp oncogenes with a
    # bulk-diploid body + amplified tail (ERBB2/MYC) are wrongly called invariant. Distinct from
    # prot_dosage_uncoupled (measured CN variation, but no protein coupling → dosage-buffered).
    if cn_p10_p90 < min_cn_spread or cn.std() < 1e-9 or prot.std() < 1e-9:
        return _base("cn_invariant_panel", **common)

    spearman_r, spearman_p = stats.spearmanr(cn, prot)
    pearson_r, pearson_p = stats.pearsonr(cn, prot)
    slope = float(np.polyfit(cn, prot, deg=1)[0])

    if spearman_r >= strong_r and spearman_p <= significance_alpha:
        cls = "prot_dosage_coupled_strong"
    elif spearman_r >= moderate_r and spearman_p <= significance_alpha:
        cls = "prot_dosage_coupled_moderate"
    else:
        # Measured CN variation but no protein coupling: the amplification does NOT raise protein =
        # post-transcriptionally dosage-BUFFERED (the informative negative for a cis-driver claim).
        cls = "prot_dosage_uncoupled"

    return _base(
        cls,
        cn_prot_spearman_r=float(spearman_r),
        cn_prot_spearman_p=float(spearman_p),
        cn_prot_pearson_r=float(pearson_r),
        cn_prot_pearson_p=float(pearson_p),
        cn_prot_slope_log2abundance_per_cn=slope,
        **common,
    )
