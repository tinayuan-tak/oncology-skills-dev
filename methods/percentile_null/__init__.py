"""percentile_null — all-gene percentile of a target's metric within a context.

Turns an ABSOLUTE per-target metric (log2FC, effect size, median abundance) into a
RELATIVE one: where does the target fall in the distribution of the SAME metric
across ALL genes measured in the same (indication × assay × sample-type) context?

The reference distribution (the "null vector") MUST be context-matched — the
population of all genes' values from the SAME product/cohort the target row came
from. Pooling across indications produces a meaningless percentile; callers pass a
context string so the emitted percentile is auditable.

Modeled on tcga_gtex_expression_distribution/stats.py::fraction_above_normal_percentile
(same np-percentile shape; reference vector is the gene population instead of normals).
"""

from __future__ import annotations

import math
from typing import Iterable, Optional

# Default percentile-class cutoffs (cards may override via their thresholds: block).
DEFAULT_CUTOFFS = {"top_1pct": 99.0, "top_decile": 90.0, "bottom_decile": 10.0}


def _finite(values: Iterable[float]) -> list[float]:
    """Drop non-finite values (None/NaN/±inf). An inf metric — e.g. effect size when
    a normal median is 0 — would poison np.sort / searchsorted, so it is excluded
    from the null AND treated as unrankable if it is the target value."""
    out = []
    for v in values:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            out.append(f)
    return out


def percentile_rank(value: Optional[float], null_values: Iterable[float]) -> Optional[float]:
    """Percentile (0-100) of `value` within the all-gene `null_values` distribution.

    Uses the fraction of genes with a value <= the target (mid-rank on ties), the
    standard empirical-percentile convention. Returns None when the value is
    non-finite or the null is empty (caller renders data_unavailable).
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    pop = _finite(null_values)
    if not pop:
        return None
    below = sum(1 for x in pop if x < v)
    equal = sum(1 for x in pop if x == v)
    # mid-rank: count ties as half, so an exactly-median gene lands ~50th pct.
    return 100.0 * (below + 0.5 * equal) / len(pop)


def classify_percentile(pct: Optional[float], cutoffs: dict | None = None) -> str:
    """Bin a percentile into the card categorical. Cutoffs come from the card's
    thresholds: block (method-side binning — the rules engine can't threshold a
    float, so a categorical companion is what drives any verdict)."""
    if pct is None:
        return "data_unavailable"
    c = {**DEFAULT_CUTOFFS, **(cutoffs or {})}
    if pct >= c["top_1pct"]:
        return "top_1pct"
    if pct >= c["top_decile"]:
        return "top_decile"
    if pct <= c["bottom_decile"]:
        return "bottom_decile"
    return "mid"
