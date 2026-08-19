"""Tests for the card→skill binding blocks (consumed_by / axis_edge) added to card.schema.json +
the _axis_binding_check cross-reference in validate_cards.py (plan Part 5 / card-binding SoT).

Both blocks are OPTIONAL + additive (existing cards without them validate unchanged). These tests
assert:
  - a card with valid consumed_by / axis_edge referencing target_profiling_axes.yaml is clean,
  - the `self_contained` lens sentinel (inline-verdict hosts) is accepted,
  - a bogus lens / reports_into that is not an ontology axis is an ERROR,
  - the schema's role:verdict ⇒ verdict_source ∈ {resolver,inline} conditional is enforced,
  - a card with neither block validates exactly as before.

Hermetic: synthetic card dicts written to tmp YAML, validated against the real card.schema.json +
the real vocabularies/target_profiling_axes.yaml.
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


def _base_card(**overrides) -> dict:
    card = {
        "card_id": "synthetic-test-card",
        "version": "1.0.0",
        "question": "Synthetic card question for {target.symbol} in {indication.label}?",
        "applies_when": ["target.depmap_screened == true"],
        "required_inputs": [{"product_id": "depmap-consortium-26q1"}],
        "methods": [{"call": "depmap-chronos"}],
        "outputs": {"summary_fields": ["median_chronos_panel"]},
        "caveats": ["A caveat long enough to satisfy the minLength constraint."],
        "schema_version": 1,
    }
    card.update(overrides)
    return card


def _validate(tmp_path: Path, card: dict):
    p = tmp_path / "synthetic.card.yaml"
    p.write_text(yaml.safe_dump(card))
    return VC.validate_card_file(p)


def _errs(r) -> str:
    return "\n".join(r.errors)


def test_no_binding_blocks_is_clean(tmp_path):
    """The blocks are optional — a card without them is unaffected."""
    r = _validate(tmp_path, _base_card())
    assert r.ok, _errs(r)


def test_valid_consumed_by_is_clean(tmp_path):
    card = _base_card(consumed_by=[
        {"skill": "genomic-alteration-profile", "lens": "genomic_alteration",
         "role": "verdict", "verdict_source": "resolver"},
        {"skill": "on-target-safety-liability", "lens": "safety",
         "role": "verdict", "verdict_source": "resolver",
         "compose_reason": "activating-driver-role-safety-context rung"},
    ])
    r = _validate(tmp_path, card)
    assert r.ok, _errs(r)


def test_self_contained_lens_sentinel_accepted(tmp_path):
    """Inline-verdict hosts (tumor-presence etc.) have no gate short → `self_contained`."""
    card = _base_card(consumed_by=[
        {"skill": "tumor-presence", "lens": "self_contained",
         "role": "verdict", "verdict_source": "inline"}])
    r = _validate(tmp_path, card)
    assert r.ok, _errs(r)


def test_conditioner_lens_accepted(tmp_path):
    """A conditioner id (e.g. molecular_form) is a valid lens too."""
    card = _base_card(consumed_by=[
        {"skill": "tumor-presence", "lens": "molecular_form",
         "role": "display", "verdict_source": "none"}])
    r = _validate(tmp_path, card)
    assert r.ok, _errs(r)


def test_bogus_lens_is_error(tmp_path):
    card = _base_card(consumed_by=[
        {"skill": "tumor-presence", "lens": "not_a_real_axis",
         "role": "display", "verdict_source": "none"}])
    r = _validate(tmp_path, card)
    assert not r.ok and "CONSUMED_BY_LENS" in _errs(r), _errs(r)


def test_role_verdict_requires_real_verdict_source(tmp_path):
    """Schema if/then: role:verdict with verdict_source:none is a structural error."""
    card = _base_card(consumed_by=[
        {"skill": "tumor-presence", "lens": "expression",
         "role": "verdict", "verdict_source": "none"}])
    r = _validate(tmp_path, card)
    assert not r.ok, "role:verdict + verdict_source:none must fail schema"


def test_valid_axis_edge_is_clean(tmp_path):
    card = _base_card(axis_edge={
        "anchor": "crispr_lof_dependency", "partner": "mutation_status",
        "edge_kind": "stratified_dependency", "reports_into": "dependency"})
    r = _validate(tmp_path, card)
    assert r.ok, _errs(r)


def test_axis_edge_bogus_reports_into_is_error(tmp_path):
    card = _base_card(axis_edge={
        "anchor": "crispr_lof_dependency", "partner": "mutation_status",
        "edge_kind": "stratified_dependency", "reports_into": "not_a_question"})
    r = _validate(tmp_path, card)
    assert not r.ok and "AXIS_EDGE_REPORTS_INTO" in _errs(r), _errs(r)


def test_axis_edge_reports_into_rejects_conditioner(tmp_path):
    """reports_into must be a QUESTION short, not a conditioner id."""
    card = _base_card(axis_edge={
        "anchor": "paralog_family", "partner": "dependency_outcome",
        "edge_kind": "paralog", "reports_into": "molecular_form"})
    r = _validate(tmp_path, card)
    assert not r.ok and "AXIS_EDGE_REPORTS_INTO" in _errs(r), _errs(r)
