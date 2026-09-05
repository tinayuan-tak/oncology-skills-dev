"""differentiation-landscape _verdict coverage (G test-gap + C exhaustiveness, 2026-07-20).

Shipped with NO tests despite being the skill whose historical rename bug (cooccurrence-ns
→ insufficient) is the canonical silent-fall-through example. These tests pin every
(rule_id → verdict) in the precedence list, precedence order, and — critically — that
`ns` maps to the `ns` verdict, NOT a silent `insufficient` (the exact bug that regressed).
Manual precursor to the gap-#5 exhaustiveness validator.
"""
from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

dl = load_run_py(Path(__file__).resolve().parent.parent, "dl_run")


def _v(*rule_ids):
    return dl._verdict([{"rule_id": r} for r in rule_ids])


# --- every rung maps (exhaustive over the cooccurrence_class vocabulary) ----

def test_all_precedence_rungs_map_to_distinct_verdicts():
    expected = {
        "cooccurrence-both-patterns-supportive": "both_patterns_present",
        "strong-mutual-exclusivity-supportive": "strong_mutually_exclusive",
        "cooccurrence-strong-supportive": "strong_cooccurring",
        "has-cooccurring-driver-supportive": "has_cooccurring_driver",
        "cooccurrence-modest-cooccurring-neutral": "modest_cooccurring",
        "cooccurrence-modest-mutually-exclusive-neutral": "modest_mutually_exclusive",
        "cooccurrence-ns-neutral": "ns",
        "cooccurrence-data-unavailable-insufficient": "data_unavailable",
    }
    for rule_id, verdict in expected.items():
        assert _v(rule_id) == (verdict, rule_id), f"{rule_id} must map to {verdict}"


def test_ns_is_not_silently_insufficient_regression():
    """The canonical silent-fall-through bug: cooccurrence-ns must yield the `ns`
    verdict, NOT collapse to insufficient (the rename bug that regressed ns→insufficient)."""
    v, drv = _v("cooccurrence-ns-neutral")
    assert v == "ns" and drv == "cooccurrence-ns-neutral"
    assert v != "insufficient"


def test_precedence_both_patterns_wins():
    # highest-precedence rung wins when multiple fire
    v, _ = _v("cooccurrence-ns-neutral", "cooccurrence-both-patterns-supportive")
    assert v == "both_patterns_present"


def test_nothing_fired_is_insufficient():
    assert dl._verdict([]) == ("insufficient", None)
