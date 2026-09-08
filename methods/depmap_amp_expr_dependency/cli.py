#!/usr/bin/env python3
"""depmap_amp_expr_dependency CLI — amplification+overexpression conjoint-stratified dependency compute.

Builds a conjoint-vs-rest boolean — amplified (CN > focal cut) AND high-expression (top within-panel
TPM tertile) — and runs the shared single-boolean Mann-Whitney stratified-dependency contrast
(methods.depmap_common.boolean_stratification), so the statistic and tiering are identical to the CN /
fusion siblings and the mutation path. This module owns only the conjoint boolean, the within-panel
high-expression cutoff, and the output field names.
"""

from __future__ import annotations

from methods.depmap_common.boolean_stratification import (
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

# Focal-amplification convention (relative CN, diploid ~ 1.0; NOT log2). The amplified component of the
# conjoint uses the FOCAL HIGH-LEVEL cut (matching depmap_cn_dependency.FOCAL_AMP_HIGH), so the conjoint
# reflects focal amplification-driven overexpression, not a shallow arm-level gain that happens to be
# high-expression.
# Named FOCAL_AMP_HIGH (not FOCAL_AMP) to match depmap_cn_dependency's identical 2.0 cutoff and to
# avoid colliding with depmap_cn_distribution.FOCAL_AMP, which is a DIFFERENT value (1.5, the
# distribution card's focal-amp bin edge) — same word, different threshold.
FOCAL_AMP_HIGH = 2.0
# High-expression cut: top within-panel tertile of log2TPM among EVALUATED lines (target-relative, no
# external percentile product needed — adapts per target, mirrors the CN method's self-contained cutoff).
HIGH_EXPR_TERTILE = 2.0 / 3.0

_LABELS = StratificationLabels(
    strong="amplified_overexpressed_strongly_dependent",
    moderate="amplified_overexpressed_moderately_dependent",
    reverse_strong="amp_expr_negative_more_dependent",
    not_stratified="not_amp_expr_stratified",
    insufficient="insufficient_amp_expr_rate",
)


def _high_expression_threshold(tpm_by_model: dict, evaluated: set) -> float | None:
    """Top-tertile log2TPM cutoff among the EVALUATED lines (those with Chronos+CN+TPM all present).

    Returns the value at the 2/3 quantile; None if too few evaluated lines to define a tertile.
    """
    vals = sorted(tpm_by_model[m] for m in evaluated if m in tpm_by_model)
    if len(vals) < 3:
        return None
    # index at the 2/3 position (inclusive floor) — everything strictly above is "high".
    idx = int(len(vals) * HIGH_EXPR_TERTILE)
    idx = min(idx, len(vals) - 1)
    return vals[idx]


def compute_amp_expr_stratification(
    chronos_by_model: dict,
    cn_by_model: dict,
    tpm_by_model: dict,
    focal_amp: float = FOCAL_AMP_HIGH,
    strong_effect_delta: float = STRONG_EFFECT_DELTA,
    moderate_effect_delta: float = MODERATE_EFFECT_DELTA,
    stratification_alpha: float = STRATIFICATION_ALPHA,
    min_conjoint: int = MIN_POSITIVE_CELLS,
    min_comparator: int = MIN_COMPARATOR_CELLS,
) -> dict:
    """Compute the amp-expr-stratified-dependency summary_fields.

    Positive arm = amplified (CN > focal_amp) AND high-expression (TPM > top-tertile cut among evaluated
    lines). Comparator = every other evaluated line. Evaluated universe = lines with Chronos AND CN AND TPM.
    """
    evaluated = set(chronos_by_model) & set(cn_by_model) & set(tpm_by_model)

    high_expr_cut = _high_expression_threshold(tpm_by_model, evaluated)
    if high_expr_cut is None:
        return {
            "n_cell_lines_evaluated": len(evaluated),
            "n_amplified_overexpressed": 0,
            "n_comparator": 0,
            "median_chronos_amp_expr": None,
            "median_chronos_comparator": None,
            "delta_chronos_amp_expr_vs_rest": None,
            "amp_expr_mannwhitney_p": None,
            "amp_expr_mannwhitney_q": None,
            "amp_expr_effect_size": None,
            "amplification_threshold_relative_cn": float(focal_amp),
            "high_expression_log2tpm_threshold": None,
            "amp_expr_stratification_class": _LABELS.insufficient,
        }

    conjoint_by_model = {m: (cn_by_model[m] > focal_amp and tpm_by_model[m] > high_expr_cut) for m in evaluated}
    res = mannwhitney_stratification(
        chronos_by_model, conjoint_by_model, min_positive=min_conjoint, min_comparator=min_comparator
    )
    cls = classify_stratification(
        res,
        _LABELS,
        strong_effect_delta=strong_effect_delta,
        moderate_effect_delta=moderate_effect_delta,
        stratification_alpha=stratification_alpha,
    )
    q = res.get("p_value")  # single boolean -> single test -> q == p
    return {
        "n_cell_lines_evaluated": len(evaluated),
        "n_amplified_overexpressed": res["n_mutant"],
        "n_comparator": res["n_wildtype"],
        "median_chronos_amp_expr": res["median_mutant"],
        "median_chronos_comparator": res["median_wildtype"],
        "delta_chronos_amp_expr_vs_rest": res.get("delta_mut_vs_wt"),
        "amp_expr_mannwhitney_p": res.get("p_value"),
        "amp_expr_mannwhitney_q": q,
        "amp_expr_mannwhitney_q_reverse": res.get("p_value_reverse"),
        "amp_expr_effect_size": res.get("effect_size"),
        "amplification_threshold_relative_cn": float(focal_amp),
        "high_expression_log2tpm_threshold": float(high_expr_cut),
        "amp_expr_stratification_class": cls,
        "_uncomputable": bool(res.get("_uncomputable")),
    }
