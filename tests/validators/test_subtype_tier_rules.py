"""Tests for the subtype-tier rule discipline in validate_interpretation_rules.py.

The verdict-affecting subtype layer (2026-07-17) adds a `tier: subtype` rule that
matches per-subgroup records via `in_record`. These tests lock the guardrail:

  - a subtype-tier rule MUST declare subgroup_metadata_declared,
  - it MUST match records via when.in_record (not scalar equals/in),
  - its in_record MUST pin an ADMISSIBILITY PREDICATE as true — one of
    {subgroup_n_floor_met, subgroup_effect_admissible} (the admissibility guard —
    an underpowered AND weak stratum must not be able to fire a verdict-affecting
    rule; a small-but-effect-admissible stratum MAY, via subgroup_effect_admissible),
  - in_record keys are validated against the card's summary_fields_record_schemas.

Also asserts the shipped subtype-non-dependence-opposing rule validates clean.
Hermetic: fabricates rules in tmp + validates against the real schema + cards/.
"""

from __future__ import annotations

import importlib.util
import sys
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


def test_subtype_rule_missing_any_admissibility_pin_fails(tmp_path):
    # No admissibility predicate at all → an underpowered stratum could fire. Reject.
    r = _base_subtype_rule()
    del r["when"]["in_record"]["subgroup_n_floor_met"]
    rep = V.validate_rules_file(_rules_file(tmp_path, r), CARDS)
    assert not rep.ok
    assert any("admissibility predicate" in e for e in rep.errors)


def test_subtype_rule_floor_pin_false_and_no_effect_admissible_fails(tmp_path):
    # floor explicitly false AND no effect-admissibility escape → still inadmissible.
    r = _base_subtype_rule()
    r["when"]["in_record"]["subgroup_n_floor_met"] = False
    rep = V.validate_rules_file(_rules_file(tmp_path, r), CARDS)
    assert not rep.ok
    assert any("admissibility predicate" in e for e in rep.errors)


def test_subtype_rule_effect_admissible_pin_passes(tmp_path):
    # The Part-8 Step-3 escape: an underpowered (floor-false) stratum that is
    # subgroup_effect_admissible: true is ADMISSIBLE — the effect-size gate substitutes
    # for the n>=30 floor. This is the SCLC-P/POU2F3 path.
    r = _base_subtype_rule()
    r["when"]["in_record"]["subgroup_n_floor_met"] = False
    r["when"]["in_record"]["evidence_state"] = "underpowered"
    r["when"]["in_record"]["subgroup_effect_admissible"] = True
    rep = V.validate_rules_file(_rules_file(tmp_path, r), CARDS)
    assert rep.ok, rep.errors


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
    """EVERY shipped interpretation-rules/*.rules.yaml validates (0 errors) —
    globbed so every current + future rules file is schema-validated (not a
    hardcoded 2-file allowlist). Covers intracellular + surface + the combo axes
    (combination-opportunity, combinatorial-dependency)."""
    rules_files = sorted((REPO / "interpretation-rules").glob("*.rules.yaml"))
    assert rules_files, "no *.rules.yaml found under interpretation-rules/"
    for path in rules_files:
        rep = V.validate_rules_file(path, CARDS)
        assert rep.ok, f"{path.name}: {rep.errors}"


# ---------------------------------------------------------------------------
# Enforced summary_fields_vocabulary (fix #4, 2026-08-15) — a rule that COMPARES
# a scalar field (equals/in) requires the emitting card to declare that field's
# value vocabulary, else it is a HARD ERROR (was a warning). Bool operands
# ('true'/'false') coerce against string vocab via _values_equal (engine parity).
# ---------------------------------------------------------------------------

def _scalar_rule(card_id: str, field: str, equals) -> dict:
    return {
        "rule_id": "t-scalar",
        "when": {"card_id": card_id, "field": field, "equals": equals},
        "signals": {"small_molecule": "supportive"},
    }


