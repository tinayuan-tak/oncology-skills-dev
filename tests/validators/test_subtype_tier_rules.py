"""Tests for the subtype-tier rule discipline in validate_interpretation_rules.py.

The verdict-affecting subtype layer (2026-07-17) adds a `tier: subtype` rule that
matches per-subgroup records via `in_record`. These tests lock the guardrail:

  - a subtype-tier rule MUST declare subgroup_metadata_declared,
  - it MUST match records via when.in_record (not scalar equals/in),
  - its in_record MUST pin subgroup_n_floor_met: true (the admissibility guard —
    an underpowered stratum must not be able to fire a verdict-affecting rule),
  - in_record keys are validated against the card's summary_fields_record_schemas.

Also asserts the shipped subtype-non-dependence-opposing rule validates clean.
Hermetic: fabricates rules in tmp + validates against the real schema + cards/.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "validate_interpretation_rules",
        REPO / "validators" / "validate_interpretation_rules.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["validate_interpretation_rules"] = mod  # register so @dataclass resolves
    spec.loader.exec_module(mod)
    return mod


V = _load()
CARDS = REPO / "cards"


def _rules_file(tmp: Path, rule: dict) -> Path:
    doc = {
        "rules_id": "test", "version": "1.0.0",
        "axis": "intracellular_intrinsic", "schema_version": 1,
        "rules": [rule],
    }
    p = tmp / "test.rules.yaml"
    p.write_text(yaml.safe_dump(doc))
    return p


def _base_subtype_rule() -> dict:
    return {
        "rule_id": "t-subtype",
        "when": {
            "card_id": "subgroup-stratified-dependency",
            "field": "per_subgroup_metrics",
            "in_record": {"class": "not_dependent", "evidence_state": "measured",
                          "subgroup_n_floor_met": True},
        },
        "signals": {"subtype_fit_genomic": "opposing"},
        "tier": "subtype",
        "subgroup_metadata_declared": {"subtype_defining_data": "genomic"},
    }


def test_valid_subtype_rule_passes(tmp_path):
    rep = V.validate_rules_file(_rules_file(tmp_path, _base_subtype_rule()), CARDS)
    assert rep.ok, rep.errors


def test_subtype_rule_missing_floor_pin_fails(tmp_path):
    r = _base_subtype_rule()
    del r["when"]["in_record"]["subgroup_n_floor_met"]
    rep = V.validate_rules_file(_rules_file(tmp_path, r), CARDS)
    assert not rep.ok
    assert any("subgroup_n_floor_met: true" in e for e in rep.errors)


def test_subtype_rule_floor_pin_false_fails(tmp_path):
    r = _base_subtype_rule()
    r["when"]["in_record"]["subgroup_n_floor_met"] = False
    rep = V.validate_rules_file(_rules_file(tmp_path, r), CARDS)
    assert not rep.ok
    assert any("subgroup_n_floor_met: true" in e for e in rep.errors)


def test_subtype_rule_scalar_when_fails(tmp_path):
    r = _base_subtype_rule()
    r["when"] = {"card_id": "subgroup-stratified-dependency",
                 "field": "per_subgroup_metrics", "equals": "x"}
    rep = V.validate_rules_file(_rules_file(tmp_path, r), CARDS)
    assert not rep.ok
    assert any("must match per-subgroup records" in e for e in rep.errors)


def test_subtype_rule_missing_metadata_fails(tmp_path):
    r = _base_subtype_rule()
    del r["subgroup_metadata_declared"]
    rep = V.validate_rules_file(_rules_file(tmp_path, r), CARDS)
    assert not rep.ok
    assert any("subgroup_metadata_declared" in e for e in rep.errors)


def test_in_record_key_not_in_record_schema_fails(tmp_path):
    r = _base_subtype_rule()
    r["when"]["in_record"]["nonexistent_key"] = "x"
    rep = V.validate_rules_file(_rules_file(tmp_path, r), CARDS)
    assert not rep.ok
    assert any("nonexistent_key" in e for e in rep.errors)


def test_shipped_rules_files_validate_clean():
    """The real intracellular + surface rules files validate (0 errors) — the
    shipped subtype-non-dependence-opposing rule passes end-to-end."""
    for fname in ("intracellular-intrinsic.rules.yaml", "surface-intrinsic.rules.yaml"):
        rep = V.validate_rules_file(REPO / "interpretation-rules" / fname, CARDS)
        assert rep.ok, f"{fname}: {rep.errors}"


def test_shipped_subtype_rule_present():
    """The subtype-non-dependence-opposing rule exists in the intracellular file
    and carries the floor pin + metadata (regression against silent removal)."""
    doc = yaml.safe_load((REPO / "interpretation-rules" / "intracellular-intrinsic.rules.yaml").read_text())
    rule = next((r for r in doc["rules"] if r.get("rule_id") == "subtype-non-dependence-opposing"), None)
    assert rule is not None, "subtype-non-dependence-opposing rule missing"
    assert rule["tier"] == "subtype"
    assert rule["when"]["in_record"]["subgroup_n_floor_met"] is True
    assert rule["signals"]["subtype_fit_genomic"] == "opposing"
    assert rule["subgroup_metadata_declared"]["subtype_defining_data"] == "genomic"
