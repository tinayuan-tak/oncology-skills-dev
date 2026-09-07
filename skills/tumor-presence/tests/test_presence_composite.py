"""Phase 5 — continuous presence COMPOSITE: a monotone [0,1] portfolio-ranking scalar the one-word
presence_verdict cannot provide. A NAMED, certainty-discounted, non-substituting projection (peak
signal tier × weakest-link certainty), NOT a canonical single value. Verdict-INERT sidecar.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parent.parent, "tp_run")


def test_composite_values():
    assert tp._presence_composite("strong_positive", "high") == 1.0
    assert tp._presence_composite("strong_positive", "low") == 0.5  # strong signal, low certainty
    assert tp._presence_composite("moderate_positive", "medium") == 0.495
    assert tp._presence_composite("weak_positive", "high") == 0.33
    assert tp._presence_composite("none", "high") == 0.0
    assert tp._presence_composite("negative", "high") == 0.0  # measured-negative floors to 0


def test_composite_monotonic_in_strength_and_certainty():
    # strength ↑ at fixed certainty
    assert (
        tp._presence_composite("strong_positive", "high")
        > tp._presence_composite("moderate_positive", "high")
        > tp._presence_composite("weak_positive", "high")
    )
    # certainty ↑ at fixed strength (non-substituting: certainty is a multiplier)
    assert (
        tp._presence_composite("strong_positive", "high")
        > tp._presence_composite("strong_positive", "medium")
        > tp._presence_composite("strong_positive", "low")
    )


def test_sidecar_emits_composite_and_is_verdict_inert():
    sc = tp._strength_certainty([], verdict_pair=("not_informative", None))
    assert sc["composite"] == 0.0  # none × low
    assert "composite_basis" in sc and "NAMED" in sc["composite_basis"]
    # the sidecar never carries the spine verdict token as its own field
    assert "presence_verdict" not in sc


def test_strong_low_certainty_case():
    """A strong-signal / low-certainty target (e.g. EPCAM: strong abundance but conflict-capped
    certainty) ranks at 0.5 — legibly distinct from a strong/high-certainty target at 1.0."""
    sc = tp._strength_certainty([], verdict_pair=("strongly_upregulated_in_tumor", "rid"))
    # empty cards → coverage low → certainty low → composite = 1.0 * 0.5
    assert sc["strength"] == "strong_positive"
    assert sc["composite"] == 0.5