def test_values_equal_coerces_bool_and_string():
    # mirrors the engine's _rule_values_equal: bool <-> lowercase 'true'/'false'.
    assert V._values_equal("true", "true")          # exact
    assert V._values_equal("true", True)            # str vocab vs bool operand
    assert V._values_equal(True, "true")            # bool vocab vs str operand
    assert V._values_equal("false", False)
    assert not V._values_equal("true", "yes")       # genuine drift still fails
    assert not V._values_equal("BRAF", "braf")      # string comparison stays case-sensitive


def test_shipped_bool_field_rule_passes_with_declared_vocab(tmp_path):
    # The real bool field: card declares ['true','false'] string vocab, rule uses equals: 'true'.
    rep = V.validate_rules_file(
        _rules_file(tmp_path, _scalar_rule("structure-features-static",
                                           "mutation_hotspot_in_druggable_pocket", "true")),
        CARDS)
    assert rep.ok, rep.errors
    # And enforcement means NO residual warning about unverifiable vocab.
    assert not any("summary_fields_vocabulary" in w for w in rep.warnings)


def test_undeclared_scalar_vocab_is_hard_error(tmp_path):
    # A rule comparing a field whose card declares NO vocabulary for it must ERROR.
    # cspa_category is a real summary_field on protein-surface-evidence with no vocab declared.
    rep = V.validate_rules_file(
        _rules_file(tmp_path, _scalar_rule("protein-surface-evidence", "cspa_category", "foo")),
        CARDS)
    assert not rep.ok
    assert any("summary_fields_vocabulary" in e and "cspa_category" in e for e in rep.errors)


def test_enum_drift_against_declared_vocab_is_error(tmp_path):
    # protein-surface-evidence declares surface_confirmation_class vocab; a drifted token must be
    # flagged. `cell_surface_confirmed` is the corrected-out (2026-08-17, S2) spelling the reader
    # never emits — it is now NOT producible and must error (the exact dead-rule the review found).
    rep = V.validate_rules_file(
        _rules_file(tmp_path, _scalar_rule("protein-surface-evidence",
                                           "surface_confirmation_class", "cell_surface_confirmed")),
        CARDS)
    assert not rep.ok
    assert any("NOT producible" in e and "surface_confirmation_class" in e for e in rep.errors)


def test_declared_enum_value_passes(tmp_path):
    # confirmed_high is a real value the cspa_surface_confirmation reader emits + the card now declares.
    rep = V.validate_rules_file(
        _rules_file(tmp_path, _scalar_rule("protein-surface-evidence",
                                           "surface_confirmation_class", "confirmed_high")),
        CARDS)
    assert rep.ok, rep.errors


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


def test_shipped_effect_admissible_rule_present_and_disjoint():
    """The Part-8 Step-3 effect-admissible supportive rule ships, is keyed on the
    UNDERPOWERED evidence_state + subgroup_effect_admissible: true (so it is disjoint
    from the floor-cleared `measured` rule — no double-fire of the same signal), and
    emits only the SUPPORTIVE signal (never an opposing/hold)."""
    doc = yaml.safe_load((REPO / "interpretation-rules" / "intracellular-intrinsic.rules.yaml").read_text())
    rule = next((r for r in doc["rules"]
                 if r.get("rule_id") == "subtype-restricted-dependency-underpowered-supportive"), None)
    assert rule is not None, "subtype-restricted-dependency-underpowered-supportive rule missing"
    assert rule["tier"] == "subtype"
    ir = rule["when"]["in_record"]
    assert ir["subgroup_effect_admissible"] is True
    assert ir["evidence_state"] == "underpowered"     # disjoint from the floor-cleared (measured) rule
    assert ir["class"] == "strong_dependency"
    assert rule["signals"]["subtype_fit_genomic"] == "supportive"
    # the floor-cleared sibling stays keyed on measured — the two never match the same record.
    floor = next(r for r in doc["rules"] if r.get("rule_id") == "subtype-restricted-dependency-supportive")
    assert floor["when"]["in_record"]["evidence_state"] == "measured"
