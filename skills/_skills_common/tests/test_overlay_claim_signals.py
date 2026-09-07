"""Unification (signals-first): sub-group SIGNAL is overlaid from the claim_vector (the tuned per-axis
tier + evidence-atom trace), not the coarse heuristic re-read; cards keep supplying corroboration.
Pure-function tests for overlay_claim_signals — no contracts / no I/O."""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.subgroup_derivation import overlay_claim_signals  # noqa: E402


HIER_DEFAULT = {"sub_groups": [{"id": "DEP"}, {"id": "SEL"}]}  # axis_key == sub_group id
HIER_MAPPED = {
    "sub_groups": [
        {"id": "abundance", "claim_axes": ["A"]},  # presence-style mapping
        {"id": "generality", "claim_axes": ["D"]},
    ]
}


def test_signal_overrides_heuristic_and_carries_atom():
    sg = {
        "DEP": {
            "signal": "moderate",
            "confidence": "high",
            "sources": [{"card": "x", "tier": "moderate"}],
            "conflict": False,
        }
    }
    cv = {
        "DEP": {
            "signal": "strong",
            "corroboration": "high",
            "conflict": None,
            "evidence": "CRISPR strong",
            "evidence_atom": {"read": "strongly_dependent"},
        }
    }
    overlay_claim_signals(sg, cv, HIER_DEFAULT)
    assert sg["DEP"]["signal"] == "strong"  # claim beats the heuristic 'moderate'
    assert sg["DEP"]["signal_source"] == "claim_vector"
    assert sg["DEP"]["confidence"] == "high"  # card-derived corroboration untouched
    assert sg["DEP"]["sources"] == [{"card": "x", "tier": "moderate"}]
    assert sg["DEP"]["claims"][0]["axis"] == "DEP"
    assert sg["DEP"]["claims"][0]["evidence_atom"] == {"read": "strongly_dependent"}


def test_unmeasured_claim_is_gap_not_absent():
    """A claim that was never measured -> `unmeasured` (the heuristic can only say absent)."""
    sg = {"SEL": {"signal": "absent", "confidence": "low", "sources": []}}
    cv = {"SEL": {"signal": "unmeasured", "corroboration": "unmeasured", "evidence": "no arm"}}
    overlay_claim_signals(sg, cv, HIER_DEFAULT)
    assert sg["SEL"]["signal"] == "unmeasured"


def test_conflict_merges_from_claim():
    sg = {"DEP": {"signal": "weak", "conflict": False, "sources": []}}
    cv = {"DEP": {"signal": "strong", "conflict": "CRISPR↔RNAi discordant"}}
    overlay_claim_signals(sg, cv, HIER_DEFAULT)
    assert sg["DEP"]["conflict"] is True


def test_creates_signal_only_subgroup_when_no_card_source():
    sg = {}  # heuristic found no card for this axis
    cv = {"A": {"signal": "moderate", "corroboration": "low", "evidence": "e"}}
    overlay_claim_signals(sg, cv, HIER_MAPPED)
    assert sg["abundance"]["signal"] == "moderate"
    assert sg["abundance"]["sources"] == []  # signal-only, honest about no cards


def test_claim_axes_mapping_and_missing_axis_is_noop():
    sg = {"generality": {"signal": "weak", "sources": []}}
    cv = {"D": {"signal": "moderate", "evidence": "breadth"}}  # no 'A' -> abundance stays untouched
    overlay_claim_signals(sg, cv, HIER_MAPPED)
    assert sg["generality"]["signal"] == "moderate"
    assert "abundance" not in sg  # unmapped axis is never invented


def test_best_effort_noop_on_bad_input():
    assert overlay_claim_signals({}, None, HIER_DEFAULT) == {}
    assert overlay_claim_signals(None, {"DEP": {}}, HIER_DEFAULT) is None
