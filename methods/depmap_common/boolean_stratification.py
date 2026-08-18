#!/usr/bin/env python3
"""Shared single-boolean stratified-dependency contrast for the DepMap dependency-biomarker siblings.

copy-number-, fusion-, and amp-expr-stratified dependency each build ONE ``{ModelID -> bool}``
stratifier (amplified / fusion-positive / amplified∩overexpressed) and run the SAME one-sided
Mann-Whitney contrast on Chronos that ``depmap_mutation_dependency`` established, then classify the
effect into strong / moderate / reverse tiers. This module owns that shared contrast + classifier so
the three siblings differ only in (a) how they build the boolean vector and (b) how they name their
output fields — not in the statistic or the tiering, which used to be copied verbatim three times.

A single boolean means a single test, so there is no multi-tier BH correction (q == p); the mutation
path only BH-corrects across its three variant-class tiers.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

# Effect-size + significance thresholds shared by every single-boolean stratified-dependency sibling.
# delta = positive-arm median Chronos - comparator median (more negative = positive arm more dependent).
STRONG_EFFECT_DELTA = -0.5      # delta <= -0.5 -> positive arm strongly dependent
MODERATE_EFFECT_DELTA = -0.2    # delta <= -0.2 -> positive arm moderately dependent
STRATIFICATION_ALPHA = 0.05
MIN_POSITIVE_CELLS = 5          # min lines in the positive (altered) arm
MIN_COMPARATOR_CELLS = 30       # min lines in the comparator arm


@dataclass(frozen=True)
class StratificationLabels:
    """The class strings a sibling emits — the only thing that varies between cn / fusion / amp-expr."""
    strong: str            # forward, delta <= -0.5: positive arm strongly dependent
    moderate: str          # forward, delta <= -0.2: positive arm moderately dependent
    reverse_strong: str    # comparator arm strongly dependent (verdict-inert; TSG-like biology)
    not_stratified: str    # tested, no significant directional effect
    insufficient: str      # too few lines in an arm to run the test


def mannwhitney_stratification(chronos_by_model: dict, bool_by_model: dict, *,
                               min_positive: int = MIN_POSITIVE_CELLS,
                               min_comparator: int = MIN_COMPARATOR_CELLS) -> dict:
    """The proven one-sided Mann-Whitney contrast, imported once from ``depmap_mutation_dependency``.

    Substrate-agnostic: takes ``chronos_by_model`` + a ``{ModelID -> bool}`` stratifier and returns
    the kernel's ``n_mutant / n_wildtype / median_* / delta_mut_vs_wt / p_value / p_value_reverse /
    effect_size / _insufficient_data`` fields.
    """
    methods_repo = Path(__file__).resolve().parent.parent.parent
    if str(methods_repo) not in sys.path:
        sys.path.insert(0, str(methods_repo))
    from methods.depmap_mutation_dependency.cli import _mannwhitney_stratification
    return _mannwhitney_stratification(
        chronos_by_model, bool_by_model, min_mutant=min_positive, min_wildtype=min_comparator)


def classify_stratification(res: dict, labels: StratificationLabels, *,
                            strong_effect_delta: float = STRONG_EFFECT_DELTA,
                            moderate_effect_delta: float = MODERATE_EFFECT_DELTA,
                            stratification_alpha: float = STRATIFICATION_ALPHA) -> str:
    """Map a ``mannwhitney_stratification`` result to one of ``labels``.

    FORWARD (positive arm more dependent): a significant forward p with a negative delta grades into
    the strong / moderate tiers. REVERSE (comparator arm more dependent): a significant reverse p with
    a strong positive delta yields ``reverse_strong`` — verdict-inert (no rule/resolver consumes it),
    surfaced only for completeness. Single boolean -> q == p (no multi-tier BH).
    """
    if res.get("_insufficient_data"):
        return labels.insufficient
    delta = res.get("delta_mut_vs_wt")
    if delta is None:
        return labels.not_stratified
    p = res.get("p_value")
    p_reverse = res.get("p_value_reverse")
    if p is not None and p < stratification_alpha:
        if delta <= strong_effect_delta:
            return labels.strong
        if delta <= moderate_effect_delta:
            return labels.moderate
    if (p_reverse is not None and p_reverse < stratification_alpha
            and delta >= -strong_effect_delta):   # >= +0.5, mirrors the forward "strong" magnitude
        return labels.reverse_strong
    return labels.not_stratified
