"""Phase 4 schema-extension tests.

Verifies the new capabilities landed in target-contracts Phase 4:
- 14-channel signal_channel_id enum (5 modality + 9 target-first)
- signal-absence enum extension: not_applicable added
- tier metadata on rules + cards
- in_record predicate for list-typed field matching
- summary_fields_record_schemas for card outputs
- subgroup_metadata_declared required on subtype-tier rules
- Backward compat: existing modality-only rules + non-tier cards still validate
"""

import json
from pathlib import Path

import jsonschema
import pytest

REPO = Path(__file__).resolve().parents[2]
RULE_SCHEMA = json.loads((REPO / "schemas" / "interpretation_rules.schema.json").read_text())
CARD_SCHEMA = json.loads((REPO / "schemas" / "card.schema.json").read_text())


# ---------- Rule schema extensions ----------

def _base_rules_doc(rule):
    return {
        "rules_id": "test-rules",
        "version": "1.0.0",
        "axis": "intracellular_intrinsic",
        "schema_version": 1,
        "rules": [rule],
    }


def test_backward_compat_modality_only_rule():
    """Legacy shape: signals with only modality channels (small_molecule etc.) validates."""
    rule = {
        "rule_id": "test-r1",
        "when": {"card_id": "card-x", "field": "class_a", "equals": "high"},
        "signals": {"small_molecule": "supportive", "degrader": "supportive"},
    }
    jsonschema.validate(instance=_base_rules_doc(rule), schema=RULE_SCHEMA)


def test_new_target_first_channels_validate():
    """New Phase-4 target-first channels validate in signals map."""
    rule = {
        "rule_id": "test-target-ess",
        "when": {"card_id": "card-x", "field": "class_a", "equals": "pan_essential"},
        "signals": {
            "target_essentiality": "killer",
            "target_tractability": "supportive",
            "axis_fit": "supportive",
        },
        "killer_message": "Pan-essential across lineages — no cancer therapeutic window.",
    }
    jsonschema.validate(instance=_base_rules_doc(rule), schema=RULE_SCHEMA)


def test_new_indication_and_subtype_channels():
    """indication_fit_* + subtype_fit_* channels validate."""
    rule = {
        "rule_id": "test-panel-conv",
        "when": {"card_id": "card-x", "field": "class_a", "equals": "converges"},
        "signals": {
            "indication_fit_convergence": "supportive",
            "indication_fit_single": "supportive",
            "subtype_fit_genomic": "supportive",
            "subtype_fit_expression": "neutral",
            "subtype_fit_immune": "insufficient",
        },
    }
    jsonschema.validate(instance=_base_rules_doc(rule), schema=RULE_SCHEMA)


def test_invalid_channel_rejected():
    """A signals key not in the 14-channel enum is rejected."""
    rule = {
        "rule_id": "test-bad",
        "when": {"card_id": "card-x", "field": "class_a", "equals": "high"},
        "signals": {"invented_channel": "supportive"},
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_base_rules_doc(rule), schema=RULE_SCHEMA)


def test_not_applicable_enum_value():
    """not_applicable (Phase 4 addition) validates as signal value."""
    rule = {
        "rule_id": "test-na",
        "when": {"card_id": "card-x", "field": "class_a", "equals": "n/a"},
        "signals": {"subtype_fit_immune": "not_applicable"},
    }
    jsonschema.validate(instance=_base_rules_doc(rule), schema=RULE_SCHEMA)


def test_tier_optional():
    """rule.tier is optional but validates when set."""
    rule = {
        "rule_id": "test-tier",
        "when": {"card_id": "card-x", "field": "class_a", "equals": "high"},
        "signals": {"target_essentiality": "supportive"},
        "tier": "target",
    }
    jsonschema.validate(instance=_base_rules_doc(rule), schema=RULE_SCHEMA)


def test_emits_declaration_validates():
    """rule.emits (Phase 4) — declaration of possible signal-vocabulary values."""
    rule = {
        "rule_id": "test-emits",
        "when": {"card_id": "card-x", "field": "class_a", "equals": "high"},
        "signals": {"target_essentiality": "supportive"},
        "emits": ["supportive", "insufficient", "not_applicable"],
    }
    jsonschema.validate(instance=_base_rules_doc(rule), schema=RULE_SCHEMA)


