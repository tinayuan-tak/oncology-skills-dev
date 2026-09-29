"""immune-context — every DECLARED class token is READ by a rule (and no rule reads an undeclared one).

The bug this makes impossible: `lymphoid_denominator_unreliable` shipped in the card vocabulary and in
the reader, and NOTHING interpreted it. The card declared a fourth token, the reader could emit it, and
the rule corpus knew only three — so the token would have arrived at the skill, fired no rule, and
fallen through to a bare `insufficient` indistinguishable from "no cohort". Declaring a token is only
half of shipping it; the corpus has to have an opinion about it.

Read against the LIVE card + LIVE rules corpus on purpose. This is a claim about the real contract
(these two files agreeing), not about validator logic, and a hermetic version would pass while the
real pair drifted. `data_unavailable` is the one deliberate exception: "no cohort at all" is the
framework-wide abstention that fires nothing everywhere.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
CARD = REPO / "cards" / "immune-context.card.yaml"
RULES_DIR = REPO / "interpretation-rules"

_CARD_ID = "immune-context"
_FIELD = "immune_context_class"
# fires no rule ANYWHERE by convention — the generic "we have no cohort" abstention.
_NO_RULE_BY_DESIGN = {"data_unavailable"}


def _declared_vocabulary() -> set:
    card = yaml.safe_load(CARD.read_text())
    vocab = ((card.get("outputs") or {}).get("summary_fields_vocabulary") or {}).get(_FIELD)
    assert vocab, f"{CARD.name} declares no {_FIELD} vocabulary — reader/card drift"
    return set(vocab)


def _rule_covered_tokens() -> dict:
    """{token: rule_id} for every rule keyed on immune-context.immune_context_class."""
    out = {}
    for path in sorted(RULES_DIR.glob("*.rules.yaml")):
        doc = yaml.safe_load(path.read_text()) or {}
        for rule in doc.get("rules") or []:
            when = rule.get("when") or {}
            if when.get("card_id") == _CARD_ID and when.get("field") == _FIELD and "equals" in when:
                out[when["equals"]] = rule.get("rule_id")
    return out


def test_every_declared_class_token_is_read_by_a_rule():
    declared = _declared_vocabulary() - _NO_RULE_BY_DESIGN
    covered = set(_rule_covered_tokens())
    assert declared <= covered, (
        f"immune_context_class tokens declared on the card but read by NO rule: {sorted(declared - covered)} "
        f"— the token would reach the skill, fire nothing, and collapse onto a bare `insufficient`"
    )


def test_no_rule_reads_a_token_the_card_does_not_declare():
    """The other direction: a rule keyed on a token the reader can never emit is dead code that reads
    like coverage."""
    declared = _declared_vocabulary()
    covered = _rule_covered_tokens()
    orphans = {tok: rid for tok, rid in covered.items() if tok not in declared}
    assert not orphans, f"rules keyed on undeclared immune_context_class tokens: {orphans}"


def test_the_lymphoid_denominator_token_has_its_own_rule_and_is_not_opposing():
    """The specific token this guard was written for. It must be NEUTRAL: an uninterpretable denominator
    is an absent MEASUREMENT, not measured effector absence, and calling it `opposing` would manufacture
    a TCE risk signal in haematologic malignancy — where TCEs are the validated modality."""
    covered = _rule_covered_tokens()
    rid = covered.get("lymphoid_denominator_unreliable")
    assert rid, "lymphoid_denominator_unreliable is declared but no rule reads it"

    signals = {}
    for path in sorted(RULES_DIR.glob("*.rules.yaml")):
        for rule in (yaml.safe_load(path.read_text()) or {}).get("rules") or []:
            if rule.get("rule_id") == rid:
                signals = rule.get("signals") or {}
    assert signals.get("bite_tce") == "neutral", f"{rid} must signal bite_tce: neutral, got {signals}"


def test_the_card_admits_the_indications_that_reach_the_guard():
    """A guard nothing can reach is a guard that reassures without protecting. The lymphoid codes must be
    in applies_when, or the token is unreachable from any real query and no panel can falsify it."""
    card = yaml.safe_load(CARD.read_text())
    admitted = " ".join(card.get("applies_when") or [])
    for code in ("LAML", "AML", "DLBC", "DLBCL", "THYM"):
        assert f"'{code}'" in admitted, f"{code} not admitted by applies_when — the guard stays unreachable"
    # non-vacuity partner: TGCT is deliberately NOT guarded (seminoma has genuine brisk TIL, so its
    # leukocyte denominator is real infiltrate) and must not have been swept in with the lymphoid batch.
    assert "'TGCT'" not in admitted, "TGCT is not a lymphoid-denominator case; it does not belong here"
