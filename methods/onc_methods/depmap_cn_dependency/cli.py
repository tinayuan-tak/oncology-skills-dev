#!/usr/bin/env python3
"""depmap_cn_dependency CLI — copy-number-stratified dependency compute.

Builds an amplified-vs-neutral boolean (relative CN > focal cut) and runs the shared single-boolean
Mann-Whitney stratified-dependency contrast (methods.depmap_common.boolean_stratification), so the
statistic and the strong/moderate/reverse tiering are identical to the fusion / amp-expr siblings and
the mutation path. This module owns only the CN-specific boolean and output field names.
"""

from __future__ import annotations

from onc_methods.depmap_common.boolean_stratification import (
    MIN_COMPARATOR_CELLS,
    MIN_POSITIVE_CELLS,
    MODERATE_EFFECT_DELTA,
    STRATIFICATION_ALPHA,
    STRONG_EFFECT_DELTA,
    StratificationLabels,
    classify_stratification,
    mannwhitney_stratification,
)

METHOD_VERSION = "0.1.0"

# DepMap relative CN (diploid ~ 1.0; ploidy-relative, NOT raw copies, NOT log2). The dependency
# amplified-arm uses a FOCAL HIGH-LEVEL cut (>= ~2x ploidy baseline), not a shallow arm-level gain:
# empirically (ERBB2, 26Q1) >2.0 flags 46 lines vs 95 at >1.5, and the extra 49 shallow gains dilute
# the amplification-addiction signal. The patient path is already GISTIC-focal-only; this matches it.
FOCAL_AMP_HIGH = 2.0

_LABELS = StratificationLabels(
    strong="amplified_strongly_dependent",
    moderate="amplified_moderately_dependent",
    reverse_strong="neutral_strongly_dependent",
    not_stratified="not_cn_stratified",
    insufficient="insufficient_amplification_rate",
)


def compute_cn_stratification(
    chronos_by_model: dict,
    cn_by_model: dict,
    focal_amp: float = FOCAL_AMP_HIGH,
    strong_effect_delta: float = STRONG_EFFECT_DELTA,
    moderate_effect_delta: float = MODERATE_EFFECT_DELTA,
    stratification_alpha: float = STRATIFICATION_ALPHA,
    min_amplified: int = MIN_POSITIVE_CELLS,
    min_neutral: int = MIN_COMPARATOR_CELLS,
) -> dict:
    """Compute the copy-number-stratified-dependency summary_fields.

    Amplified boolean = relative CN > focal_amp; neutral = every other line (broad comparator).
    """
    amp_by_model = {m: (cn > focal_amp) for m, cn in cn_by_model.items()}
    res = mannwhitney_stratification(
        chronos_by_model, amp_by_model, min_positive=min_amplified, min_comparator=min_neutral
    )
    cls = classify_stratification(
        res,
        _LABELS,
        strong_effect_delta=strong_effect_delta,
        moderate_effect_delta=moderate_effect_delta,
        stratification_alpha=stratification_alpha,
    )
    q = res.get("p_value")  # single boolean -> single test -> q == p
    n_evaluated = len(set(chronos_by_model) & set(cn_by_model))
    return {
        "n_cell_lines_evaluated": int(n_evaluated),
        "n_amplified": res["n_mutant"],
        "n_neutral": res["n_wildtype"],
        "median_chronos_amplified": res["median_mutant"],
        "median_chronos_neutral": res["median_wildtype"],
        "delta_chronos_amplified_vs_neutral": res.get("delta_mut_vs_wt"),
        "cn_stratification_mannwhitney_p": res.get("p_value"),
        "cn_stratification_mannwhitney_q": q,
        "cn_stratification_mannwhitney_q_reverse": res.get("p_value_reverse"),
        "cn_stratification_effect_size": res.get("effect_size"),
        "amplification_threshold_relative_cn": float(focal_amp),
        "cn_stratification_class": cls,
        "_uncomputable": bool(res.get("_uncomputable")),
    }
