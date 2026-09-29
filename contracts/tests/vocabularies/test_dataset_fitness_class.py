"""dataset_fitness_class vocabulary tests — the product-grain dataset-fitness verdict enum.

The axis is orthogonal to the per-target (measurement_type x entity_grain) grammar: it is keyed
by product_id and is a reporting DIMENSION, never a gate. See docs/design/DATASET_FITNESS_AXIS.md.

These pins:
  - the shape is well-formed + versioned + declares its product_id keying and dimension role,
  - the value SET is pinned exactly (adding/removing a class is a deliberate test edit),
  - exactly one default, which is the `not_measured` NULL abstention and the ONLY unmeasured class,
  - every measured class is is_measured:true and carries a label + a non-empty description,
  - the DIMENSION-NOT-GATE invariant: the fitness axis/enum does not leak into
    nomination_verdict_gate.yaml (no fitness_class token is a nomination verdict), which is the
    machine-checkable form of "reports, never vetoes".
"""

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
ENUM = yaml.safe_load((REPO / "vocabularies" / "dataset_fitness_class.enum.yaml").read_text())
GATE_TEXT = (REPO / "vocabularies" / "nomination_verdict_gate.yaml").read_text()

# The pinned class set. Changing this is a deliberate vocabulary decision, not an accident.
EXPECTED_VALUES = {"fit", "fit_with_caveats", "partially_fit", "unfit", "not_measured"}


def _values():
    return ENUM["values"]


def _by_value():
    return {v["value"]: v for v in _values()}


# --------------------------------------------------------------------------
# Shape + top-level invariants
# --------------------------------------------------------------------------
def test_enum_header_is_well_formed():
    assert ENUM["enum_id"] == "dataset_fitness_class"
    assert ENUM["version"].count(".") == 2  # semver-ish
    assert ENUM["axis"] == "dataset_fitness"
    assert ENUM["keyed_by"] == "product_id"  # orthogonal to target x indication
    assert ENUM["description"].strip()


def test_axis_is_a_dimension_not_a_gate():
    # The design invariant, made machine-visible on the enum.
    assert ENUM["axis_role"] == "dimension"
    assert ENUM["never_gates"] is True


# --------------------------------------------------------------------------
# Value set + per-value shape
# --------------------------------------------------------------------------
def test_value_set_is_exactly_pinned():
    got = {v["value"] for v in _values()}
    assert got == EXPECTED_VALUES
    # no duplicate value entries
    assert len(_values()) == len(got)


def test_every_value_has_label_and_nonempty_description():
    for v in _values():
        assert v.get("label"), v
        assert v.get("description", "").strip(), v
        assert "renders_in_dashboard" in v, v


# --------------------------------------------------------------------------
# Default / abstention + measured partition
# --------------------------------------------------------------------------
def test_exactly_one_default_and_it_is_not_measured():
    defaults = [v["value"] for v in _values() if v.get("is_default")]
    assert defaults == ["not_measured"]
    assert ENUM["default"] == "not_measured"


def test_not_measured_is_the_only_unmeasured_class():
    by = _by_value()
    assert by["not_measured"]["is_measured"] is False
    measured = {k for k, v in by.items() if v.get("is_measured") is True}
    assert measured == EXPECTED_VALUES - {"not_measured"}


# --------------------------------------------------------------------------
# Dimension-not-gate: the axis must not leak into the nomination gate
# --------------------------------------------------------------------------
def test_fitness_axis_does_not_appear_in_nomination_gate():
    # A substring scan is deliberate: it catches ANY future wiring of the axis or its enum id
    # into the gate, without false-positiving on the generic word "fit".
    assert "dataset_fitness" not in GATE_TEXT
    assert "fitness_class" not in GATE_TEXT


def test_no_fitness_class_token_is_a_nomination_verdict():
    # Parse the gate and confirm none of our class values are used as a verdict token anywhere.
    gate = yaml.safe_load(GATE_TEXT)
    verdict_tokens = set()

    def _collect(node):
        if isinstance(node, dict):
            for k, val in node.items():
                if k == "verdict" and isinstance(val, str):
                    verdict_tokens.add(val)
                _collect(val)
        elif isinstance(node, list):
            for item in node:
                _collect(item)

    _collect(gate)
    assert EXPECTED_VALUES.isdisjoint(verdict_tokens), EXPECTED_VALUES & verdict_tokens
