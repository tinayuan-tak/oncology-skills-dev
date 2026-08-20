"""Unit tests for immune-context's claim vector (skills/_skills_common/immune_context_claims.py) —
the TCE effector axis. Pins the IMMUNE tier map, the CD8-fraction atom, and the immune_cold=absent
(measured effector-absence, not a veto) discipline. Pure."""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.immune_context_claims import (  # noqa: E402
    immune_context_claim_vector, immune_context_key_signals)


def _cards(cls="immune_hot"):
    return [{"card_id": "immune-context", "summary": {
        "immune_context_class": cls, "median_cd8_fraction": 0.154,
        "median_total_t_cell_fraction": 0.32, "n_samples": 470, "tumor_studies": ["SKCM"]}}]


def test_tier_map():
    assert immune_context_claim_vector({}, _cards("immune_hot"))["IMMUNE"]["signal"] == "strong"
    assert immune_context_claim_vector({}, _cards("immune_intermediate"))["IMMUNE"]["signal"] == "moderate"
    assert immune_context_claim_vector({}, _cards("immune_cold"))["IMMUNE"]["signal"] == "absent"
    assert immune_context_claim_vector({}, _cards("data_unavailable"))["IMMUNE"]["signal"] == "unmeasured"


def test_cd8_fraction_atom():
    vec = immune_context_claim_vector({}, _cards("immune_hot"))
    atom = vec["IMMUNE"]["evidence_atom"]
    assert atom["cite"]["card_id"] == "immune-context"
    assert atom["values"]["median_cd8_fraction"] == 0.154
    assert atom["entity"]["grain"] == "indication"


def test_atom_absent_without_card():
    vec = immune_context_claim_vector({}, [])
    assert vec["IMMUNE"]["signal"] == "unmeasured"
    assert "evidence_atom" not in vec["IMMUNE"]


def test_key_signals_headline():
    hot = immune_context_key_signals({}, _cards("immune_hot"))["headline"]
    cold = immune_context_key_signals({}, _cards("immune_cold"))["headline"]
    assert "effector context present" in hot
    assert "Immune-cold" in cold or "limited" in cold.lower()
