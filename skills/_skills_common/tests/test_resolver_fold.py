"""Fold interpreter (match_all_reduce) — VERDICT_REPRESENTATION_FOLD.md foundation B. Pins:
- first_match (default) is unchanged (regression);
- match_all_reduce with priority = ladder index is BYTE-EQUIVALENT to first_match on every input
  (the by-construction equivalence that lets a resolver flip land with no verdict change);
- match_all_reduce is ORDER-INDEPENDENT (shuffling rungs, priorities fixed, changes nothing) — R6;
- min-priority wins regardless of position; driving_rule_id fidelity preserved.
"""

from __future__ import annotations

import itertools

from _skills_common.resolver import resolve_verdict, resolve_verdict_provenance  # noqa: E402

# a 3-rung ladder (first-match precedence): killer > selective > weak, default insufficient.
_RUNGS = [
    {"verdict": "killer", "when_fired": "kill-rule"},
    {"verdict": "selective", "when_any_fired": ["sel-a", "sel-b"]},
    {"verdict": "weak", "when_all_fired": ["w1", "w2"]},
]
_FIRST_MATCH = {"gate": "x", "default": "insufficient", "resolve": _RUNGS}


def _with_index_priorities(rungs):
    return {
        "gate": "x",
        "default": "insufficient",
        "evaluation": "match_all_reduce",
        "resolve": [{**r, "priority": i} for i, r in enumerate(rungs)],
    }


def _fired(*ids):
    return [{"rule_id": r} for r in ids]


# every subset of the rule universe — the exhaustive equivalence domain (small, so full power set)
_UNIVERSE = ["kill-rule", "sel-a", "sel-b", "w1", "w2", "noise"]
_ALL_FIRED = [list(c) for k in range(len(_UNIVERSE) + 1) for c in itertools.combinations(_UNIVERSE, k)]


def test_first_match_regression():
    assert resolve_verdict(_fired("kill-rule", "sel-a"), _FIRST_MATCH) == ("killer", "kill-rule")
    assert resolve_verdict(_fired("sel-b"), _FIRST_MATCH) == ("selective", "sel-b")
    assert resolve_verdict(_fired("w1", "w2"), _FIRST_MATCH) == ("weak", "w2")
    assert resolve_verdict(_fired("noise"), _FIRST_MATCH) == ("insufficient", None)


def test_match_all_reduce_is_byte_equivalent_to_first_match():
    fold = _with_index_priorities(_RUNGS)
    for fired in _ALL_FIRED:
        assert resolve_verdict(_fired(*fired), fold) == resolve_verdict(_fired(*fired), _FIRST_MATCH), fired


def test_match_all_reduce_is_order_independent():
    # shuffle the rung order but KEEP each rung's priority: the result must not change (R6).
    base = _with_index_priorities(_RUNGS)
    for perm in itertools.permutations(base["resolve"]):
        shuffled = {**base, "resolve": list(perm)}
        for fired in (["kill-rule", "sel-a", "w1", "w2"], ["sel-a", "w1", "w2"], ["w1", "w2"], ["noise"]):
            assert resolve_verdict(_fired(*fired), shuffled) == resolve_verdict(_fired(*fired), base)


def test_min_priority_wins_regardless_of_position():
    # killer authored LAST but given the top priority (0) still wins over selective (priority 1).
    spec = {
        "gate": "x",
        "default": "insufficient",
        "evaluation": "match_all_reduce",
        "resolve": [
            {"verdict": "selective", "when_any_fired": ["sel-a"], "priority": 1},
            {"verdict": "killer", "when_fired": "kill-rule", "priority": 0},
        ],
    }
    assert resolve_verdict(_fired("kill-rule", "sel-a"), spec) == ("killer", "kill-rule")


def test_resolve_verdict_provenance_reports_discarded_matches():
    """D1: resolve_verdict_provenance returns the winner PLUS the matching rungs that LOST — the
    observability the precedence-review (RFC Class A) needs — while resolve_verdict stays a 2-tuple."""
    spec = {
        "gate": "t",
        "default": "none",
        "evaluation": "match_all_reduce",
        "resolve": [
            {"verdict": "strong", "when_fired": "r_strong", "priority": 0},
            {"verdict": "weak", "when_fired": "r_weak", "priority": 5},
            {"verdict": "annotation", "when_fired": "r_annot", "priority": 9},
        ],
    }
    fired = [{"rule_id": "r_weak"}, {"rule_id": "r_annot"}]  # two rungs match; strong does NOT
    v, drv, discarded = resolve_verdict_provenance(fired, spec)
    assert (v, drv) == ("weak", "r_weak")  # min-priority match wins
    assert discarded == [(9, "annotation", "r_annot")]  # the loser is reported
    # resolve_verdict (hot path) is UNCHANGED — same winner, 2-tuple, no behavior drift
    assert resolve_verdict(fired, spec) == ("weak", "r_weak")
    # no match → default, empty discarded
    assert resolve_verdict_provenance([{"rule_id": "x"}], spec) == ("none", None, [])