def test_subgroup_metadata_declared():
    """subgroup_metadata_declared block validates for subtype-tier rules."""
    rule = {
        "rule_id": "test-subtype",
        "when": {"card_id": "card-x", "field": "class_a", "equals": "high"},
        "signals": {"subtype_fit_genomic": "supportive"},
        "tier": "subtype",
        "subgroup_metadata_declared": {
            "subtype_defining_data": "genomic",
            "subgroup_n_source": "tcga-subgroup-assignments-coadread-v1:MSI_H",
            "min_n_required": 30,
        },
    }
    jsonschema.validate(instance=_base_rules_doc(rule), schema=RULE_SCHEMA)


def test_in_record_predicate():
    """in_record predicate (Phase 4) — match records within list-typed fields."""
    rule = {
        "rule_id": "test-in-record",
        "when": {
            "card_id": "cellline-rna-distribution",
            "field": "per_scope_expression",
            "in_record": {
                "scope_type": "subtype",
                "expression_class": "broadly_high",
                "subgroup_n_floor_met": True,
            },
        },
        "signals": {"target_essentiality": "supportive"},
        "dominant": True,
    }
    jsonschema.validate(instance=_base_rules_doc(rule), schema=RULE_SCHEMA)


def test_in_record_with_list_value():
    """in_record supports array values (in-list matching within a record)."""
    rule = {
        "rule_id": "test-in-record-list",
        "when": {
            "card_id": "cellline-rna-distribution",
            "field": "per_scope_expression",
            "in_record": {
                "scope_type": "subtype",
                "expression_class": ["broadly_high", "broadly_moderate"],
            },
        },
        "signals": {"target_essentiality": "supportive"},
    }
    jsonschema.validate(instance=_base_rules_doc(rule), schema=RULE_SCHEMA)


def test_when_oneOf_still_enforced():
    """One of equals/in/in_record must be present; all three absent → invalid."""
    rule = {
        "rule_id": "test-no-predicate",
        "when": {"card_id": "card-x", "field": "class_a"},
        "signals": {"target_essentiality": "supportive"},
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_base_rules_doc(rule), schema=RULE_SCHEMA)


# ---------- Card schema extensions ----------

def _base_card(**overrides):
    base = {
        "card_id": "test-card",
        "version": "1.0.0",
        "question": "Test card question for Phase 4 schema-extension tests?",
        "applies_when": [],
        "required_inputs": [{"product_id": "test-product"}],
        "methods": [{"call": "test-method"}],
        "outputs": {"summary_fields": ["some_class"]},
        "caveats": [],
        "schema_version": 1,
    }
    base.update(overrides)
    return base


def test_tier_optional_on_card():
    """card.tier is optional; card without tier validates."""
    jsonschema.validate(instance=_base_card(), schema=CARD_SCHEMA)
    # And with tier set
    jsonschema.validate(instance=_base_card(tier="target"), schema=CARD_SCHEMA)


def test_tier_enum_enforced():
    """Invalid tier value rejected."""
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_base_card(tier="invented_tier"), schema=CARD_SCHEMA)


def test_summary_fields_record_schemas_optional():
    """summary_fields_record_schemas is optional."""
    card = _base_card()
    card["outputs"]["summary_fields"] = ["per_scope_expression", "expression_class_panel"]
    card["outputs"]["summary_fields_record_schemas"] = {
        "per_scope_expression": {
            "scope_type": ["indication", "subtype", "lineage"],
            "scope_id": "string",
            "subgroup_n": "integer",
            "subgroup_n_floor_met": "boolean",
            "expression_class": {
                "enum": ["broadly_high", "broadly_moderate", "lineage_restricted", "broadly_low"]
            },
        }
    }
    jsonschema.validate(instance=card, schema=CARD_SCHEMA)


def test_summary_fields_record_schemas_type_validation():
    """Invalid record-schema type spec rejected."""
    card = _base_card()
    card["outputs"]["summary_fields_record_schemas"] = {
        "per_scope_expression": {
            "scope_type": "float64",  # Not in allowed type enum
        }
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=card, schema=CARD_SCHEMA)
