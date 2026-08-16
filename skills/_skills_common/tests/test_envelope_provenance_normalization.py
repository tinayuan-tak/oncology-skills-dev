"""Regression: card_present provenance must always carry method_calls (evidence_package.schema).

A subskill card that emits a provenance dict WITHOUT method_calls used to pass through incomplete
via card.get('provenance', DEFAULT), so EVERY card failed card_present validation in
target-profile --emit evidence-package (--emit always exited 1, "not governance-grade"). The
normalizers now merge the schema-required keys into whatever provenance the card carries.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SK = Path(__file__).resolve().parents[2]  # .../skills
sys.path.insert(0, str(_SK))

from _skills_common.dispatcher import _envelope_card_present  # noqa: E402


def test_incomplete_provenance_gets_method_calls():
    """The bug case: provenance dict present but missing method_calls."""
    card = {"card_id": "c", "summary": {}, "interpretation_call": "x",
            "provenance": {"input_manifest_ids": ["m1"]}}
    prov = _envelope_card_present(card)["provenance"]
    assert prov["method_calls"] == []          # required key now present
    assert prov["input_manifest_ids"] == ["m1"]  # existing keys preserved


def test_absent_provenance_gets_both_keys():
    prov = _envelope_card_present({"card_id": "c", "summary": {}, "interpretation_call": "x"})["provenance"]
    assert prov == {"method_calls": [], "input_manifest_ids": []}


def test_existing_method_calls_not_clobbered():
    card = {"card_id": "c", "summary": {}, "interpretation_call": "x",
            "provenance": {"method_calls": [{"module": "m"}], "input_manifest_ids": []}}
    assert _envelope_card_present(card)["provenance"]["method_calls"] == [{"module": "m"}]
