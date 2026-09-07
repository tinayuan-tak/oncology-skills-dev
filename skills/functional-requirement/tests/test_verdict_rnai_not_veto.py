"""RNAi-only non-dependence must NOT drive a veto.

Before 2026-07-17 the _verdict collapsed both `non-dependent-killer` (CRISPR,
emits killer signals) AND `rnai-non-dependent-neutral` (RNAi, emits NEUTRAL
signals — RNAi is false-negative-prone) into `non_dependent`, which the nomination
gate maps to VETO. So RNAi-alone-not-dependent could hard-veto a target off a signal
the rule author deliberately marked neutral. Fix: only CRISPR non-dependence → veto;
RNAi-only → insufficient (honest 'not established').
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

fr = load_run_py(Path(__file__).resolve().parent.parent, "fr_run")


def test_crispr_non_dependent_still_vetoes():
    assert fr._verdict([{"rule_id": "non-dependent-killer"}]) == ("non_dependent", "non-dependent-killer")


def test_rnai_only_non_dependent_does_not_map_to_non_dependent():
    v, _ = fr._verdict([{"rule_id": "rnai-non-dependent-neutral"}])
    assert v != "non_dependent", "RNAi-only non-dependence must not reach the veto verdict"
    assert v == "insufficient"


def test_crispr_killer_still_wins_over_rnai_neutral():
    """If both fire, the CRISPR killer verdict stands (pan-essential precedence intact)."""
    v, _ = fr._verdict([{"rule_id": "non-dependent-killer"}, {"rule_id": "rnai-non-dependent-neutral"}])
    assert v == "non_dependent"
