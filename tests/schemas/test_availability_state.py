"""availability_state vocabulary + evidence-package card_unavailable variant (F, 2026-07-20).

The governance evidence_package historically collapsed several distinct card absences
(unwired / data-blocked / errored / measured-absent) into a bare n_cards_failed integer or
an opaque summary value, so a consumer could not tell "we haven't built it" from "we looked
and it's genuinely unknown." These tests pin the fix:
  - the availability_state enum vocab is well-formed and its values match the schema enum;
  - the card_unavailable envelope variant is a first-class, reason-carrying absence;
  - the three cards[] variants (present / excluded / unavailable) are oneOf-DISJOINT, so a
    consumer can discriminate them unambiguously (the load-bearing property — the schema is
    unevaluatedProperties:false, so a mis-shaped stub would fail rather than silently match).
"""
import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

REPO = Path(__file__).resolve().parents[2]
ENUM = yaml.safe_load((REPO / "vocabularies" / "availability_state.enum.yaml").read_text())
PKG_SCHEMA = json.loads((REPO / "schemas" / "evidence_package.schema.json").read_text())
DEFS = PKG_SCHEMA["$defs"]

EXPECTED_VALUES = {"not_wired", "data_blocked", "read_error", "insufficient"}


# ---------- the enum vocab ----------

def test_enum_wellformed():
    assert ENUM["enum_id"] == "availability_state"
    assert ENUM["version"]
    values = {v["value"] for v in ENUM["values"]}
    assert values == EXPECTED_VALUES, f"enum values {values} != expected {EXPECTED_VALUES}"


def test_every_value_declares_coverage_and_measured_flags():
    """The measured-vs-not-built boundary is the point of the vocabulary — each value must
    state is_coverage_gap + measured explicitly (no silent default)."""
    for v in ENUM["values"]:
        assert "is_coverage_gap" in v, f"{v['value']} missing is_coverage_gap"
        assert "measured" in v, f"{v['value']} missing measured"
    by = {v["value"]: v for v in ENUM["values"]}
    # not_wired / data_blocked / read_error = never looked (not measured); insufficient = looked.
    assert by["not_wired"]["measured"] is False
    assert by["data_blocked"]["measured"] is False
    assert by["read_error"]["measured"] is False
    assert by["insufficient"]["measured"] is True
    # all four are coverage gaps — none is opposing evidence
    assert all(v["is_coverage_gap"] is True for v in ENUM["values"])


def test_enum_matches_schema_variant():
    """The schema's card_unavailable.availability_state enum must equal the vocab values —
    a drift between the two would let one accept a value the other rejects."""
    schema_enum = set(DEFS["card_unavailable"]["properties"]["availability_state"]["enum"])
    assert schema_enum == EXPECTED_VALUES


# ---------- the card_unavailable envelope variant ----------

def _validates_as(variant: str, sample: dict) -> bool:
    return Draft202012Validator({**DEFS[variant], "$defs": DEFS}).is_valid(sample)


def _matches_exactly_one(sample: dict) -> int:
    return sum(_validates_as(v, sample)
              for v in ("card_present", "card_excluded", "card_unavailable"))


def test_cards_items_oneof_includes_unavailable():
    refs = {r["$ref"] for r in PKG_SCHEMA["properties"]["cards"]["items"]["oneOf"]}
    assert "#/$defs/card_unavailable" in refs
    assert refs == {"#/$defs/card_present", "#/$defs/card_excluded", "#/$defs/card_unavailable"}


def test_unavailable_requires_state_and_reason():
    valid = {"card_id": "fusion-rearrangement-landscape", "card_version": "0.1.0",
             "availability_state": "not_wired", "availability_reason": "dispatcher_returned_none"}
    assert _validates_as("card_unavailable", valid)
    # missing reason → invalid
    assert not _validates_as("card_unavailable",
                             {"card_id": "x-card", "card_version": "1.0.0", "availability_state": "not_wired"})
    # unknown state → invalid (guards against a typo'd token leaking in)
    assert not _validates_as("card_unavailable",
                             {"card_id": "x-card", "card_version": "1.0.0",
                              "availability_state": "made_up", "availability_reason": "nope"})


def test_three_variants_are_disjoint():
    """oneOf demands EXACTLY one match per entry — the discriminators (validation_state /
    excluded_by_applies_when / availability_state) must not overlap."""
    present = {"card_id": "kras-x", "card_version": "1.0.0", "validation_state": "pass",
               "summary": {}, "interpretation_call": "strong",
               "provenance": {"method_calls": [], "input_manifest_ids": []}}
    excluded = {"card_id": "kras-x", "card_version": "1.0.0", "excluded_by_applies_when": True,
                "exclusion_reason": "applies_when fusion_calls_available==false"}
    unavailable = {"card_id": "gnomad-lof-constraint", "card_version": "1.0.0",
                   "availability_state": "insufficient", "availability_reason": "primary_class=data_unavailable"}
    for sample in (present, excluded, unavailable):
        assert _matches_exactly_one(sample) == 1, f"{sample} is not oneOf-disjoint"


def test_unavailable_rejects_extra_properties():
    """unevaluatedProperties:false — a stub carrying a stray field (e.g. a smuggled summary)
    must FAIL rather than silently pass, so the governance envelope can't accumulate
    undeclared shape."""
    assert not _validates_as("card_unavailable",
                             {"card_id": "x-card", "card_version": "1.0.0",
                              "availability_state": "not_wired", "availability_reason": "r",
                              "summary": {"smuggled": True}})
