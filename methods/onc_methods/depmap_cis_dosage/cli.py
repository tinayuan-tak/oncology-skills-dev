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

METHOD_VERSION = "0.2.0"

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

# --- LINEAGE-CONFOUND control on the subset contrast (round-2 panel calibration 2026-09-12) -----------
# The focal-amp subset contrast is an UNSTRATIFIED pan-panel group comparison, so for a LINEAGE-RESTRICTED
# gene the "amplified" group is lineage-ENRICHED and the neutral comparator includes lineages that do not
# express the gene at all — the group delta then measures lineage, not cis-dosage. Round-2 panel evidence
# (median log2TPM amplified-vs-neutral, pan-panel → pooled WITHIN-lineage):
#   CDH1   +3.26 → -0.70  (sign FLIPS; the 56 CN-gained lines are epithelial, the comparator is not)
#   PAX8   +2.02 → +0.77  (collapses below the moderate gate)
#   ERBB2  +1.64 → +1.70  (SURVIVES — a genuine focal amplicon, not a lineage artifact)
#   FGFR2  +3.40 → +2.42  (survives)   MITF +3.65 → +2.30 (survives)   MYC +0.81 → +0.91 (survives)
# So the subset ESCAPE additionally requires the WITHIN-lineage delta to clear the same moderate gate.
# The control is only applied when lineage labels are supplied; without them the field is None and the
# escape behaves exactly as before (no silent behaviour change for callers that pass no lineage).
MIN_PER_LINEAGE_SIDE = 3  # a lineage contributes to the within-lineage pooling only with >=3 lines a side

# Deletion-side contrast (the DIRECTION leg, round-2 panel calibration 2026-09-12).
# cis_dosage_class answers "does own CN predict own expression"; it is DIRECTION-BLIND, and a deleted
# tumour suppressor satisfies it just as well as an amplified oncogene (less CN → less expression). The
# round-2 literature panel flagged this on 6/20 targets: BRCA1/APC/STK11/NF1/CDH1/RASSF1 all read
# "cn_dosage_coupled_*" while the literature calls them LOSS-of-function suppressors, and the downstream
# verdicts (coherent_cis_driver / expressed_cis_coupled_inert) frame the chain as a GAIN chain. So also
# run the deleted-vs-neutral contrast and record which arm carries the coupling:
#   CDKN2A  amp +1.46 / del -4.04 (within-lineage) → deletion_coupled     MET  amp +1.36 / del -0.33 → amplification_coupled
#   RASSF1  amp (n=16, no power) / del -0.59       → deletion_coupled     ERBB2 amp +1.70 / del -0.58 → amplification_coupled
DELETION_THRESHOLD = 0.75  # relative CN below this = deleted (mirrors depmap_cn_distribution's loss bin)
MIN_DELETED_FOR_SUBSET = 20  # min deleted lines to run the deletion-side contrast
# Which arm WINS when both are powered: evidence weight = |within-lineage delta| * sqrt(n_arm), i.e. the
# same effect x sqrt(n) scaling as the arms' own Mann-Whitney z. Neither term alone works, and the panel
# says so (within-lineage delta_amp / n_amp vs delta_del / n_del):
#   magnitude ALONE mislabels PTEN (+1.06 on 15 amplified vs -0.76 on 338 deleted -> "amplification")
#     and AURKA (+0.64 on 507 vs -0.92 on 25 -> "deletion"); n ALONE mislabels MITF (2.30x60 vs 0.70x369
#     -> "deletion") and coin-flips FOXA1 (143 vs 145).
#   |delta|*sqrt(n) gets all four right: PTEN/RB1/SMAD4/VHL/CDKN2A/APC/NF1/STK11/RASSF1 -> deletion;
#   AURKA/MITF/FOXA1/ERBB2/MET/EGFR/KRAS/MYC/CDK4/MCL1/FGFR2/PDGFRA/PAX8 -> amplification.
# Each arm must also clear MIN_ARM_DELTA_FOR_DIRECTION so a vacuous arm cannot win on n alone.
MIN_ARM_DELTA_FOR_DIRECTION = 0.25


def _within_lineage_delta(
    minority_vals, majority_vals, minority_lineages, majority_lineages, min_per_side: int = MIN_PER_LINEAGE_SIDE
):
    """Pooled WITHIN-lineage median delta (minority - majority), lineage-count-weighted.

    Only lineages carrying >= min_per_side lines on BOTH sides contribute — a lineage present on one
    side only is exactly the confound being controlled for, so it must not enter the estimate. Returns
    (delta, n_lineages_contributing, dominant_lineage_fraction_of_minority) or (None, 0, frac) when no
    lineage is jointly powered (the contrast is then wholly lineage-separated = uncontrollable).
    """
    from collections import defaultdict

    import numpy as np

    by_min, by_maj = defaultdict(list), defaultdict(list)
    for v, lin in zip(minority_vals, minority_lineages):
        by_min[lin].append(float(v))
    for v, lin in zip(majority_vals, majority_lineages):
        by_maj[lin].append(float(v))
    dom_frac = (max(len(v) for v in by_min.values()) / len(minority_vals)) if by_min else None
    deltas, weights = [], []
    for lin, vals in by_min.items():
        other = by_maj.get(lin, [])
        if len(vals) >= min_per_side and len(other) >= min_per_side:
            deltas.append(float(np.median(vals) - np.median(other)))
            weights.append(len(vals))
    if not deltas:
        return None, 0, dom_frac
    return float(np.average(deltas, weights=weights)), len(deltas), dom_frac


