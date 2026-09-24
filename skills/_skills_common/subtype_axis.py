"""Shared predicate for the subtype axis-quality grade — the ONE place the display layer decides
whether a molecular-subtype axis is strong enough to read as a real cross-subtype differential.

The methods reader rolls per-stratum `evidence_state` up to one honest `subtype_axis_quality` grade
(`analysis-methods/methods/subgroup_common/panorama.py:axis_quality`, most→least usable):

    powered      >= 2 strata clear the n-floor (evidence_state == "measured"): comparative subtype
                 claims ("enriched in A vs B") are SUPPORTABLE.
    exploratory  < 2 measured but >= 2 measured-OR-exploratory: contrastable as a HYPOTHESIS only.
    underpowered has samples but is not contrastable even as a hypothesis.
    unevaluable  nothing on the axis was classified.
    empty        every stratum was evaluated and none has members (a measured negative about the axis).
    unavailable  no records at all (no assignment shard / no subtype axis).
    None         the field was never produced.

Only `powered` supports a differential. `subtype_stratification_class` is derived from the MEASURED
strata alone, so a single measured-enriched stratum in an `exploratory`-graded family yields
`subtype_stratification_class == "subtype_enriched"` WHILE `subtype_axis_quality == "exploratory"` —
a combination that reads as a real differential to any consumer keying on the class without the grade
(claude-oncology-skills#1518). Two consumers already gate correctly — `run.py:_subtype_layer_concordance`
(joins only strata whose `subtype_signal` the reader left non-null) and
`subgroup_derivation.py` (per-stratum `evidence_state == "measured" and n >= n_floor`) — this predicate
converges the remaining display consumers on that same reading.

Verdict-INERT: `tumor-rna-distribution-by-subtype` is display-only and feeds no ladder, so routing a
grade through this predicate must leave the pooled `presence_verdict` (the replay golden) byte-stable.
"""

from __future__ import annotations

from typing import Optional

# The single grade that supports a COMPARATIVE subtype claim. Kept as a constant so the set of
# "differential-capable" grades has exactly one definition across every consumer.
_POWERED_GRADE = "powered"


def is_powered_axis(subtype_axis_quality: Optional[str]) -> bool:
    """True iff the subtype axis-quality grade is `powered` — enough powered strata to support a
    comparative subtype claim. Every other grade (exploratory / underpowered / unevaluable / empty /
    unavailable / None) is NOT powered and must not read as a cross-subtype differential."""
    return subtype_axis_quality == _POWERED_GRADE


def is_differential_axis(subtype_axis_quality: Optional[str]) -> bool:
    """Display-layer gate: may a consumer surface this subtype axis as a real cross-subtype
    DIFFERENTIAL (enriched/restricted selection handle)? Only a `powered` axis qualifies — an
    `exploratory` (hypothesis-only) or weaker grade must render as unmeasured / hypothesis-grade,
    never as a favourable differential. Semantic alias of `is_powered_axis` for read-clarity at the
    display sites; one definition, so the next consumer cannot re-introduce the gap."""
    return is_powered_axis(subtype_axis_quality)
