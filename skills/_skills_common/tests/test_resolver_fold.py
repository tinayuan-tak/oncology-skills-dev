"""Fold interpreter (match_all_reduce) — VERDICT_REPRESENTATION_FOLD.md foundation B. Pins:
- first_match (default) is unchanged (regression);
- match_all_reduce with priority = ladder index is BYTE-EQUIVALENT to first_match on every input
  (the by-construction equivalence that lets a resolver flip land with no verdict change);
- match_all_reduce is ORDER-INDEPENDENT (shuffling rungs, priorities fixed, changes nothing) — R6;
- min-priority wins regardless of position; driving_rule_id fidelity preserved.
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILLS))
from _skills_common.resolver import resolve_verdict  # noqa: E402

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
