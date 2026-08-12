"""F (2026-07-20): an UNWIRED card is a reasoned absence, not a silent drop.

Historically a card whose live reader returned None (no dispatcher registered — e.g. the
fusion-rearrangement-landscape placeholder) was dropped to a bare n_cards_failed integer
with NO per-card reason. Now compose-dashboard emits a structured card_unavailable envelope
entry carrying a typed availability_state, so a consumer can distinguish "not built yet"
from a measured absence.

These tests pin:
  1. the assembly path turns an `unavailable_cards` stub into a schema-valid card_unavailable
     envelope entry (and the assembled package still validates);
  2. the availability stub is kept OUT of the synthesis-input card_outputs stream (it has no
     signal to interpret) — proven by feeding it only via the separate param;
  3. the discriminator is unambiguous — the entry has availability_state, not validation_state
     or excluded_by_applies_when.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR.parent))
sys.path.insert(0, str(SCRIPTS_DIR.parent.parent))  # skills/ — for _skills_common

from _skills_common.envelope import assemble_evidence_package  # noqa: E402

CONTRACTS = Path(os.environ.get("TARGET_CONTRACTS_ROOT",
                                "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"))
PKG_SCHEMA = json.loads((CONTRACTS / "schemas" / "evidence_package.schema.json").read_text())


def _minimal_run_plan():
    return {
        "input_context": {
            "target_symbol": "KRAS", "indication": "COADREAD",
            "data_mode": "pinned", "release_pin": "2026-Q2",
        },
        "axis_resolution": {"status": "resolved", "resolved_axis": "intracellular_intrinsic"},
        "loaded_modality_modules": [],
    }


def _synthesis_block():
    return {"headline": "test headline over five chars", "caveats_summary": "",
            "modality_fit_assessment": []}


def _assemble(card_outputs, unavailable_cards):
    return assemble_evidence_package(
        run_plan=_minimal_run_plan(),
        card_outputs=card_outputs,
        validation_summary={"n_cards_attempted": len(card_outputs), "n_cards_passed": 0,
                            "n_cards_passed_with_warnings": 0,
                            "n_cards_failed": len(unavailable_cards),
                            "n_cards_excluded_by_applies_when": 0},
        synthesis_block=_synthesis_block(),
        deterministic_timestamps=True,
        framework_version="2.0.0",
        generated_by="skills/compose-dashboard@0000000",
        unavailable_cards=unavailable_cards,
    )


def test_unwired_card_becomes_card_unavailable_entry():
    ep = _assemble(card_outputs=[], unavailable_cards=[
        {"card_id": "fusion-rearrangement-landscape", "card_version": "0.1.0",
         "availability_state": "not_wired", "availability_reason": "dispatcher_returned_none"},
    ])
    entries = [c for c in ep["cards"] if c["card_id"] == "fusion-rearrangement-landscape"]
    assert len(entries) == 1, "the unwired card must appear as a reasoned absence, not vanish"
    e = entries[0]
    assert e["availability_state"] == "not_wired"
    assert e["availability_reason"] == "dispatcher_returned_none"
    # discriminator is unambiguous — NOT a present or excluded entry
    assert "validation_state" not in e
    assert "excluded_by_applies_when" not in e


def test_cards_array_with_card_unavailable_validates():
    """The cards[] array (present + unavailable coexisting) must validate against the
    updated evidence_package schema — proves the card_unavailable oneOf variant is admitted.
    Validates the cards[] sub-schema directly, so the assertion is scoped to what F changed
    (not incidental context fields like the hgnc_id=-1 sentinel a minimal fixture produces)."""
    ep = _assemble(
        card_outputs=[
            {"card_id": "tumor-vs-normal-selectivity", "card_version": "1.0.0",
             "validation_state": "pass", "summary": {"x": 1},
             "interpretation_call": "strong tumor selectivity",
             "provenance": {"method_calls": [], "input_manifest_ids": []}},
        ],
        unavailable_cards=[
            {"card_id": "fusion-rearrangement-landscape", "card_version": "0.1.0",
             "availability_state": "not_wired", "availability_reason": "dispatcher_returned_none"},
        ],
    )
    # Validate the cards[] array against its schema (the F-relevant surface).
    cards_schema = {**PKG_SCHEMA["properties"]["cards"], "$defs": PKG_SCHEMA["$defs"]}
    errors = sorted(e.message for e in Draft202012Validator(cards_schema).iter_errors(ep["cards"]))
    assert errors == [], f"cards[] failed schema validation: {errors}"
    # And no validation error anywhere in the package touches a cards[] entry.
    card_path_errors = [list(e.absolute_path) for e in Draft202012Validator(PKG_SCHEMA).iter_errors(ep)
                        if e.absolute_path and e.absolute_path[0] == "cards"]
    assert card_path_errors == [], f"cards[] entries produced schema errors: {card_path_errors}"
    # both a present card and an unavailable card coexist in cards[]
    states = {c["card_id"]: ("present" if "validation_state" in c
                             else "unavailable" if "availability_state" in c
                             else "excluded")
              for c in ep["cards"]}
    assert states["tumor-vs-normal-selectivity"] == "present"
    assert states["fusion-rearrangement-landscape"] == "unavailable"


def test_no_unavailable_cards_leaves_envelope_unchanged_shape():
    """Backward-compat: with no unavailable cards, cards[] contains only present/excluded
    entries exactly as before (F is purely additive)."""
    ep = _assemble(
        card_outputs=[
            {"card_id": "tumor-vs-normal-selectivity", "card_version": "1.0.0",
             "validation_state": "pass", "summary": {},
             "interpretation_call": "strong tumor selectivity",
             "provenance": {"method_calls": [], "input_manifest_ids": []}},
        ],
        unavailable_cards=[],
    )
    assert all("availability_state" not in c for c in ep["cards"])
    assert len(ep["cards"]) == 1
