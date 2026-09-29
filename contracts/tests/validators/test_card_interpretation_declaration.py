"""Tests for the `interpretation:` declaration check in validate_cards.py.

A card only reaches a verdict if some rule in interpretation-rules/*.rules.yaml names it via
`when.card_id`. 57 of 148 cards are named by no rule, and before this check they were ONE
undifferentiated bucket — a card that deliberately emits context only was indistinguishable from a
card computing a categorical judgement nothing consumes, so the health feed could not report
interpretation debt. `interpretation:` is REQUIRED exactly when no rule keys on the card and
FORBIDDEN when rules exist.

Hermetic: the rule-bearing set (`_card_modality_signals`) is monkeypatched in every test, so nothing
here depends on the live rules corpus — a test that read the real corpus would flip meaning the first
time someone authored a rule for the synthetic card id, and would silently stop exercising the
rule-less branch.
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

CARD_ID = "synthetic-test-card"


def _base_card(with_vocabulary: bool, **overrides) -> dict:
    outputs: dict = {"summary_fields": ["median_chronos_panel", "dependency_class"]}
    if with_vocabulary:
        outputs["summary_fields_vocabulary"] = {"dependency_class": ["strong", "weak", "data_unavailable"]}
    card = {
        "card_id": CARD_ID,
        "version": "1.0.0",
        "question": "Synthetic card question for {target.symbol} in {indication.label}?",
        "applies_when": ["target.depmap_screened == true"],
        "required_inputs": [{"product_id": "some-manifest-v1"}],
        "methods": [{"call": "depmap-chronos"}],
        "outputs": outputs,
        "caveats": ["A caveat long enough to satisfy the minLength constraint."],
        "schema_version": 1,
    }
    card.update(overrides)
    return card


def _validate(tmp_path: Path, monkeypatch, card: dict, *, rule_bearing) -> "VC.ValidationReport":
    """`rule_bearing` mirrors _card_modality_signals(): {card_id -> modality signal set}, and a card
    with NO rule is ABSENT from the mapping (that absence is what the check keys on). Pass None to
    simulate a checkout with no interpretation-rules/ directory."""
    p = tmp_path / "synthetic.card.yaml"
    p.write_text(yaml.safe_dump(card))
    monkeypatch.setattr(VC, "_card_modality_signals", lambda: rule_bearing)
    return VC.validate_card_file(p)


def _warns(r) -> str:
    return "\n".join(r.warnings)


def _errs(r) -> str:
    return "\n".join(r.errors)


# --- the required-declaration branch -------------------------------------------------------------


def test_rule_less_card_without_a_declaration_warns(tmp_path, monkeypatch):
    """The gap this check exists to close: no rule names the card, and the card is silent about it."""
    r = _validate(tmp_path, monkeypatch, _base_card(True), rule_bearing={})
    assert r.ok, _errs(r)  # WARNING, not an error — undeclared intent is debt, not a schema violation
    assert "INTERPRETATION_UNDECLARED" in _warns(r)


def test_rules_pending_declaration_is_clean(tmp_path, monkeypatch):
    r = _validate(tmp_path, monkeypatch, _base_card(True, interpretation="rules_pending"), rule_bearing={})
    assert r.ok, _errs(r)
    assert "INTERPRETATION_" not in _warns(r)


def test_informational_declaration_is_clean(tmp_path, monkeypatch):
    r = _validate(tmp_path, monkeypatch, _base_card(True, interpretation="informational"), rule_bearing={})
    assert r.ok, _errs(r)
    assert "INTERPRETATION_" not in _warns(r)


def test_descriptive_declaration_is_clean_without_a_vocabulary(tmp_path, monkeypatch):
    r = _validate(tmp_path, monkeypatch, _base_card(False, interpretation="descriptive"), rule_bearing={})
    assert r.ok, _errs(r)
    assert "INTERPRETATION_" not in _warns(r)


# --- fail-closed in both directions --------------------------------------------------------------


def test_descriptive_contradicted_by_a_declared_vocabulary_errors(tmp_path, monkeypatch):
    """'descriptive' asserts there is nothing for a rule's equals:/in: to match. A declared
    vocabulary is exactly such a thing, so the pair is a contradiction — the author means either
    'informational' (bears no verdict by intent) or 'rules_pending' (owes one)."""
    r = _validate(tmp_path, monkeypatch, _base_card(True, interpretation="descriptive"), rule_bearing={})
    assert not r.ok
    assert "INTERPRETATION_CONTRADICTED" in _errs(r)
    assert "dependency_class" in _errs(r)


def test_rules_pending_without_a_vocabulary_errors(tmp_path, monkeypatch):
    """Symmetric direction: claiming the card owes rules while declaring no enumerated class means
    there is no value a rule could key on, so the debt as stated is not actionable."""
    r = _validate(tmp_path, monkeypatch, _base_card(False, interpretation="rules_pending"), rule_bearing={})
    assert not r.ok
    assert "INTERPRETATION_CONTRADICTED" in _errs(r)


def test_informational_without_a_vocabulary_errors(tmp_path, monkeypatch):
    r = _validate(tmp_path, monkeypatch, _base_card(False, interpretation="informational"), rule_bearing={})
    assert not r.ok
    assert "INTERPRETATION_CONTRADICTED" in _errs(r)


def test_declaring_intent_on_a_rule_bearing_card_errors(tmp_path, monkeypatch):
    """The rules ARE the ground truth. A declaration next to them can only contradict them, so it is
    forbidden rather than merely redundant — otherwise `interpretation: descriptive` could sit on a
    card whose rules actively move a verdict."""
    card = _base_card(True, interpretation="descriptive")
    r = _validate(tmp_path, monkeypatch, card, rule_bearing={CARD_ID: {"small_molecule"}})
    assert not r.ok
    assert "INTERPRETATION_DECLARED_WITH_RULES" in _errs(r)


def test_rule_bearing_card_without_a_declaration_is_clean(tmp_path, monkeypatch):
    """The 91 rule-bearing cards must stay untouched — the check must not demand the field of them."""
    r = _validate(tmp_path, monkeypatch, _base_card(True), rule_bearing={CARD_ID: set()})
    assert r.ok, _errs(r)
    assert "INTERPRETATION_" not in _warns(r)


# --- graceful skip --------------------------------------------------------------------------------


def test_absent_rules_directory_skips_the_check(tmp_path, monkeypatch):
    """With no rules corpus to read, EVERY card looks rule-less and the check would fire 148 times on
    a checkout-only runner. Mirrors the other cross-ref checks' graceful-skip."""
    r = _validate(tmp_path, monkeypatch, _base_card(True), rule_bearing=None)
    assert r.ok, _errs(r)
    assert "INTERPRETATION_" not in _warns(r)


