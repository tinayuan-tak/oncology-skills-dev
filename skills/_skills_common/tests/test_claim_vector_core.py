"""Unit tests for the SHARED claim_vector_core contract (skills/_skills_common/claim_vector_core.py).

Pin the COMBINATION DISCIPLINE the shared machinery must uphold, independent of any one skill's axes:
  * ordinal (not metric) tiers; gap (`unmeasured`) is off-scale, never comparable, never == absent;
  * within-claim corroboration is SUB-ADDITIVE (lifts reliability, never the signal tier);
  * conflict caps reliability; claims stay separate; the key-signals builder ranks + gates + picks the
    weakest MEASURED critical caveat deterministically.
Pure — no S3, no card reads.
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]        # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.claim_vector_core import (  # noqa: E402
    SIGNAL_ORD, RELIABILITY_ORD, ClaimSpec, build_claim_vector, build_key_signals,
    bump_reliability, cap_reliability, weakest, sig_ge, cards_by_id,
)


# ── ordinal / gap≠absent invariants ───────────────────────────────────────────────────────────────
def test_gap_is_off_scale_not_zero():
    assert SIGNAL_ORD["unmeasured"] is None          # a GAP is off-scale
    assert SIGNAL_ORD["absent"] == 0                  # a measured floor IS on-scale
    assert SIGNAL_ORD["negative"] == 0
    assert RELIABILITY_ORD["unmeasured"] is None


def test_sig_ge_treats_unmeasured_as_never_meeting_floor():
    assert sig_ge("strong", "moderate")
    assert sig_ge("moderate", "moderate")
    assert not sig_ge("weak", "moderate")
    assert not sig_ge("unmeasured", "absent")        # gap is never >= even the floor
    assert not sig_ge(None, "absent")


# ── sub-additive corroboration + conflict cap ──────────────────────────────────────────────────────
def test_bump_reliability_is_sub_additive_and_capped():
    assert bump_reliability("low", True) == "moderate"
    assert bump_reliability("moderate", True) == "high"
    assert bump_reliability("high", True) == "high"          # cannot exceed high
    assert bump_reliability("low", False) == "low"           # no corroboration = no-op
    assert bump_reliability("unmeasured", True) == "unmeasured"  # a gap can't be corroborated


def test_cap_reliability_never_raises():
    assert cap_reliability("high", "moderate") == "moderate"
    assert cap_reliability("low", "moderate") == "low"       # already below ceiling → unchanged
    assert cap_reliability("unmeasured", "low") == "unmeasured"


def test_weakest_ignores_unmeasured():
    assert weakest(["high", "moderate", "low"], RELIABILITY_ORD) == "low"
    assert weakest(["high", "unmeasured"], RELIABILITY_ORD) == "high"   # gap doesn't win weakest-link
    assert weakest(["unmeasured"], RELIABILITY_ORD) is None


def test_cards_by_id_tolerates_none():
    assert cards_by_id(None) == {}
    assert cards_by_id([{"card_id": "x", "summary": None}]) == {"x": {}}
    assert cards_by_id([{"card_id": "y", "summary": {"a": 1}}]) == {"y": {"a": 1}}


# ── build_claim_vector: axes stay SEPARATE, shape is uniform ───────────────────────────────────────
def _toy_spec():
    return [
        ClaimSpec("X", "x", lambda h, c: ("strong", "e-x", None), lambda h, c: "high", "informs-x"),
        ClaimSpec("Y", "y", lambda h, c: ("absent", "e-y", "conf-y"), lambda h, c: "low", "informs-y"),
        ClaimSpec("Z", "z", lambda h, c: ("unmeasured", "e-z", None), lambda h, c: "unmeasured", "informs-z"),
    ]


def test_build_claim_vector_shape_and_separation():
    vec = build_claim_vector(_toy_spec(), {}, [], "DISC")
    assert vec["_disclaimer"] == "DISC"
    assert vec["X"] == {"signal": "strong", "reliability": "high", "evidence": "e-x",
                        "conflict": None, "informs": "informs-x"}
    # a weak/absent Y sits UNCHANGED next to a strong X — no averaging, no cross-contamination
    assert vec["Y"]["signal"] == "absent" and vec["Y"]["conflict"] == "conf-y"
    assert vec["Z"]["signal"] == "unmeasured"


# ── build_key_signals: rank, >=moderate gate, weakest-critical caveat, deterministic headline ──────
def test_key_signals_ranks_gates_and_caveats():
    vec = build_claim_vector(_toy_spec(), {}, [], "DISC")
    out = build_key_signals(
        vec,
        rank_keys=("X", "Y", "Z"),
        support_fns={"X": lambda cl: "SUP-X", "Y": lambda cl: "SUP-Y", "Z": lambda cl: "SUP-Z"},
        critical_keys=("X", "Y"),
        caveat_fns={"X": lambda cl: "CAV-X", "Y": lambda cl: "CAV-Y"},
        headline_fn=lambda v, sup: f"H:{len(sup)}",
    )
    # only X is >= moderate → the sole support; Y(absent)/Z(gap) are gated out
    assert out["supports"] == ["SUP-X"]
    # weakest MEASURED critical claim is Y (absent, tier 0 <= weak) → its caveat fires (Z gap ignored)
    assert out["caveat"] == "CAV-Y"
    assert out["headline"] == "H:1"


def test_key_signals_no_caveat_when_all_critical_strong():
    spec = [ClaimSpec("A", "a", lambda h, c: ("strong", "", None), lambda h, c: "high", "i"),
            ClaimSpec("B", "b", lambda h, c: ("moderate", "", None), lambda h, c: "moderate", "i")]
    vec = build_claim_vector(spec, {}, [], "D")
    out = build_key_signals(vec, rank_keys=("A", "B"),
                            support_fns={"A": lambda cl: "sa", "B": lambda cl: "sb"},
                            critical_keys=("A", "B"), caveat_fns={"A": lambda cl: "ca", "B": lambda cl: "cb"},
                            headline_fn=lambda v, s: "h")
    assert out["caveat"] is None                       # weakest critical is moderate (tier 2 > weak)
    assert out["supports"] == ["sa", "sb"]


def test_key_signals_fallback_caveat_when_no_measured_critical():
    spec = [ClaimSpec("A", "a", lambda h, c: ("unmeasured", "", None), lambda h, c: "unmeasured", "i")]
    vec = build_claim_vector(spec, {}, [], "D")
    out = build_key_signals(vec, rank_keys=("A",), support_fns={}, critical_keys=("A",),
                            caveat_fns={}, headline_fn=lambda v, s: "h",
                            fallback_caveat_fn=lambda: "FALLBACK")
    assert out["caveat"] == "FALLBACK"
