#!/usr/bin/env python3
"""depmap_amp_expr_dependency CLI — amplification+overexpression conjoint-stratified dependency compute.

Single conjoint-vs-rest Mann-Whitney contrast on Chronos (one boolean vector → no multi-tier BH, like
CN/fusion). The boolean is the CONJUNCTION amplified (CN>1.5) AND high-expression (top within-panel TPM
tertile). Reuses the PROVEN _mannwhitney_stratification from depmap_mutation_dependency verbatim, so the
statistics are identical to the mutation/CN/fusion paths.
"""
from __future__ import annotations

import sys
from pathlib import Path

METHOD_VERSION = "0.1.0"

# Focal-amplification convention (relative CN, diploid ~ 1.0; NOT log2) — reused from depmap_cn_dependency.
FOCAL_AMP = 1.5
# High-expression cut: top within-panel tertile of log2TPM among EVALUATED lines (target-relative, no
# external percentile product needed — adapts per target, mirrors the CN method's self-contained cutoff).
HIGH_EXPR_TERTILE = 2.0 / 3.0

# Classification thresholds — mirror depmap_cn_dependency / depmap_fusion_dependency exactly.
STRONG_EFFECT_DELTA = -0.5
MODERATE_EFFECT_DELTA = -0.2
STRATIFICATION_ALPHA = 0.05
MIN_CONJOINT_CELLS = 5         # mirror min_mutant / min_amplified / min_positive
MIN_COMPARATOR_CELLS = 30      # mirror min_wildtype / min_neutral / min_negative
WT_INVERSE_DELTA = 0.3


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


def compute_amp_expr_stratification(chronos_by_model: dict, cn_by_model: dict, tpm_by_model: dict,
                                    focal_amp: float = FOCAL_AMP,
                                    strong_effect_delta: float = STRONG_EFFECT_DELTA,
                                    moderate_effect_delta: float = MODERATE_EFFECT_DELTA,
                                    stratification_alpha: float = STRATIFICATION_ALPHA,
                                    min_conjoint: int = MIN_CONJOINT_CELLS,
                                    min_comparator: int = MIN_COMPARATOR_CELLS) -> dict:
    """Compute the amp-expr-stratified-dependency summary_fields.

    Positive arm = amplified (CN > focal_amp) AND high-expression (TPM > top-tertile cut among evaluated
    lines). Comparator = every other evaluated line. Runs the SAME one-sided Mann-Whitney the CN/fusion
    paths use (conjoint more dependent). Returns the card's summary_fields shape + amp_expr_stratification_class.
    """
    METHODS_REPO = Path(__file__).resolve().parent.parent.parent
    if str(METHODS_REPO) not in sys.path:
        sys.path.insert(0, str(METHODS_REPO))
    from methods.depmap_mutation_dependency.cli import _mannwhitney_stratification

    # Evaluated universe = lines with ALL THREE measurements (the conjunction needs CN AND TPM AND Chronos).
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
            "amp_expr_stratification_class": "insufficient_amp_expr_rate",
        }

    # Conjoint boolean over the evaluated universe.
    conjoint_by_model = {
        m: (cn_by_model[m] > focal_amp and tpm_by_model[m] > high_expr_cut)
        for m in evaluated
    }

    res = _mannwhitney_stratification(
        chronos_by_model, conjoint_by_model,
        min_mutant=min_conjoint, min_wildtype=min_comparator,
    )

    q = res.get("p_value")
    delta = res.get("delta_mut_vs_wt")

    def _classify() -> str:
        if res.get("_insufficient_data"):
            return "insufficient_amp_expr_rate"
        if q is None or delta is None or q >= stratification_alpha:
            return "not_amp_expr_stratified"
        if delta <= strong_effect_delta:
            return "amplified_overexpressed_strongly_dependent"
        if delta <= moderate_effect_delta:
            return "amplified_overexpressed_moderately_dependent"
        if delta >= WT_INVERSE_DELTA:
            return "amp_expr_negative_more_dependent"
        return "not_amp_expr_stratified"

    cls = _classify()

    return {
        "n_cell_lines_evaluated": len(evaluated),
        "n_amplified_overexpressed": res["n_mutant"],
        "n_comparator": res["n_wildtype"],
        "median_chronos_amp_expr": res["median_mutant"],
        "median_chronos_comparator": res["median_wildtype"],
        "delta_chronos_amp_expr_vs_rest": delta,
        "amp_expr_mannwhitney_p": res.get("p_value"),
        "amp_expr_mannwhitney_q": q,
        "amp_expr_effect_size": res.get("effect_size"),
        "amplification_threshold_relative_cn": float(focal_amp),
        "high_expression_log2tpm_threshold": float(high_expr_cut),
        "amp_expr_stratification_class": cls,
    }
