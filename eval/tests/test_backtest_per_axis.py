"""Hermetic tests for backtest_per_axis — the per-claim-vector-axis attribution scorer.

Runs via: pixi run pytest eval/tests/test_backtest_per_axis.py -q   (from the home checkout).

Guards Step 1a: the backtest reads the AUTHORITATIVE deciding-axis attribution the run emits
(target_call.deciding_axis), rather than reconstructing it from gate.triggered_by — which was lossy
(empty for a positive_signal call, so every nominate/positive target was silently dropped from
scoring). A legacy fallback keeps pre-1a nomination.json files scorable.
"""

from __future__ import annotations

import sys
from pathlib import Path

_EVAL = Path(__file__).resolve().parents[1]
if str(_EVAL) not in sys.path:
    sys.path.insert(0, str(_EVAL))

import backtest_per_axis as bpa  # noqa: E402


def _nom(deciding_axis=None, gate=None):
    return {"target": "X", "target_call": {"deciding_axis": deciding_axis, "gate": gate or {}}, "sub_verdicts": {}}


def test_emitted_gate_fired_is_authoritative():
    da = {
        "basis": "gate_fired",
        "deciding_axis": {"short": "safety"},
        "admissible_but_silent": [{"short": "surface_modality"}],
    }
    shorts, basis, silent = bpa._emitted_attribution(_nom(da))
    assert shorts == ["safety"] and basis == "gate_fired"
    assert [s["short"] for s in silent] == ["surface_modality"]


def test_emitted_positive_signal_is_a_set():
    da = {"basis": "positive_signal", "deciding_axes": [{"short": "dependency"}, {"short": "selectivity"}]}
    shorts, basis, _ = bpa._emitted_attribution(_nom(da))
    assert shorts == ["dependency", "selectivity"] and basis == "positive_signal"


def test_emitted_abstention_has_no_deciding_axis():
    shorts, basis, _ = bpa._emitted_attribution(_nom({"basis": "abstention_coverage_gaps", "unevidenced_gates": []}))
    assert shorts == [] and basis == "abstention_coverage_gaps"


def test_legacy_fallback_reconstructs_when_no_block():
    """A pre-1a nomination.json (no emitted deciding_axis block) still scores via the old
    gate.triggered_by reconstruction."""
    nom = _nom(deciding_axis=None, gate={"triggered_by": [{"short": "dependency"}]})
    shorts, basis, silent = bpa._emitted_attribution(nom)
    assert (shorts, basis, silent) == ([], None, [])  # no block → emitted-reader yields nothing…
    row = bpa.score_target(nom, {"deciding_axis": "pan_essential", "outcome": "declined"})
    assert row["composed_deciding_short"] == "dependency"  # …and score_target falls back to reconstruct


def test_positive_signal_matches_on_any_supporting_axis():
    """A positive_signal call is supported by a SET; attribution is correct if the ground-truth axis
    is ANY of them (here surface, matched by surface_modality)."""
    da = {"basis": "positive_signal", "deciding_axes": [{"short": "dependency"}, {"short": "surface_modality"}]}
    row = bpa.score_target(_nom(da), {"deciding_axis": "E2_density_topology", "outcome": "approved_class"})
    assert row["ref_family"] == "surface"
    assert row["axis_attribution_match"] is True
    assert row["composed_basis"] == "positive_signal"


def test_gate_fired_wrong_axis_is_a_miss():
    da = {"basis": "gate_fired", "deciding_axis": {"short": "safety"}}
    row = bpa.score_target(_nom(da), {"deciding_axis": "E2_density_topology", "outcome": "approved_class"})
    assert row["ref_family"] == "surface" and row["fw_family"] == "safety"
    assert row["axis_attribution_match"] is False


def test_backtest_surfaces_attribution_mismatch():
    """Step 1b: the row carries the run-emitted attribution_mismatch flag (per-run honesty signal),
    independent of the ground-truth axis_attribution_match."""
    da = {"basis": "gate_fired", "deciding_axis": {"short": "safety"}, "attribution_mismatch": {"flagged": True}}
    row = bpa.score_target(_nom(da), {"deciding_axis": "constrained_safety", "outcome": "approved_class"})
    assert row["attribution_mismatch"] is True
    # absent/False block → False, never None
    da2 = {"basis": "gate_fired", "deciding_axis": {"short": "dependency"}}
    row2 = bpa.score_target(_nom(da2), {"deciding_axis": "pan_essential", "outcome": "declined"})
    assert row2["attribution_mismatch"] is False
