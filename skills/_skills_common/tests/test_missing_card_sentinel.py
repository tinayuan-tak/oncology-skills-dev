"""Regression tests for RP4 — dual missing-card sentinel canonicalization.

The root cause: _skills_common/__init__.py was translating `_missing` → `missing`
(no underscore) when assembling the output cards list. Downstream code in
dispatcher.py then defensively accepted both spellings via `or c.get("missing")`.

Fix: __init__.py emits `_missing` everywhere; dispatcher.py checks only `_missing`.
These tests verify both that the output dict carries `_missing` and that the
old bare `missing` arm is gone from dispatcher.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

COMMON_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMMON_DIR.parent))  # skills/

from _skills_common.dispatcher import _apply_on_dependency_status


# ---------------------------------------------------------------------------
# Test 1 — resolve_cards output carries _missing (not bare missing)
# ---------------------------------------------------------------------------

def _make_card(card_id: str, missing: bool) -> dict:
    """Build a card_output dict as resolve_cards produces internally."""
    return {
        "card_id": card_id,
        "summary": {} if missing else {"value": 42},
        "_missing": missing,
        "_missing_reason": "dispatcher_returned_none" if missing else None,
    }


def test_make_decision_json_emits_underscore_missing_key():
    """make_decision_json must emit `_missing` in the cards list, not bare `missing`.

    RP4 regression: the old code translated _missing → missing (bare) when
    assembling the output cards list in make_decision_json. The fix keeps `_missing`.
    """
    from _skills_common import make_decision_json

    card_outputs = [_make_card("card-x", missing=True)]

    result = make_decision_json(
        skill_name="test-skill",
        target="GENE",
        indication="NSCLC",
        question="Is GENE tractable?",
        card_outputs=card_outputs,
        fired=[],
        headline={"verdict": "insufficient"},
    )

    assert len(result["cards"]) == 1
    card = result["cards"][0]

    assert "_missing" in card, (
        "RP4 regression: `_missing` key absent — make_decision_json emitted bare `missing`"
    )
    assert card["_missing"] is True, f"Expected _missing=True, got {card['_missing']}"
    assert "missing" not in card, (
        "Bare `missing` key (no underscore) must not appear — `_missing` is canonical"
    )


def test_make_decision_json_present_card_has_missing_false():
    """A present card in the output dict must carry `_missing: False`."""
    from _skills_common import make_decision_json

    card_outputs = [_make_card("card-y", missing=False)]

    result = make_decision_json(
        skill_name="test-skill",
        target="GENE",
        indication="NSCLC",
        question="Is GENE tractable?",
        card_outputs=card_outputs,
        fired=[],
        headline={"verdict": "supportive"},
    )

    card = result["cards"][0]
    assert "_missing" in card
    assert card["_missing"] is False
    assert "missing" not in card


# ---------------------------------------------------------------------------
# Test 2 — dispatcher.py no longer accepts bare `missing` as sentinel
# ---------------------------------------------------------------------------

def test_apply_on_dependency_status_ignores_bare_missing():
    """_apply_on_dependency_status checks only `_missing`; bare `missing` is NOT a sentinel.

    A card with `missing: True` but no `_missing` key must be treated as *present*
    (the dual-key shim is gone). This test confirms the old shim is removed.
    """
    cards = [
        {"card_id": "card-present", "summary": {"v": 1}, "_missing": False},
        {"card_id": "card-old-style", "summary": {}, "missing": True},  # old format
    ]
    on_dep = {"card-old-style": "skip_section"}

    surviving, skipped, caveats = _apply_on_dependency_status(cards, on_dep)

    surviving_ids = {c["card_id"] for c in surviving}
    # card-old-style has only bare `missing`, not `_missing` — so it's NOT missing
    # under the new rule, and skip_section does not fire.
    assert "card-old-style" in surviving_ids, (
        "card-old-style should be treated as present (bare `missing` is not a sentinel)"
    )
    assert skipped == [], f"Nothing should be skipped; got {skipped}"


def test_apply_on_dependency_status_skips_underscore_missing():
    """_apply_on_dependency_status correctly skips a card with `_missing: True`."""
    cards = [
        {"card_id": "card-a", "summary": {"v": 1}, "_missing": False},
        {"card_id": "card-b", "summary": {}, "_missing": True},
    ]
    on_dep = {"card-b": "skip_section"}

    surviving, skipped, caveats = _apply_on_dependency_status(cards, on_dep)

    surviving_ids = {c["card_id"] for c in surviving}
    assert "card-a" in surviving_ids
    assert "card-b" not in surviving_ids
    assert skipped == ["card-b"]
