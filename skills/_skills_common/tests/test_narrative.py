"""Unit tests for the per-verdict narrative assembler (narrative.py) and the rule_text_index path.

Hermetic: builds a tiny resolver spec + a tiny interpretation-rules file on disk (tmp_path), so the
tests do not depend on the live target-contracts content (which shifts). Covers: movers (driver +
same-direction referenced-present), dissenters (opposing-sign fired non-driver, per channel), the
counterfactual flip_conditions incl. a NON-fired rule captioned from the index, rule_sentences
precedence (fired-inline over index), the modality channel filter, determinism, and non-mutation.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

SKILLS = Path(__file__).resolve().parents[2]   # .../skills
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.narrative import build_narrative          # noqa: E402
from _skills_common.rules_loader import rule_text_index       # noqa: E402


# ---- fixture: a gate "g" with a veto rung above a positive rung, and a rules file carrying the
# human text (rationale/killer_message) for every rule_id — including opp-rule (a fired dissenter
# not referenced by the resolver) and veto-rule (referenced but NOT fired: a counterfactual).
_SPEC = {
    "default": "D",
    "resolve": [
        {"when_fired": "veto-rule", "verdict": "the_veto"},
        {"when_fired": "pos-rule", "verdict": "the_positive"},
    ],
}
_RULES = {
    "axis": "test_axis",
    "rules_id": "test",
    "rules": [
        {"rule_id": "pos-rule", "when": {"card_id": "cA", "field": "f", "equals": "x"},
         "signals": {"small_molecule": "supportive"}, "rationale": "Pos file rationale"},
        {"rule_id": "veto-rule", "when": {"card_id": "cB", "field": "f", "equals": "y"},
         "signals": {"small_molecule": "killer", "degrader": "killer"},
         "killer_message": "Veto!", "rationale": "Veto rationale"},
        {"rule_id": "opp-rule", "when": {"card_id": "cC", "field": "f", "equals": "z"},
         "signals": {"small_molecule": "opposing"}, "rationale": "Opp rationale"},
    ],
}


def _write_contracts(root: Path) -> None:
    (root / "resolvers").mkdir(parents=True, exist_ok=True)
    (root / "resolvers" / "g.resolver.yaml").write_text(yaml.safe_dump(_SPEC))
    (root / "interpretation-rules").mkdir(parents=True, exist_ok=True)
    (root / "interpretation-rules" / "test-axis.rules.yaml").write_text(yaml.safe_dump(_RULES))


def _fired():
    # pos-rule fired (drives the_positive) with an INLINE rationale that must win over the file text;
    # opp-rule fired but NOT a resolver rung -> a pure signal dissenter.
    return [
        {"rule_id": "pos-rule", "card_id": "cA", "signals": {"small_molecule": "supportive"},
         "rationale": "Pos inline rationale", "killer_message": None},
        {"rule_id": "opp-rule", "card_id": "cC", "signals": {"small_molecule": "opposing"},
         "rationale": "Opp inline", "killer_message": None},
    ]


@pytest.fixture()
def contracts(tmp_path):
    _write_contracts(tmp_path)
    rule_text_index.cache_clear()   # the index is lru_cached on the path arg; keep tests isolated
    yield tmp_path
    rule_text_index.cache_clear()


def _build(contracts, **kw):
    return build_narrative(axis="test_axis", gate="g", fired=_fired(),
                           verdict="the_positive", driving_rule_id="pos-rule",
                           contracts_repo=contracts, **kw)


def test_movers_are_driver_only_here(contracts):
    n = _build(contracts)
    assert [m["rule_id"] for m in n["movers"]] == ["pos-rule"]
    assert n["movers"][0]["role"] == "driver"
    # opp-rule is a pure opposer (not referenced) -> NOT a mover; veto-rule is not fired -> NOT a mover.


def test_dissenters_are_opposing_sign_fired_nondrivers(contracts):
    n = _build(contracts)
    assert n["dissenters"] == [{
        "rule_id": "opp-rule", "card_id": "cC", "channel": "small_molecule",
        "signal": "opposing", "sentence": "Opp inline", "killer_message": None,
    }]


def test_flip_conditions_include_absent_counterfactual(contracts):
    n = _build(contracts)
    flips = {f["rule_id"]: f for f in n["flip_conditions"]}
    # adding the absent veto-rule flips -> the_veto; removing the present pos-rule flips -> default D.
    assert set(flips) == {"veto-rule", "pos-rule"}
    assert flips["veto-rule"]["present"] is False
    assert flips["veto-rule"]["to_verdict"] == "the_veto"
    assert flips["pos-rule"]["present"] is True
    assert flips["pos-rule"]["to_verdict"] == "D"


def test_rule_sentences_cover_nonfired_rule_from_index(contracts):
    n = _build(contracts)
    # veto-rule never fired, so its text can only come from rule_text_index.
    assert n["rule_sentences"]["veto-rule"]["rationale"] == "Veto rationale"
    assert n["rule_sentences"]["veto-rule"]["killer_message"] == "Veto!"
    # pos-rule fired -> the INLINE rationale wins over the file's "Pos file rationale".
    assert n["rule_sentences"]["pos-rule"]["rationale"] == "Pos inline rationale"


def test_modality_filter_scopes_dissenters(contracts):
    # opp-rule dissents only on small_molecule; filtering to "degrader" yields no dissenters.
    n = _build(contracts, modality="degrader")
    assert n["dissenters"] == []


def test_rule_text_index_indexes_all_rules_including_nonfiring(contracts):
    idx = rule_text_index(contracts)
    assert set(idx) == {"pos-rule", "veto-rule", "opp-rule"}
    assert idx["veto-rule"]["card_id"] == "cB"
    assert idx["opp-rule"]["axis"] == "test_axis"


def test_deterministic_and_nonmutating(contracts):
    fired = _fired()
    before = [dict(f) for f in fired]
    a = build_narrative(axis="test_axis", gate="g", fired=fired, verdict="the_positive",
                        driving_rule_id="pos-rule", contracts_repo=contracts)
    b = build_narrative(axis="test_axis", gate="g", fired=fired, verdict="the_positive",
                        driving_rule_id="pos-rule", contracts_repo=contracts)
    assert a == b
    assert fired == before   # verdict-INERT / read-only


def test_gateless_skill_reduces_to_driver_no_flips(contracts):
    n = build_narrative(axis="test_axis", gate=None, fired=_fired(), verdict="the_positive",
                        driving_rule_id="pos-rule", contracts_repo=contracts)
    assert [m["rule_id"] for m in n["movers"]] == ["pos-rule"]
    assert n["flip_conditions"] == []          # no gate -> flips inapplicable
    assert n["dissenters"][0]["rule_id"] == "opp-rule"   # signal dissent still computed
