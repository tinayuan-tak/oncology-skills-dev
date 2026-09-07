"""Tests for the blocked-subtype status-honesty check in validate_cards.py (C3, 2026-08-15).

A `tier: subtype` card whose subgroup_stratification.status == blocked_needs_per_sample_reader cannot
be LIVE (its whole identity is the per-subgroup panorama, which is blocked), so it MUST declare an
explicit non-`wired` top-level status — an OMITTED status defaults to `wired` and would falsely claim
liveness to the required-cards gate. The check is scoped to `tier: subtype` on purpose: the SAME
blocked stratification status appears on `tier: indication` POOLED cards where only the optional
subgroup FEATURE is blocked and the card is genuinely live (tumor-rna-vs-adjacent, etc.).

Hermetic synthetic cards + a guard on the real subgroup-stratified-expression card.
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

_BLOCKED = {"eligible": True, "status": "blocked_needs_per_sample_reader"}


def _base_card(**overrides) -> dict:
    c = {
        "card_id": "synthetic-subtype-card",
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


def _validate(tmp_path: Path, card: dict):
    p = tmp_path / "s.card.yaml"
    p.write_text(yaml.safe_dump(card))
    return VC.validate_card_file(p)


def _errs(r) -> str:
    return "\n".join(r.errors)


def test_subtype_blocked_without_status_errors(tmp_path):
    r = _validate(tmp_path, _base_card(tier="subtype", subgroup_stratification=_BLOCKED))
    assert not r.ok
    assert "BLOCKED_SUBTYPE_STATUS" in _errs(r)


def test_subtype_blocked_with_wired_status_errors(tmp_path):
    # explicit `wired` is the same false claim as the default
    r = _validate(tmp_path, _base_card(tier="subtype", status="wired", subgroup_stratification=_BLOCKED))
    assert not r.ok
    assert "BLOCKED_SUBTYPE_STATUS" in _errs(r)


def test_subtype_blocked_with_dormant_status_is_clean(tmp_path):
    r = _validate(tmp_path, _base_card(tier="subtype", status="dormant_pending_data", subgroup_stratification=_BLOCKED))
    assert "BLOCKED_SUBTYPE_STATUS" not in _errs(r)


def test_subtype_blocked_with_placeholder_status_is_clean(tmp_path):
    r = _validate(
        tmp_path, _base_card(tier="subtype", status="placeholder_not_wired", subgroup_stratification=_BLOCKED)
    )
    assert "BLOCKED_SUBTYPE_STATUS" not in _errs(r)


def test_indication_pooled_blocked_card_not_flagged(tmp_path):
    """The live-pooled-card guard: a tier:indication card with blocked stratification is genuinely
    live (only the optional subgroup feature is blocked) and must NOT be forced non-wired."""
    r = _validate(tmp_path, _base_card(tier="indication", subgroup_stratification=_BLOCKED))
    assert "BLOCKED_SUBTYPE_STATUS" not in _errs(r)


def test_real_subgroup_stratified_expression_declares_nonwired_status():
    """Regression guard on the shipped card: it must carry an explicit non-wired status."""
    doc = yaml.safe_load((REPO / "cards" / "subgroup-stratified-expression.card.yaml").read_text())
    assert doc.get("subgroup_stratification", {}).get("status") == "blocked_needs_per_sample_reader"
    assert doc.get("status") in {"dormant_pending_data", "placeholder_not_wired"}, (
        "blocked subtype-tier card must declare an explicit non-wired status"
    )
