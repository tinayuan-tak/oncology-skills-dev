"""Tests for the verdict-bearing summary-schema coverage RATCHET in validate_cards.py (TC1).

Every resolver-consumed (verdict-bearing) card must have a committed
schemas/methods/<card>.summary.schema.json — the method->card shape contract. This guards the ratchet:
missing schema on a verdict-bearing card -> [ERROR]; present -> clean; non-verdict-bearing card ->
exempt; absent snapshot -> graceful no-op. Hermetic: a synthetic repo layout in tmp_path.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load(mod_name: str):
    spec = importlib.util.spec_from_file_location(mod_name, REPO / "validators" / f"{mod_name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


VC = _load("validate_cards")


def _layout(tmp_path: Path, verdict_cards, card_files, schema_files, write_snapshot=True) -> Path:
    """Build <root>/{cards,coverage,schemas/methods} and return the cards dir."""
    cards = tmp_path / "cards"
    cards.mkdir()
    for c in card_files:
        (cards / f"{c}.card.yaml").write_text("card_id: " + c + "\n")
    methods = tmp_path / "schemas" / "methods"
    methods.mkdir(parents=True)
    for c in schema_files:
        (methods / f"{c}.summary.schema.json").write_text("{}")
    if write_snapshot:
        cov = tmp_path / "coverage"
        cov.mkdir()
        (cov / "card_resolver_consumption.yaml").write_text(
            "resolver_consumed_cards:\n" + "".join(f"- {c}\n" for c in verdict_cards)
        )
    return cards


def _errs(problems):
    return "\n".join(problems)


def test_missing_schema_on_verdict_card_is_error(tmp_path):
    cards = _layout(
        tmp_path, verdict_cards=["card-a", "card-b"], card_files=["card-a", "card-b"], schema_files=["card-a"]
    )  # card-b schema missing
    problems = VC.validate_verdict_card_summary_schema_coverage(cards)
    assert any("SUMMARY_SCHEMA_MISSING" in p and "card-b" in p for p in problems), _errs(problems)
    assert all("card-a" not in p for p in problems)  # card-a has its schema → not flagged
    assert all(p.startswith("[ERROR]") for p in problems)  # it's a hard error (ratchet)


def test_all_verdict_cards_with_schemas_is_clean(tmp_path):
    cards = _layout(
        tmp_path, verdict_cards=["card-a", "card-b"], card_files=["card-a", "card-b"], schema_files=["card-a", "card-b"]
    )
    assert VC.validate_verdict_card_summary_schema_coverage(cards) == []


def test_non_verdict_card_is_exempt(tmp_path):
    # card-x is NOT in resolver_consumed_cards → no schema required even though it exists as a card
    cards = _layout(tmp_path, verdict_cards=["card-a"], card_files=["card-a", "card-x"], schema_files=["card-a"])
    assert VC.validate_verdict_card_summary_schema_coverage(cards) == []


def test_snapshot_entry_without_card_file_is_skipped(tmp_path):
    # a stale snapshot entry with no card file is the resolver-consumption validator's concern, not ours
    cards = _layout(tmp_path, verdict_cards=["card-a", "ghost-card"], card_files=["card-a"], schema_files=["card-a"])
    assert VC.validate_verdict_card_summary_schema_coverage(cards) == []


def test_graceful_when_snapshot_absent(tmp_path):
    cards = _layout(tmp_path, verdict_cards=[], card_files=["card-a"], schema_files=[], write_snapshot=False)
    assert VC.validate_verdict_card_summary_schema_coverage(cards) == []


def test_real_repo_every_verdict_card_has_a_schema():
    """Integration: the shipped repo satisfies the ratchet (all resolver-consumed cards have schemas)."""
    problems = VC.validate_verdict_card_summary_schema_coverage(REPO / "cards")
    assert problems == [], "verdict-bearing cards missing summary schemas:\n" + _errs(problems)
