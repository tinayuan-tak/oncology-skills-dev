"""Unit tests for the co-emission fired-set enumerator (D5, 2026-08-09).

Guards the enumerator itself (coemission.py) — the golden harness relies on it to decide which
fired-sets are physically possible, so its grouping + soundness rules must be pinned independently
of any live rules file. Uses synthetic rule-indices (no target-contracts dependency here) plus one
live smoke against the real rules to catch a rules-file that becomes ungroupable.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from _skills_common.paths import TARGET_CONTRACTS_ROOT_DEFAULT
from _test_support import load_module

SKILLS = Path(__file__).resolve().parents[2]

CO = load_module(SKILLS / "_skills_common" / "tests" / "coemission.py", "coemission_ut")


def _idx(**rules):
    """rule_id -> (card, field, value_set). rules given as rid=(card, field, [values])."""
    return {rid: (c, f, frozenset(v)) for rid, (c, f, v) in rules.items()}


def test_two_disjoint_equals_on_one_field_form_a_group():
    idx = _idx(a=("cardX", "f", ["v1"]), b=("cardX", "f", ["v2"]), c=("cardY", "g", ["w"]))
    groups, free = CO.build_exclusivity_groups(["a", "b", "c"], idx)
    assert groups == [["a", "b"]]
    assert free == ["c"]


def test_group_members_never_coemit_but_field_can_be_none():
    idx = _idx(a=("cardX", "f", ["v1"]), b=("cardX", "f", ["v2"]), c=("cardY", "g", ["w"]))
    sets = CO.coemission_fired_sets_for_gate(["a", "b", "c"], idx)
    # 3 group states (none / a / b) x 2 free states (off / on c) = 6
    assert len(sets) == 6
    assert frozenset() in sets  # field takes an unmatched value AND c off
    assert frozenset(["a", "b"]) not in sets  # a,b mutually exclusive -> never co-emit
    assert frozenset(["a", "c"]) in sets  # cross-group co-emission is fine


def test_lone_value_rule_on_its_own_field_is_free():
    # a single rule on a (card,field) is not a group -> toggles freely
    idx = _idx(a=("cardX", "f", ["v1"]), b=("cardY", "g", ["w"]))
    groups, free = CO.build_exclusivity_groups(["a", "b"], idx)
    assert groups == []
    assert set(free) == {"a", "b"}
    sets = CO.coemission_fired_sets_for_gate(["a", "b"], idx)
    assert len(sets) == 4  # full 2^2 — both independent


def test_in_and_equals_on_same_field_group_if_disjoint():
    # an `in:` rule (value-set) and an `equals:` rule on the SAME field group iff disjoint
    idx = _idx(a=("cardX", "f", ["v1", "v2"]), b=("cardX", "f", ["v3"]))
    groups, free = CO.build_exclusivity_groups(["a", "b"], idx)
    assert groups == [["a", "b"]]
    assert free == []
    sets = CO.coemission_fired_sets_for_gate(["a", "b"], idx)
    assert sorted(sorted(s) for s in sets) == [[], ["a"], ["b"]]


def test_overlapping_value_sets_on_one_field_raise():
    # if two rules on one field could BOTH match some value, grouping is unsound -> raise
    idx = _idx(a=("cardX", "f", ["v1", "shared"]), b=("cardX", "f", ["shared", "v2"]))
    with pytest.raises(ValueError, match="value-sets overlap"):
        CO.build_exclusivity_groups(["a", "b"], idx)


def test_unknown_rule_id_raises():
    with pytest.raises(KeyError, match="not found"):
        CO.build_exclusivity_groups(["ghost"], {})


def test_non_value_condition_is_free_not_grouped():
    # a rule with no discrete value (value_set None) on a shared field is NOT grouped (can't pick a
    # winner by field value) -> stays free, conservatively keeping its combos
    idx = {"a": ("cardX", "f", frozenset(["v1"])), "b": ("cardX", "f", None)}
    groups, free = CO.build_exclusivity_groups(["a", "b"], idx)
    assert groups == []
    assert set(free) == {"a", "b"}


def test_live_rules_are_groupable():
    """Smoke: the REAL interpretation-rules must remain groupable (no overlapping value-sets on a
    shared field). If a future rules edit breaks this, the golden harness would raise — catch it here
    with a clearer message."""
    contracts = Path(os.environ.get("TARGET_CONTRACTS_ROOT", TARGET_CONTRACTS_ROOT_DEFAULT))
    if not (contracts / "interpretation-rules").is_dir():
        pytest.skip("target-contracts interpretation-rules not available")
    idx = CO.load_rule_index(contracts)
    resolvers = sorted((contracts / "resolvers").glob("*.resolver.yaml"))
    assert resolvers, "no resolver specs found"
    import yaml

    for spec_path in resolvers:
        spec = yaml.safe_load(spec_path.read_text())
        rule_ids = sorted(
            {rung.get("when_fired") for rung in spec.get("resolve", []) if rung.get("when_fired")} & set(idx)
        )
        # build_exclusivity_groups must not raise for any shipped gate's known rule_ids
        CO.build_exclusivity_groups(rule_ids, idx)
