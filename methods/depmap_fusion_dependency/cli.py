#!/usr/bin/env python3
"""depmap_fusion_dependency CLI — fusion-stratified dependency compute.

Builds a fusion-positive-vs-negative boolean (the target appears as either the 5' or 3' partner in a
high-confidence DepMap fusion call for a line) and runs the shared single-boolean Mann-Whitney
stratified-dependency contrast (methods.depmap_common.boolean_stratification), so the statistic and
tiering are identical to the CN / amp-expr siblings and the mutation path. The boolean is built in
read.py from OmicsFusionFiltered.csv and passed in; this module is pure compute + classification.
"""

from __future__ import annotations

from methods.depmap_common.boolean_stratification import (
    StratificationLabels,
    mannwhitney_stratification,
    classify_stratification,
    STRONG_EFFECT_DELTA,
    MODERATE_EFFECT_DELTA,
    STRATIFICATION_ALPHA,
    MIN_POSITIVE_CELLS,
    MIN_COMPARATOR_CELLS,
)

METHOD_VERSION = "0.1.0"

_LABELS = StratificationLabels(
    strong="fusion_positive_strongly_dependent",
    moderate="fusion_positive_moderately_dependent",
    reverse_strong="fusion_negative_strongly_dependent",
    not_stratified="not_fusion_stratified",
    insufficient="insufficient_fusion_rate",
)


def compute_fusion_stratification(
    chronos_by_model: dict,
    fusion_by_model: dict,
    strong_effect_delta: float = STRONG_EFFECT_DELTA,
    moderate_effect_delta: float = MODERATE_EFFECT_DELTA,
    stratification_alpha: float = STRATIFICATION_ALPHA,
    min_positive: int = MIN_POSITIVE_CELLS,
    min_negative: int = MIN_COMPARATOR_CELLS,
) -> dict:
    """Compute the fusion-stratified-dependency summary_fields.

    `fusion_by_model` is {ModelID -> bool} over the fusion-profiled universe (True = a high-confidence
    fusion INVOLVING the target, either partner). Comparator = every other fusion-profiled line.
    """
    res = mannwhitney_stratification(
        chronos_by_model, fusion_by_model, min_positive=min_positive, min_comparator=min_negative
    )
    cls = classify_stratification(
        res,
        _LABELS,
        strong_effect_delta=strong_effect_delta,
        moderate_effect_delta=moderate_effect_delta,
        stratification_alpha=stratification_alpha,
    )
    q = res.get("p_value")  # single boolean -> single test -> q == p
    n_evaluated = len(set(chronos_by_model) & set(fusion_by_model))
    return {
        "n_cell_lines_evaluated": int(n_evaluated),
        "n_fusion_positive": res["n_mutant"],
        "n_fusion_negative": res["n_wildtype"],
        "median_chronos_fusion_positive": res["median_mutant"],
        "median_chronos_fusion_negative": res["median_wildtype"],
        "delta_chronos_fusion_positive_vs_negative": res.get("delta_mut_vs_wt"),
        "fusion_stratification_mannwhitney_p": res.get("p_value"),
        "fusion_stratification_mannwhitney_q": q,
        "fusion_stratification_mannwhitney_q_reverse": res.get("p_value_reverse"),
        "fusion_stratification_effect_size": res.get("effect_size"),
        "fusion_stratification_class": cls,
        "_uncomputable": bool(res.get("_uncomputable")),
    }
