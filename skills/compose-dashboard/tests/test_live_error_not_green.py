"""T3 (2026-08-11 engineering review): a live reader that RAISED must NOT emit a green card.

The dispatch layer (_live_readers.read_live_summary) catches all reader exceptions and
returns a truthy sentinel dict {"_live_read_error": "<detail>"}. Before this fix, pure
`live` mode (execution_mode="live") did NOT inspect that sentinel — only the
`live-stub-fallback` branch did — so the error dict was a non-None `summary` that flowed
past the `if summary is None` guard, through _evaluate_interpretation_hints, and was emitted
as a validation_state:"pass" card. A crashed method thus produced a GREEN verdict.

These tests pin the fix: in ALL live modes an `_live_read_error` sentinel routes the card to
a first-class card_unavailable stub (availability_state="read_error"), counts toward
n_cards_failed, and never appears in the interpretable card_outputs stream as a pass.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR.parent))

from scripts import _execution  # noqa: E402

# A real, on-disk, wired card so load_card_spec() inside execute_run_plan succeeds.
_WIRED_CARD = "tumor-vs-normal-selectivity"


def _run_plan_one_card(card_id: str = _WIRED_CARD) -> dict:
    return {
        "input_context": {
            "target_symbol": "KRAS", "indication": "COADREAD",
            "data_mode": "exploratory", "release_pin": None,
        },
        "subgroup_resolution": {},
        "card_run_plan": {
            "to_run": [{"card_id": card_id, "card_version": "1.0.0",
                        "applied_threshold_overlays": {}, "method_invocations": []}],
            "excluded_at_compose": [],
            "failed_at_compose": [],
        },
    }


def test_live_reader_exception_is_not_a_pass(monkeypatch):
    """A dispatcher error dict in pure `live` mode → read_error unavailable stub, not a pass."""
    monkeypatch.setattr(
        _execution, "_read_live_summary",
        lambda *a, **k: {"_live_read_error": "boom: simulated reader crash"},
    )
    result = _execution.execute_run_plan(_run_plan_one_card(), execution_mode="live")

    # The card must NOT appear in the interpretable card_outputs stream at all...
    assert all(c["card_id"] != _WIRED_CARD for c in result["cards"]), (
        "an errored live read leaked into card_outputs — it must be a reasoned absence"
    )
    # ...and certainly not as a pass.
    assert all(c.get("validation_state") != "pass" or c["card_id"] != _WIRED_CARD
               for c in result["cards"])

    # It must be a first-class card_unavailable stub with availability_state=read_error.
    unavail = {c["card_id"]: c for c in result["unavailable_cards"]}
    assert _WIRED_CARD in unavail, "errored card missing from unavailable_cards"
    assert unavail[_WIRED_CARD]["availability_state"] == "read_error"
    assert "boom" in unavail[_WIRED_CARD]["availability_reason"]
    assert result["validation_summary"]["n_cards_failed"] == 1
    assert result["validation_summary"]["n_cards_passed"] == 0


def test_live_stub_fallback_error_never_becomes_a_pass(monkeypatch):
    """In live-stub-fallback with NO stub fixture available, an errored live read must still
    never emit a pass. (The stub fallback exhausts to None → not_wired here, which is the
    honest state: both live AND stub produced nothing. The invariant under test is 'never a
    green card', regardless of which reasoned-absence state it lands in.)"""
    monkeypatch.setattr(
        _execution, "_read_live_summary",
        lambda *a, **k: {"_live_read_error": "s3_read_failed"},
    )
    # Point fixtures_dir at an empty dir so the stub fallback finds nothing.
    empty = Path("/tmp/__nonexistent_fixtures__")
    result = _execution.execute_run_plan(
        _run_plan_one_card(), execution_mode="live-stub-fallback", fixtures_dir=empty,
    )
    # The card is a reasoned absence (read_error if the sentinel survived, or not_wired if the
    # fallback resolved it to None) — but NEVER a present/pass card_output.
    assert all(c["card_id"] != _WIRED_CARD for c in result["cards"]), (
        "an errored live read leaked into card_outputs in fallback mode"
    )
    unavail = {c["card_id"]: c for c in result["unavailable_cards"]}
    assert _WIRED_CARD in unavail
    assert unavail[_WIRED_CARD]["availability_state"] in ("read_error", "not_wired")
    assert result["validation_summary"]["n_cards_passed"] == 0