# --- the real corpus ------------------------------------------------------------------------------


def test_every_live_card_is_classified_and_consistent():
    """Ratchet against the live repo: no rule-less card may be undeclared, and no rule-bearing card
    may carry the field. This is what keeps the debt count honest as cards and rules are added —
    a new rule-less card fails here rather than joining an invisible bucket."""
    rule_bearing = set()
    for f in sorted((REPO / "interpretation-rules").glob("*.rules.yaml")):
        for rule in (yaml.safe_load(f.read_text()) or {}).get("rules") or []:
            cid = (rule.get("when") or {}).get("card_id")
            if cid:
                rule_bearing.add(cid)
    assert rule_bearing, "no rules parsed — the linkage key is when.card_id, not a top-level card_id"

    undeclared, wrongly_declared, counts = [], [], {}
    for p in sorted((REPO / "cards").glob("*.card.yaml")):
        doc = yaml.safe_load(p.read_text()) or {}
        cid, declared = doc["card_id"], doc.get("interpretation")
        if cid in rule_bearing:
            if declared is not None:
                wrongly_declared.append(cid)
        elif declared is None:
            undeclared.append(cid)
        else:
            counts[declared] = counts.get(declared, 0) + 1

    assert not undeclared, f"rule-less cards missing interpretation:: {undeclared}"
    assert not wrongly_declared, f"rule-bearing cards carrying interpretation:: {wrongly_declared}"
    assert set(counts) <= VC._INTERPRETATION_DECLARATIONS, counts
    n_rule_less = sum(
        1 for c in (REPO / "cards").glob("*.card.yaml") if yaml.safe_load(c.read_text())["card_id"] not in rule_bearing
    )
    # The debt meter is fully partitioned: every rule-less card lands in exactly one bucket.
    # rules_pending is expected to SHRINK as rules are authored, so assert the partition, not a number.
    assert sum(counts.values()) == n_rule_less, counts
