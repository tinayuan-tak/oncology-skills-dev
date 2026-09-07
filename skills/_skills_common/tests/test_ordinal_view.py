"""Ordinal-view projection tests (gap #3 "now", 2026-07-20).

The module's whole reason to exist is a labeled ordering-of-categoricals that CANNOT masquerade
as measurement. These tests pin the honesty invariants:
  - the mapping is ORDER-PRESERVING (killer < opposing < neutral < supportive);
  - insufficient / not_applicable / unknown are OFF-SCALE (None), never a negative number;
  - every output carries the disclaimer;
  - ranking places off-scale cells as coverage gaps (trailing), NOT as "worst".
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_module

MOD = Path(__file__).resolve().parent.parent / "ordinal_view.py"

ov = load_module(MOD, "ordinal_view")


def test_order_preserving():
    """The load-bearing property: the ranks preserve killer < opposing < neutral < supportive."""
    assert ov.ordinal_of("killer") < ov.ordinal_of("opposing") < ov.ordinal_of("neutral") < ov.ordinal_of("supportive")


def test_absence_is_off_scale_not_a_number():
    """measured-vs-null discipline: insufficient / not_applicable are None, NOT a low score —
    'we didn't look' must never masquerade as 'we looked and it's mildly bad'."""
    assert ov.ordinal_of("insufficient") is None
    assert ov.ordinal_of("not_applicable") is None


def test_unknown_signal_is_none_never_guessed():
    """A vocabulary value the map doesn't know → None (never a fabricated rank)."""
    assert ov.ordinal_of("some_future_signal") is None
    assert ov.ordinal_of(None) is None


def test_project_signals_shape_and_disclaimer():
    view = ov.project_signals(
        {
            "dependency": "supportive",
            "selectivity": "opposing",
            "safety": "insufficient",
            "surface_modality": "not_applicable",
            "mechanism": "neutral",
        }
    )
    assert view["_disclaimer"], "every projection must carry the disclaimer"
    assert "NOT calibrated" in view["_disclaimer"]
    # off-scale cells reported as coverage, not value
    assert set(view["off_scale"]) == {"safety", "surface_modality"}
    assert view["cells"]["safety"]["on_scale"] is False
    assert view["cells"]["dependency"]["ordinal"] == 2


def test_ranking_puts_offscale_last_not_worst():
    """A killer (on-scale, most negative) must rank ABOVE an insufficient (off-scale) in the
    ordered list's tail logic — off-scale is a coverage gap, not the worst value. Concretely:
    on-scale cells (incl. killer) come first sorted high→low; off-scale trails."""
    view = ov.project_signals({"a": "killer", "b": "insufficient", "c": "supportive"})
    ordered = view["ordered"]
    # supportive (c) first, killer (a) next (on-scale), insufficient (b) last (off-scale)
    assert ordered == ["c", "a", "b"]
    # the killer is on-scale; the insufficient is not — killer is NOT ranked below a coverage gap
    assert view["cells"]["a"]["on_scale"] is True
    assert view["cells"]["b"]["on_scale"] is False


def test_legend_separates_on_and_off_scale():
    leg = ov.scale_legend()
    assert set(leg["on_scale"]) == {"supportive", "neutral", "opposing", "killer"}
    assert set(leg["off_scale"]) == {"insufficient", "not_applicable"}
    assert leg["_disclaimer"]
