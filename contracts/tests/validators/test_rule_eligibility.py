"""Tests for RULE_INELIGIBLE_FIELD (validate_interpretation_rules.py, Check 3a.5).

The framework's resolver is Turing-incomplete: interpretation rules pattern-match DERIVED CLASS
tokens a card's Python already computed, never raw numbers (a cut on a number is applied upstream
and declared in threshold_roles). This check CI-enforces that narrow waist — a rule that
equality-matches a field the card declares NUMERIC in summary_fields_scalar_types is a category
error and must ERROR.

MEASURED at authoring: 0 of 128 rule-read (card, field) pairs are declared numeric, so this fires
0× on production (a NULL DIFF). That makes the check invisible on real data — so the mutation tests
below (a synthetic numeric-typed field DOES fire) are load-bearing: without them the check would be
indistinguishable from decoration (the CR-R2 vacuity trap).

Hermetic: fabricates cards + rules in tmp_path, validates against the real rules schema.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "validate_interpretation_rules",
        REPO / "validators" / "validate_interpretation_rules.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["validate_interpretation_rules"] = mod
    spec.loader.exec_module(mod)
    return mod


V = _load()


def _cards_dir(tmp: Path, *, scalar_type: str, with_vocab: bool = False) -> Path:
    """A synthetic cards/ holding one card that emits `metric_field` with the given scalar type."""
    d = tmp / "cards"
    d.mkdir(exist_ok=True)
    outputs: dict = {
        "summary_fields": ["metric_field"],
        "summary_fields_scalar_types": {"metric_field": scalar_type},
    }
    if with_vocab:
        outputs["summary_fields_vocabulary"] = {"metric_field": ["low", "high"]}
    card = {"card_id": "synthetic-card", "outputs": outputs}
    (d / "synthetic-card.card.yaml").write_text(yaml.safe_dump(card))
    return d


def _rules_file(tmp: Path, rule: dict) -> Path:
    doc = {
        "rules_id": "test",
        "version": "1.0.0",
        "axis": "intracellular_intrinsic",
        "schema_version": 1,
        "rules": [rule],
    }
    p = tmp / "test.rules.yaml"
    p.write_text(yaml.safe_dump(doc))
    return p


def _equals_rule(value="high") -> dict:
    return {
        "rule_id": "t-eligibility",
        "when": {"card_id": "synthetic-card", "field": "metric_field", "equals": value},
        "signals": {"axis_fit": "supportive"},
    }


# ── the mutation / non-vacuity proof: the check MUST fire on a numeric-typed field ──────────────
@pytest.mark.parametrize("numeric_type", ["number", "integer", "float"])
def test_equals_on_numeric_field_is_ineligible(tmp_path, numeric_type):
    cards = _cards_dir(tmp_path, scalar_type=numeric_type, with_vocab=True)
    rep = V.validate_rules_file(_rules_file(tmp_path, _equals_rule(value="high")), cards)
    assert not rep.ok
    assert any("RULE_INELIGIBLE_FIELD" in e for e in rep.errors), rep.errors


def test_in_operand_on_numeric_field_is_ineligible(tmp_path):
    cards = _cards_dir(tmp_path, scalar_type="number", with_vocab=True)
    rule = _equals_rule()
    del rule["when"]["equals"]
    rule["when"]["in"] = ["low", "high"]
    rep = V.validate_rules_file(_rules_file(tmp_path, rule), cards)
    assert not rep.ok
    assert any("RULE_INELIGIBLE_FIELD" in e for e in rep.errors), rep.errors


# ── specificity / positive control: a STRING-typed field is eligible (does NOT fire) ────────────
def test_equals_on_string_field_is_eligible(tmp_path):
    cards = _cards_dir(tmp_path, scalar_type="string", with_vocab=True)
    rep = V.validate_rules_file(_rules_file(tmp_path, _equals_rule()), cards)
    assert rep.ok, rep.errors
    assert not any("RULE_INELIGIBLE_FIELD" in e for e in rep.errors)


def test_boolean_field_is_eligible(tmp_path):
    # bool fields (true/false) are legitimate rule operands — not numeric scalars.
    cards = _cards_dir(tmp_path, scalar_type="boolean", with_vocab=True)
    rule = _equals_rule(value="true")
    rep = V.validate_rules_file(_rules_file(tmp_path, rule), cards)
    assert not any("RULE_INELIGIBLE_FIELD" in e for e in rep.errors), rep.errors


# ── the production NULL DIFF guard: 0 of the shipped rules key on a numeric field ───────────────
def test_production_rules_have_zero_ineligible_fields():
    cards = REPO / "cards"
    rules_dir = REPO / "interpretation-rules"
    offenders: list[str] = []
    for rules_path in sorted(rules_dir.glob("*.rules.yaml")):
        rep = V.validate_rules_file(rules_path, cards)
        offenders += [e for e in rep.errors if "RULE_INELIGIBLE_FIELD" in e]
    assert offenders == [], f"a shipped rule keys on a numeric field: {offenders}"
