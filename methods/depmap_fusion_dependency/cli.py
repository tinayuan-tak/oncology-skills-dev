#!/usr/bin/env python3
"""depmap_fusion_dependency CLI — fusion-stratified dependency compute.

Single fusion-positive-vs-negative Mann-Whitney contrast on Chronos (the FUSION analog of
depmap_cn_dependency: one boolean vector → no multi-tier BH correction). Reuses the PROVEN
_mannwhitney_stratification from depmap_mutation_dependency verbatim, so the statistics are
identical to the mutation / CN paths.

The fusion-involvement boolean (whether the target appears as either the 5' or 3' partner in
any high-confidence DepMap fusion call for a line) is built in read.py from OmicsFusionFiltered.csv
and passed in here; this module is pure compute + classification (mirrors depmap_cn_dependency/cli.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

METHOD_VERSION = "0.1.0"

# Classification thresholds — mirror depmap_cn_dependency / depmap_mutation_dependency exactly.
STRONG_EFFECT_DELTA = -0.5     # fusion-positive median Chronos - negative median <= -0.5 → strongly dependent
MODERATE_EFFECT_DELTA = -0.2
STRATIFICATION_ALPHA = 0.05
MIN_POSITIVE_CELLS = 5         # mirror min_mutant / min_amplified
MIN_NEGATIVE_CELLS = 30        # mirror min_wildtype / min_neutral
WT_INVERSE_DELTA = 0.3         # positive delta with significance → fusion-negative lines more dependent


def compute_fusion_stratification(chronos_by_model: dict, fusion_by_model: dict,
                                  strong_effect_delta: float = STRONG_EFFECT_DELTA,
                                  moderate_effect_delta: float = MODERATE_EFFECT_DELTA,
                                  stratification_alpha: float = STRATIFICATION_ALPHA,
                                  min_positive: int = MIN_POSITIVE_CELLS,
                                  min_negative: int = MIN_NEGATIVE_CELLS) -> dict:
    """Compute the fusion-stratified-dependency summary_fields.

    `fusion_by_model` is {ModelID -> bool} over the fusion-profiled universe (True = a
    high-confidence fusion INVOLVING the target, either partner). Runs the SAME one-sided
    Mann-Whitney contrast the mutation/CN paths use (fusion-positive more dependent).
    Returns the card's summary_fields shape + fusion_stratification_class.
    """
    # Reuse the proven contrast verbatim (substrate-agnostic: chronos + {ModelID -> bool}).
    METHODS_REPO = Path(__file__).resolve().parent.parent.parent
    if str(METHODS_REPO) not in sys.path:
        sys.path.insert(0, str(METHODS_REPO))
    from methods.depmap_mutation_dependency.cli import _mannwhitney_stratification

    res = _mannwhitney_stratification(
        chronos_by_model, fusion_by_model,
        min_mutant=min_positive, min_wildtype=min_negative,
    )

    # Single test → q == p (no multi-tier BH; the mutation path only BH-corrects across its
    # 3 tiers). Fill q from p so the classifier (which gates on q) works identically.
    q = res.get("p_value")
    delta = res.get("delta_mut_vs_wt")

    def _classify() -> str:
        if res.get("_insufficient_data"):
            return "insufficient_fusion_rate"
        if q is None or delta is None or q >= stratification_alpha:
            return "not_fusion_stratified"
        if delta <= strong_effect_delta:
            return "fusion_positive_strongly_dependent"
        if delta <= moderate_effect_delta:
            return "fusion_positive_moderately_dependent"
        if delta >= WT_INVERSE_DELTA:
            return "fusion_negative_strongly_dependent"
        return "not_fusion_stratified"

    cls = _classify()
    n_evaluated = len(set(chronos_by_model) & set(fusion_by_model))

    return {
        "n_cell_lines_evaluated": int(n_evaluated),
        "n_fusion_positive": res["n_mutant"],
        "n_fusion_negative": res["n_wildtype"],
        "median_chronos_fusion_positive": res["median_mutant"],
        "median_chronos_fusion_negative": res["median_wildtype"],
        "delta_chronos_fusion_positive_vs_negative": delta,
        "fusion_stratification_mannwhitney_p": res.get("p_value"),
        "fusion_stratification_mannwhitney_q": q,
        "fusion_stratification_effect_size": res.get("effect_size"),
        "fusion_stratification_class": cls,
    }
