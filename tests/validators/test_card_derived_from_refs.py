"""Tests for the derived_from existence cross-check in validate_cards.py (C1, 2026-08-15).

A composed card's `derived_from[].card_id` must resolve to a LIVE card in cards/ OR to a historical
alias (`from` -> `to` in vocabularies/card_id_aliases.yaml whose target is live). An unresolvable
upstream is an ERROR — a composed card cannot read a card that does not exist. This is the existence
half of the reachability the schema advertises (the field-level half is not implemented; schema
description down-scoped to match).

Hermetic: synthetic card dirs written to tmp; the alias map is monkeypatched so the tests don't
depend on the vocab's evolving contents. One integration test asserts the REAL tree is clean.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def _load(mod_name: str):
    spec = importlib.util.spec_from_file_location(mod_name, REPO / "validators" / f"{mod_name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


VC = _load("validate_cards")


def _card(cid: str, **overrides) -> dict:
    c = {
        "card_id": cid,
        "version": "1.0.0",
        "question": "Question for {target.symbol} in {indication.label}?",
        "applies_when": ["true"],
        "required_inputs": [{"product_id": "some-product-v1"}],
        "methods": [{"call": "some-method"}],
        "outputs": {"summary_fields": ["some_field"]},
        "caveats": ["A caveat long enough to satisfy the minLength constraint."],
        "schema_version": 1,
    }
    c.update(overrides)
    return c


def _write(dir_path: Path, card: dict) -> None:
    (dir_path / f"{card['card_id']}.card.yaml").write_text(yaml.safe_dump(card))


def _composed(cid: str, upstream: list[str]) -> dict:
    # composed card: empty required_inputs is legal because derived_from is declared
    return _card(cid, required_inputs=[], derived_from=[{"card_id": u} for u in upstream])


def test_derived_from_to_live_card_is_clean(tmp_path, monkeypatch):
    monkeypatch.setattr(VC, "_card_id_aliases", lambda: {})
    _write(tmp_path, _card("upstream-card"))
    _write(tmp_path, _composed("downstream-card", ["upstream-card"]))
    assert VC.validate_derived_from_refs(tmp_path) == []


def test_derived_from_to_missing_card_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(VC, "_card_id_aliases", lambda: {})
    _write(tmp_path, _composed("downstream-card", ["does-not-exist"]))
    problems = VC.validate_derived_from_refs(tmp_path)
    assert any("does-not-exist" in p and p.startswith("[ERROR]") for p in problems), problems


def test_derived_from_via_alias_to_live_card_is_clean(tmp_path, monkeypatch):
    # old-id upstream resolves through the alias map to a live card
    monkeypatch.setattr(VC, "_card_id_aliases", lambda: {"old-name": "new-name"})
    _write(tmp_path, _card("new-name"))
    _write(tmp_path, _composed("downstream-card", ["old-name"]))
    assert VC.validate_derived_from_refs(tmp_path) == []


def test_derived_from_via_stale_alias_errors(tmp_path, monkeypatch):
    # alias exists but its target is NOT a live card -> stale alias error
    monkeypatch.setattr(VC, "_card_id_aliases", lambda: {"old-name": "also-missing"})
    _write(tmp_path, _composed("downstream-card", ["old-name"]))
    problems = VC.validate_derived_from_refs(tmp_path)
    assert any("historical alias" in p and "also-missing" in p for p in problems), problems


def test_real_cards_tree_has_no_derived_from_drift():
    """Regression guard: the shipped cards/ tree must have every derived_from reference resolvable
    (would have caught a rename-without-alias)."""
    problems = VC.validate_derived_from_refs(REPO / "cards")
    assert problems == [], "\n".join(problems)