def compute_cis_dosage(
    cn_by_model: dict,
    tpm_by_model: dict,
    lineage_by_model: dict | None = None,
    strong_r: float = STRONG_DOSAGE_SPEARMAN_R,
    moderate_r: float = MODERATE_DOSAGE_SPEARMAN_R,
    significance_alpha: float = SIGNIFICANCE_ALPHA,
    min_cell_lines: int = MIN_CELL_LINES_FOR_CORRELATION,
    min_cn_spread: float = MIN_RELATIVE_CN_P10_P90_SPREAD,
    amplification_threshold: float = AMPLIFICATION_THRESHOLD,
    deletion_threshold: float = DELETION_THRESHOLD,
) -> dict:
    """Compute the cis-feature-expression-coherence summary_fields.

    Evaluated universe = lines with BOTH relative CN AND log2TPM present. cis_dosage_class is driven by
    the CN↔expression Spearman correlation; a near-diploid panel (CN p90-p10 spread < min) is
    cn_invariant_panel (untestable), NOT cn_dosage_uncoupled. Higher CN → higher expression = POSITIVE
    r = coupled. The invariant gate keys on the p90-p10 spread (tail-sensitive), NOT the IQR, so
    focal-amplification oncogenes (bulk-diploid + amplified tail; ERBB2/MYC) are correctly testable.

    `lineage_by_model` ({ModelID -> lineage}) is OPTIONAL and purely a CONTROL: when supplied, the
    focal-amplification subset escape must additionally clear the moderate gate WITHIN lineage, which
    removes lineage-restriction artefacts (CDH1's +3.26 pan delta is -0.70 within lineage). When it is
    absent the escape behaves exactly as before. cis_dosage_direction reports WHICH CN arm carries the
    coupling (amplification_coupled | deletion_coupled) — the class itself is direction-blind, so a
    deleted suppressor and an amplified oncogene are otherwise indistinguishable.
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
            # lineage-confound control on the subset contrast (None when no lineage labels supplied)
            "subset_within_lineage_delta_log2tpm": None,
            "subset_n_lineages_compared": None,
            "amplified_dominant_lineage_fraction": None,
            # DIRECTION of the coupling — which arm carries it (amplification_coupled | deletion_coupled).
            # None whenever the class is not coupled, or when neither arm is powered/measurable.
            "cis_dosage_direction": None,
            "cis_dosage_direction_basis": None,  # amplified_vs_deleted_contrast | cn_distribution_asymmetry
            "n_deleted": 0,
            "deleted_subset_delta_log2tpm": None,
            "deleted_within_lineage_delta_log2tpm": None,
            "deleted_subset_mannwhitney_p": None,
            "deletion_threshold_relative_cn": float(deletion_threshold),
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
    lineages = None
    if lineage_by_model:
        lineages = [str(lineage_by_model.get(m) or "unknown") for m in evaluated]

    amp_mask = cn > amplification_threshold
    del_mask = cn < deletion_threshold
    neutral_mask = ~amp_mask  # the escape's historic comparator (everything not amplified)
    mid_mask = neutral_mask & ~del_mask  # the deletion arm's comparator (neither deleted nor amplified)
    n_amp_lines = int(amp_mask.sum())
    n_neutral_lines = int(neutral_mask.sum())
    n_del_lines = int(del_mask.sum())
    n_mid_lines = int(mid_mask.sum())

    def _arm(minority_mask, majority_mask, alternative: str):
        """(median delta, one-sided MWU p, within-lineage delta, n_lineages, dominant lineage frac)."""
        a, b = tpm[minority_mask], tpm[majority_mask]
        delta = float(np.median(a) - np.median(b))
        try:
            _u, p = stats.mannwhitneyu(a, b, alternative=alternative)
            p = float(p)
        except ValueError:
            p = None
        within, n_lin, dom = None, None, None
        if lineages is not None:
            lin_a = [lin for lin, keep in zip(lineages, minority_mask) if keep]
            lin_b = [lin for lin, keep in zip(lineages, majority_mask) if keep]
            within, n_lin, dom = _within_lineage_delta(a, b, lin_a, lin_b)
        return delta, p, within, n_lin, dom

    # Amplification arm. Computed whenever powered (not only on the escape path): it is both the escape
    # driver AND the gain arm of cis_dosage_direction, so a pan-panel-coupled gene needs it too.
    subset_delta_med = subset_p = subset_within = subset_n_lin = dom_frac = None
    if n_amp_lines >= MIN_AMPLIFIED_FOR_SUBSET and n_neutral_lines >= MIN_NEUTRAL_COMPARATOR:
        subset_delta_med, subset_p, subset_within, subset_n_lin, dom_frac = _arm(amp_mask, neutral_mask, "greater")

    if (
        cls == "cn_dosage_uncoupled"
        and n_amp_lines >= MIN_AMPLIFIED_FOR_SUBSET
        and n_neutral_lines >= MIN_NEUTRAL_COMPARATOR
        and subset_p is not None
        and subset_p <= significance_alpha
        and subset_delta_med >= MODERATE_FOCAL_AMP_DELTA
    ):
        # LINEAGE CONTROL: the escape is a NARROWING guard, never a rescue — both the pan-panel and the
        # within-lineage delta must clear the gate, and the TIER reads the weaker (lineage-honest) of the
        # two. With no lineage labels the pan delta stands alone (unchanged legacy behaviour).
        effective = subset_delta_med if lineages is None else min(subset_delta_med, subset_within or -np.inf)
        if effective >= MODERATE_FOCAL_AMP_DELTA:
            cls = "cn_dosage_coupled_strong" if effective >= STRONG_FOCAL_AMP_DELTA else "cn_dosage_coupled_moderate"
            driver = "focal_amplification_subset"

    # Deletion arm (the DIRECTION leg): do deleted lines UNDER-express relative to the copy-neutral body?
    del_delta_med = del_p = del_within = None
    if n_del_lines >= MIN_DELETED_FOR_SUBSET and n_mid_lines >= MIN_NEUTRAL_COMPARATOR:
        del_delta_med, del_p, del_within, _dn, _dd = _arm(del_mask, mid_mask, "less")

    direction = direction_basis = None
    if cls in ("cn_dosage_coupled_strong", "cn_dosage_coupled_moderate"):
        amp_eff = subset_delta_med if (lineages is None or subset_within is None) else subset_within
        del_eff = del_delta_med if (lineages is None or del_within is None) else del_within
        # An arm counts only with the RIGHT SIGN (gain -> over-expression, loss -> under-expression) and
        # an effect above the noise floor; the winner is the larger |delta| * sqrt(n) evidence weight.
        amp_w = (
            amp_eff * (n_amp_lines**0.5) if (amp_eff is not None and amp_eff >= MIN_ARM_DELTA_FOR_DIRECTION) else None
        )
        del_w = (
            -del_eff * (n_del_lines**0.5) if (del_eff is not None and -del_eff >= MIN_ARM_DELTA_FOR_DIRECTION) else None
        )
        if amp_w is not None or del_w is not None:
            direction_basis = "amplified_vs_deleted_contrast"
            if amp_w is not None and del_w is not None:
                direction = "amplification_coupled" if amp_w >= del_w else "deletion_coupled"
            else:
                direction = "amplification_coupled" if amp_w is not None else "deletion_coupled"
        else:
            # Neither arm is powered/consistent (small panels; the TCGA GISTIC arm): fall back to which
            # CN tail carries the panel's variation, measured off the panel MEDIAN so the fallback is
            # scale-free (relative CN centred ~1.0, GISTIC scores centred ~0). A broadly-deleted
            # suppressor locus has the loss tail dominant, a focal-amp oncogene the gain tail. Weaker
            # evidence, hence the explicitly recorded basis.
            cn_med = float(np.median(cn))
            direction_basis = "cn_distribution_asymmetry"
            direction = "amplification_coupled" if (cn_p90 - cn_med) >= (cn_med - cn_p10) else "deletion_coupled"

    return _base(
        cls,
        cn_expr_spearman_r=float(spearman_r),
        cn_expr_spearman_p=float(spearman_p),
        cn_expr_pearson_r=float(pearson_r),
        cn_expr_pearson_p=float(pearson_p),
        cn_expr_slope_log2tpm_per_cn=slope,
        subset_delta_log2tpm_amplified_vs_neutral=subset_delta_med,
        subset_mannwhitney_p=subset_p,
        subset_within_lineage_delta_log2tpm=subset_within,
        subset_n_lineages_compared=subset_n_lin,
        amplified_dominant_lineage_fraction=dom_frac,
        cis_dosage_direction=direction,
        cis_dosage_direction_basis=direction_basis,
        n_deleted=n_del_lines,
        deleted_subset_delta_log2tpm=del_delta_med,
        deleted_within_lineage_delta_log2tpm=del_within,
        deleted_subset_mannwhitney_p=del_p,
        cis_dosage_driver=driver,
        **common,
    )
