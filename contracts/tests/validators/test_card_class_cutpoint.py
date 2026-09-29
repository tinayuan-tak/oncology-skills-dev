"""Tests for the derivation edge — `threshold_roles.role: class_cutpoint` + `outputs.derivations`.

The hop from a numeric field to a categorical class token (e.g. log2_fc -> expression_call_class)
was declared NOWHERE before 2026-09-18: it lived in a vocabulary comment and the method's Python.
`class_cutpoint` names that boundary and `outputs.derivations` summarises it per class. The whole
value of the pair is that the two declarations, and the card's own summary_fields/vocabulary, agree
with each other — so these tests pin each referential check by MUTATION (an escape hatch that only
ever passes is decoration). Each mutation starts from the same clean card and changes exactly one
thing, so a check that stopped firing shows up as a green mutation.

Hermetic: synthetic cards written to tmp YAML, validated against the real card.schema.json.
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


def _cutpoint_card(**overrides) -> dict:
    """A minimal card exercising both a directional-boundary cut and a conjunctive gate cut."""
    card = {
        "card_id": "synthetic-cutpoint-card",
        "version": "1.0.0",
        "question": "Synthetic cutpoint question for {target.symbol} in {indication.label}?",
        "applies_when": ["target.depmap_screened == true"],
        "required_inputs": [{"product_id": "depmap-consortium-26q1"}],
        "methods": [{"call": "dge-deseq2"}],
        "outputs": {
            "summary_fields": ["log2_fc", "q_value", "expression_call_class"],
            "summary_fields_vocabulary": {
                "expression_call_class": ["strong_upregulation", "modest_upregulation", "not_informative"],
            },
            "derivations": {
                "expression_call_class": {
                    "derives_from": ["log2_fc", "q_value"],
                    "cutpoints": ["strong_cut", "sig_gate"],
                },
            },
        },
        "caveats": ["A caveat long enough to satisfy the minLength constraint."],
        "schema_version": 1,
        "thresholds": {"strong_cut": 1.5, "sig_gate": 0.05},
        "threshold_roles": {
            "strong_cut": {
                "role": "class_cutpoint",
                "bins": "expression_call_class",
                "of": "log2_fc",
                "boundary": "strong_upregulation",
                "scale": "log2FC",
            },
            # a conjunctive gate: no `boundary` (qualifies every directional call)
            "sig_gate": {
                "role": "class_cutpoint",
                "bins": "expression_call_class",
                "of": "q_value",
                "scale": "q_value",
            },
        },
    }
    card.update(overrides)
    return card


def _validate(tmp_path: Path, card: dict):
    p = tmp_path / "synthetic.card.yaml"
    p.write_text(yaml.safe_dump(card))
    return VC.validate_card_file(p)


def _errs(report) -> str:
    return "\n".join(report.errors)


# ---------- happy path ----------


def test_clean_class_cutpoint_validates(tmp_path):
    """The whole shape agrees with itself: no referential error, and a class_cutpoint (like any
    role entry) silences THRESHOLD_UNUSED for the number it declares."""
    report = _validate(tmp_path, _cutpoint_card())
    assert report.ok, _errs(report)
    for tok in ("CLASS_CUTPOINT", "DERIVATION_UNKNOWN"):
        assert tok not in _errs(report), _errs(report)
    thr_unused = [w for w in report.warnings if "THRESHOLD_UNUSED" in w]
    assert not thr_unused, thr_unused  # both cuts are class_cutpoints, so neither is "unused"


def test_gate_cut_without_boundary_is_legal(tmp_path):
    """A conjunctive gate (`sig_gate`, no boundary) is a valid class_cutpoint — boundary is only
    required for a directional cut that admits ONE class."""
    report = _validate(tmp_path, _cutpoint_card())
    assert "CLASS_CUTPOINT_UNKNOWN_BOUNDARY" not in _errs(report)


# ---------- mutation controls: each referential check must be able to fire ----------


def test_unknown_class_fires(tmp_path):
    card = _cutpoint_card()
    card["threshold_roles"]["strong_cut"]["bins"] = "not_a_class_field"
    report = _validate(tmp_path, card)
    assert "CLASS_CUTPOINT_UNKNOWN_CLASS" in _errs(report), _errs(report)


def test_unknown_field_fires(tmp_path):
    card = _cutpoint_card()
    card["threshold_roles"]["strong_cut"]["of"] = "field_the_card_does_not_emit"
    report = _validate(tmp_path, card)
    assert "CLASS_CUTPOINT_UNKNOWN_FIELD" in _errs(report), _errs(report)


def test_unknown_boundary_fires(tmp_path):
    card = _cutpoint_card()
    card["threshold_roles"]["strong_cut"]["boundary"] = "a_value_not_in_the_vocabulary"
    report = _validate(tmp_path, card)
    assert "CLASS_CUTPOINT_UNKNOWN_BOUNDARY" in _errs(report), _errs(report)


def test_derivation_mismatch_missing_entry_fires(tmp_path):
    """A class_cutpoint whose class has no outputs.derivations entry at all."""
    card = _cutpoint_card()
    del card["outputs"]["derivations"]["expression_call_class"]
    report = _validate(tmp_path, card)
    assert "CLASS_CUTPOINT_DERIVATION_MISMATCH" in _errs(report), _errs(report)


def test_derivation_mismatch_cutpoint_not_listed_fires(tmp_path):
    """A class_cutpoint present, but its name absent from derivations.cutpoints."""
    card = _cutpoint_card()
    card["outputs"]["derivations"]["expression_call_class"]["cutpoints"] = ["sig_gate"]
    report = _validate(tmp_path, card)
    assert "CLASS_CUTPOINT_DERIVATION_MISMATCH" in _errs(report), _errs(report)


def test_derivation_of_not_in_derives_from_fires(tmp_path):
    card = _cutpoint_card()
    card["outputs"]["derivations"]["expression_call_class"]["derives_from"] = ["q_value"]
    report = _validate(tmp_path, card)
    assert "CLASS_CUTPOINT_DERIVATION_MISMATCH" in _errs(report), _errs(report)


# ---------- reverse direction: derivations entries must also reference real things ----------


def test_derivation_unknown_class_fires(tmp_path):
    card = _cutpoint_card()
    card["outputs"]["derivations"]["a_class_with_no_vocabulary"] = {
        "derives_from": ["log2_fc"],
        "cutpoints": ["strong_cut"],
    }
    report = _validate(tmp_path, card)
    assert "DERIVATION_UNKNOWN_CLASS" in _errs(report), _errs(report)


def test_derivation_unknown_cutpoint_fires(tmp_path):
    """A derivations cutpoint with no backing class_cutpoint on that class."""
    card = _cutpoint_card()
    card["outputs"]["derivations"]["expression_call_class"]["cutpoints"].append("phantom_cut")
    card["thresholds"]["phantom_cut"] = 2.0  # a real threshold, but not declared class_cutpoint
    report = _validate(tmp_path, card)
    assert "DERIVATION_UNKNOWN_CUTPOINT" in _errs(report), _errs(report)


def test_derivation_unknown_field_fires(tmp_path):
    card = _cutpoint_card()
    card["outputs"]["derivations"]["expression_call_class"]["derives_from"].append("phantom_field")
    report = _validate(tmp_path, card)
    assert "DERIVATION_UNKNOWN_FIELD" in _errs(report), _errs(report)


# ---------- schema-level: class_cutpoint requires bins/of/scale ----------


def test_class_cutpoint_missing_required_keys_is_structural(tmp_path):
    """Dropping the required derivation keys is a STRUCTURAL (schema) failure, not a soft check —
    so a class_cutpoint can never be declared without saying what it bins."""
    card = _cutpoint_card()
    card["threshold_roles"]["strong_cut"] = {"role": "class_cutpoint"}  # no bins/of/scale
    report = _validate(tmp_path, card)
    assert not report.ok
    assert "STRUCTURAL" in _errs(report), _errs(report)
