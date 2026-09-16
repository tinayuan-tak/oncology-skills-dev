"""Unit tests for the field-conformance classifier — the churn-prone core of step-0a.

These pin the exact boundary the audit had to get right to not inflate: a PRESENT-but-
wrong-type value is a defect; an ABSENT or explicitly-null field is NOT (that is coverage/0b),
and a capsule-only field is a milder note, not a defect.
"""

import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[1]  # skills/tools
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import field_conformance_audit as fca  # noqa: E402


# ── numeric ──
def test_numeric_present_and_numeric_is_ok():
    assert fca.classify_numeric("x", {"x": 0.5}, {}) == fca.OK
    assert fca.classify_numeric("x", {"x": 0}, {}) == fca.OK  # zero is a real reading


def test_numeric_absent_or_null_is_na_not_a_defect():
    assert fca.classify_numeric("x", {}, {}) == fca.NA
    assert fca.classify_numeric("x", {"x": None}, {}) == fca.NA


def test_numeric_present_but_a_name_string_is_wrong_type():
    # the real defect class: a label declared as a numeric extra_scalar
    assert fca.classify_numeric("x", {"x": "MK-2206"}, {}) == fca.WRONGTYPE


def test_numeric_present_but_boolean_is_wrong_type():
    assert fca.classify_numeric("x", {"x": False}, {}) == fca.WRONGTYPE


def test_numeric_readable_only_via_capsule_is_fallback():
    cap = {"numeric_anchors": [{"metric": "x", "value": 3.0}]}
    assert fca.classify_numeric("x", {}, cap) == fca.FALLBACK


# ── string ──
def test_string_present_and_string_is_ok():
    assert fca.classify_string("c", {"c": "high"}, {}) == fca.OK


def test_string_absent_or_null_is_na():
    assert fca.classify_string("c", {}, {}) == fca.NA
    assert fca.classify_string("c", {"c": None}, {}) == fca.NA


def test_string_present_but_boolean_is_wrong_type():
    # is_tce_viable / has_oncogenic_variant class: a bool where a *_class string is read
    assert fca.classify_string("c", {"c": True}, {}) == fca.WRONGTYPE
    assert fca.classify_string("c", {"c": False}, {}) == fca.WRONGTYPE


# ── array ──
def test_array_present_list_ok_scalar_wrong_type_absent_na():
    assert fca.classify_array("a", {"a": [1, 2]}) == fca.OK
    assert fca.classify_array("a", {"a": 5}) == fca.WRONGTYPE
    assert fca.classify_array("a", {}) == fca.NA
    assert fca.classify_array("a", {"a": None}) == fca.NA


# ── spec_fields bucketing ──
def test_spec_fields_buckets_by_reader_type():
    spec = {
        "effect_field": "eff",
        "significance_field": "q",
        "n_field": "n",
        "extra_scalars": ["s1"],
        "categorical": ["c1", "c2"],
        "label_field": "lbl",
        "strata_array": "arr",
    }
    f = fca.spec_fields(spec)
    assert set(f["numeric"]) == {"eff", "q", "n", "s1"}
    assert set(f["string"]) == {"c1", "c2", "lbl"}
    assert f["array"] == ["arr"]
