#!/usr/bin/env python3
"""depmap_cn_dependency CLI — copy-number-stratified dependency compute.

Single amplified-vs-neutral Mann-Whitney contrast on Chronos (the CN analog of
depmap_mutation_dependency's hotspot/damaging tiers, but one CN vector → no multi-tier
BH correction). Reuses the PROVEN _mannwhitney_stratification from depmap_mutation_dependency
verbatim, so the statistics are identical to the mutation path.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

METHOD_VERSION = "0.1.0"

# DepMap-side focal-amplification convention (relative CN, diploid ≈ 1.0; NOT log2).
# Reused from depmap_cn_distribution.cli (FOCAL_AMP). A line is "amplified" when its
# relative CN exceeds this; the neutral comparator is everything NOT amplified (broad
# mirror of the mutation path's WT = "everything not mutant" — sign-off 2026-08-06).
FOCAL_AMP = 1.5

# Classification thresholds — mirror depmap_mutation_dependency exactly.
STRONG_EFFECT_DELTA = -0.5     # amplified median Chronos - neutral median <= -0.5 → strongly dependent
MODERATE_EFFECT_DELTA = -0.2
STRATIFICATION_ALPHA = 0.05
MIN_AMPLIFIED_CELLS = 5        # mirror min_mutant
MIN_NEUTRAL_CELLS = 30         # mirror min_wildtype
WT_INVERSE_DELTA = 0.3         # positive delta with significance → neutral lines more dependent


def compute_cn_stratification(chronos_by_model: dict, cn_by_model: dict,
                              focal_amp: float = FOCAL_AMP,
                              strong_effect_delta: float = STRONG_EFFECT_DELTA,
                              moderate_effect_delta: float = MODERATE_EFFECT_DELTA,
                              stratification_alpha: float = STRATIFICATION_ALPHA,
                              min_amplified: int = MIN_AMPLIFIED_CELLS,
                              min_neutral: int = MIN_NEUTRAL_CELLS) -> dict:
    """Compute the copy-number-stratified-dependency summary_fields.

    Builds an amplified boolean vector (relative CN > focal_amp) and runs the SAME
    Mann-Whitney contrast the mutation path uses (one-sided: amplified more dependent).
    Returns the card's summary_fields shape + cn_stratification_class.
    """
    # Reuse the proven contrast verbatim (substrate-agnostic: chronos + {ModelID -> bool}).
    METHODS_REPO = Path(__file__).resolve().parent.parent.parent
    if str(METHODS_REPO) not in sys.path:
        sys.path.insert(0, str(METHODS_REPO))
    from methods.depmap_mutation_dependency.cli import _mannwhitney_stratification

    # amplified boolean per line; neutral = NOT amplified (broad comparator).
    amp_by_model = {m: (cn > focal_amp) for m, cn in cn_by_model.items()}

    res = _mannwhitney_stratification(
        chronos_by_model, amp_by_model,
        min_mutant=min_amplified, min_wildtype=min_neutral,
    )

    # Single test → q == p (no multi-tier BH; the mutation path only BH-corrects across its
    # 3 tiers). Fill q from p so the classifier (which gates on q) works identically.
    q = res.get("p_value")
    delta = res.get("delta_mut_vs_wt")

    def _classify() -> str:
        if res.get("_insufficient_data"):
            return "insufficient_amplification_rate"
        if q is None or delta is None or q >= stratification_alpha:
            return "not_cn_stratified"
        if delta <= strong_effect_delta:
            return "amplified_strongly_dependent"
        if delta <= moderate_effect_delta:
            return "amplified_moderately_dependent"
        if delta >= WT_INVERSE_DELTA:
            return "neutral_strongly_dependent"
        return "not_cn_stratified"

    cls = _classify()
    n_evaluated = len(set(chronos_by_model) & set(cn_by_model))

    return {
        "n_cell_lines_evaluated": int(n_evaluated),
        "n_amplified": res["n_mutant"],
        "n_neutral": res["n_wildtype"],
        "median_chronos_amplified": res["median_mutant"],
        "median_chronos_neutral": res["median_wildtype"],
        "delta_chronos_amplified_vs_neutral": delta,
        "cn_stratification_mannwhitney_p": res.get("p_value"),
        "cn_stratification_mannwhitney_q": q,
        "cn_stratification_effect_size": res.get("effect_size"),
        "amplification_threshold_relative_cn": float(focal_amp),
        "cn_stratification_class": cls,
    }
