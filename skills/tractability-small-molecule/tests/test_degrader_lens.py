"""Tests for the degrader lens (_degrader_snapshot) — modality-specific-interpretation slice 2.

The SM skill loads the intracellular axis, which scores small_molecule AND degrader in parallel.
_degrader_snapshot projects the DEGRADER channel of the fired rules into a degrader-specific read,
additive to (verdict-inert w.r.t.) the SM druggability_snapshot. Pure-helper tests (no I/O)."""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parent.parent, "tsm_run")


def _fired(rule_id, degrader_signal, dominant=False):
    return {
        "rule_id": rule_id,
        "card_id": "c",
        "dominant": dominant,
        "signals": {"small_molecule": "neutral", "degrader": degrader_signal},
    }


def test_dominant_degrader_supportive_is_strong():
    cls, drv = tp._degrader_snapshot([_fired("r-strong", "supportive", dominant=True)])
    assert cls == "strong_degrader_rationale" and drv == "r-strong"


def test_plain_degrader_supportive_is_rationale():
    cls, drv = tp._degrader_snapshot([_fired("r-sup", "supportive")])
    assert cls == "degrader_rationale" and drv == "r-sup"


def test_degrader_killer_is_unviable():
    # e.g. broadly-low expression → nothing to degrade
    cls, drv = tp._degrader_snapshot([_fired("expression-broadly-low-degrader-killer", "killer")])
    assert cls == "degrader_unviable"


def test_degrader_opposing():
    cls, drv = tp._degrader_snapshot([_fired("r-opp", "opposing")])
    assert cls == "degrader_opposed" and drv == "r-opp"


def test_no_degrader_signal_is_insufficient():
    assert tp._degrader_snapshot([]) == ("insufficient", None)
    # a rule with no degrader channel → insufficient
    assert tp._degrader_snapshot(
        [{"rule_id": "x", "card_id": "c", "dominant": False, "signals": {"small_molecule": "supportive"}}]
    ) == ("insufficient", None)


def test_killer_precedence_over_supportive():
    # a killer must dominate even if a supportive also fired
    fired = [_fired("r-sup", "supportive", dominant=True), _fired("r-kill", "killer")]
    cls, _ = tp._degrader_snapshot(fired)
    assert cls == "degrader_unviable"
