"""Tests for `threshold_roles` and the narrowed THRESHOLD_UNUSED warning in validate_cards.py.

THRESHOLD_UNUSED fired for 363 declared thresholds across 79 of 148 cards — 52% of every gap
the framework atlas reported — and told authors to "remove from thresholds: block" for numbers
the method needs. `thresholds:` holds two different kinds of value:

  interpretation cutoff   a predicate compares against it → MUST be THRESHOLD.-referenced
  upstream parameter      the method or reader already applied it before the card saw a field
                          (a stratification alpha, an effect-size floor, an RF hyperparameter)
                          → can NEVER be predicate-referenced, so the warning was permanent

`threshold_roles` declares the second kind. The risk in any such escape hatch is that it turns
into a blanket silencer, so these tests pin it from both ends: the declaration silences ONLY the
name it declares, and it must be a true statement about this card — it names a real threshold, it
names one of THIS card's own method calls, and it FAILS the moment a predicate starts referencing
the value (which is both the misdeclaration check and the staleness ratchet).

Hermetic: synthetic cards written to tmp YAML, validated against the real card.schema.json.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
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
        "card_id": "synthetic-threshold-card",
        "version": "1.0.0",
        "question": "Synthetic card question for {target.symbol} in {indication.label}?",
        "applies_when": ["target.depmap_screened == true"],
        "required_inputs": [{"product_id": "depmap-consortium-26q1"}],
        "methods": [{"call": "depmap-chronos"}],
        "outputs": {"summary_fields": ["median_chronos_panel"]},
        "caveats": ["A caveat long enough to satisfy the minLength constraint."],
        "schema_version": 1,
        "thresholds": {"stratification_alpha": 0.05},
    }
    card.update(overrides)
    return card


def _validate(tmp_path: Path, card: dict):
    p = tmp_path / "synthetic.card.yaml"
    p.write_text(yaml.safe_dump(card))
    return VC.validate_card_file(p)


def _errs(report) -> str:
    return "\n".join(report.errors)


def _warns(report) -> str:
    return "\n".join(report.warnings)


def _threshold_warns(report) -> list[str]:
    """The synthetic card also trips INTERPRETATION_UNDECLARED / MEASUREMENT_TYPE_MISSING (it is
    not a registered card), so asserting `not report.warnings` would test those instead."""
    return [w for w in report.warnings if "THRESHOLD" in w]


_METHOD_PARAM = {"role": "method_parameter", "consumed_by": "depmap-chronos"}


# ---------- the warning still fires when nothing is declared ----------


def test_undeclared_unused_threshold_still_warns(tmp_path):
    """Non-vacuity for the whole file: without a role entry the warning is unchanged, so these
    tests are measuring the declaration and not a check that stopped firing."""
    report = _validate(tmp_path, _base_card())
    assert report.ok, _errs(report)
    assert "THRESHOLD_UNUSED" in _warns(report)
    assert "stratification_alpha" in _warns(report)


def test_warning_names_the_escape_hatch(tmp_path):
    """A warning that does not say what to do about it is how 363 of these went unactioned."""
    report = _validate(tmp_path, _base_card())
    assert "threshold_roles" in _warns(report)


# ---------- a declaration silences exactly its own name ----------


def test_declared_method_parameter_silences_its_own_warning(tmp_path):
    card = _base_card(threshold_roles={"stratification_alpha": dict(_METHOD_PARAM)})
    report = _validate(tmp_path, card)
    assert report.ok, _errs(report)
    assert not _threshold_warns(report), _warns(report)


def test_declaring_one_threshold_does_not_silence_another(tmp_path):
    """The failure mode the checks exist to prevent: an entry that quiets the whole card."""
    card = _base_card(
        thresholds={"stratification_alpha": 0.05, "strong_effect_delta": -0.5},
        threshold_roles={"stratification_alpha": dict(_METHOD_PARAM)},
    )
    report = _validate(tmp_path, card)
    assert report.ok, _errs(report)
    assert "THRESHOLD_UNUSED" in _warns(report)
    assert "strong_effect_delta" in _warns(report)
    assert "stratification_alpha" not in _warns(report)


def test_reader_gate_role_also_silences(tmp_path):
    card = _base_card(
        threshold_roles={
            "stratification_alpha": {
                "role": "reader_gate",
                "note": "the skill-side reader applies this alpha while shaping the emitted fields",
            }
        }
    )
    report = _validate(tmp_path, card)
    assert report.ok, _errs(report)
    assert not _threshold_warns(report), _warns(report)


# ---------- the declaration must be a true statement about this card ----------


def test_role_for_a_threshold_that_does_not_exist_fails(tmp_path):
    """Dead declaration: waives a warning that could never have been emitted."""
    card = _base_card(threshold_roles={"not_a_threshold": dict(_METHOD_PARAM)})
    report = _validate(tmp_path, card)
    assert not report.ok
    assert "DANGLING_THRESHOLD_ROLE" in _errs(report)
    assert "not_a_threshold" in _errs(report)


def test_role_on_a_predicate_referenced_threshold_fails(tmp_path):
    """The misdeclaration check AND the staleness ratchet: the card interprets this value itself,
    so claiming it is applied only upstream is false — and it must fail rather than suppress."""
    card = _base_card(
        applies_when=["target.depmap_screened == true and target.q < THRESHOLD.stratification_alpha"],
        threshold_roles={"stratification_alpha": dict(_METHOD_PARAM)},
    )
    report = _validate(tmp_path, card)
    assert not report.ok
    assert "MISDECLARED_THRESHOLD_ROLE" in _errs(report)
    assert "stratification_alpha" in _errs(report)


def test_stale_role_survives_moving_the_reference_into_a_hint(tmp_path):
    """Same ratchet through interpretation_hints, not just applies_when — the check must read
    every predicate surface the reference scan reads, or the ratchet has a hole."""
    card = _base_card(
        interpretation_hints=[{"if": "card.q < THRESHOLD.stratification_alpha", "call": "significant"}],
        threshold_roles={"stratification_alpha": dict(_METHOD_PARAM)},
    )
    report = _validate(tmp_path, card)
    assert not report.ok
    assert "MISDECLARED_THRESHOLD_ROLE" in _errs(report)


def test_method_parameter_must_name_one_of_this_cards_own_calls(tmp_path):
    """`consumed_by` is anchored the way a resolver's driving_rule is anchored to its own rung.
    Naming any method in the fleet would make the declaration unfalsifiable."""
    card = _base_card(
        threshold_roles={"stratification_alpha": {"role": "method_parameter", "consumed_by": "dge-deseq2"}}
    )
    report = _validate(tmp_path, card)
    assert not report.ok
    assert "UNKNOWN_THRESHOLD_CONSUMER" in _errs(report)
    assert "dge-deseq2" in _errs(report)


def test_method_parameter_without_a_consumer_is_rejected_structurally(tmp_path):
    """Schema-level: role alone would be a bare suppression with nothing to check."""
    card = _base_card(threshold_roles={"stratification_alpha": {"role": "method_parameter"}})
    report = _validate(tmp_path, card)
    assert not report.ok
    assert "STRUCTURAL" in _errs(report) and "consumed_by" in _errs(report)


def test_reader_gate_without_a_note_is_rejected_structurally(tmp_path):
    """reader_gate cannot be machine-anchored, so the prose IS the review surface and is required
    — the asymmetry with method_parameter is deliberate."""
    card = _base_card(threshold_roles={"stratification_alpha": {"role": "reader_gate"}})
    report = _validate(tmp_path, card)
    assert not report.ok
    assert "STRUCTURAL" in _errs(report) and "note" in _errs(report)


def test_reader_gate_note_must_be_substantive(tmp_path):
    card = _base_card(threshold_roles={"stratification_alpha": {"role": "reader_gate", "note": "upstream"}})
    report = _validate(tmp_path, card)
    assert not report.ok
    assert "STRUCTURAL" in _errs(report)
    assert "threshold_roles.stratification_alpha.note" in _errs(report)


def test_unknown_role_is_rejected_structurally(tmp_path):
    """A free-text role would let a card invent a category nobody checks."""
    card = _base_card(
        threshold_roles={"stratification_alpha": {"role": "someone_else_probably", "consumed_by": "depmap-chronos"}}
    )
    report = _validate(tmp_path, card)
    assert not report.ok
    assert "STRUCTURAL" in _errs(report)


def test_unknown_key_inside_a_role_entry_is_rejected(tmp_path):
    card = _base_card(threshold_roles={"stratification_alpha": dict(_METHOD_PARAM, waived_because="reviewer said so")})
    report = _validate(tmp_path, card)
    assert not report.ok
    assert "STRUCTURAL" in _errs(report)


# ---------- the shipped cards ----------


def test_every_shipped_role_entry_is_valid(card_specs, card_reports):
    """The annotated cards must satisfy every check above, not just the schema."""
    annotated = []
    for p, spec in card_specs.items():
        if not spec.get("threshold_roles"):
            continue
        annotated.append(spec["card_id"])
        report = card_reports[p]
        # case-insensitive: a schema that does not KNOW threshold_roles rejects it as an
        # unevaluated property, which an upper-case-only needle would miss entirely.
        bad = [e for e in report.errors if "threshold" in e.lower()]
        assert not bad, f"{spec['card_id']}: {bad}"
    assert annotated, "no shipped card declares threshold_roles — this test would be vacuous"


def test_shipped_role_entries_name_only_their_own_method_calls(card_specs):
    """Read directly off the YAML rather than through the validator, so a regression that
    disabled the UNKNOWN_THRESHOLD_CONSUMER check would still be caught here."""
    checked = 0
    for spec in card_specs.values():
        roles = spec.get("threshold_roles") or {}
        own = {m.get("call") for m in (spec.get("methods") or []) if isinstance(m, dict)}
        for name, entry in roles.items():
            if entry.get("role") != "method_parameter":
                continue
            assert entry["consumed_by"] in own, f"{spec['card_id']}.{name} -> {entry['consumed_by']} not in {own}"
            checked += 1
    assert checked >= 40, f"only {checked} method_parameter entries found — expected the 43 annotated"


def test_no_shipped_role_entry_shadows_a_predicate_reference(card_specs):
    """The population-level version of the misdeclaration check: no annotated card may declare a
    role for a threshold its own predicates use."""
    import re

    for spec in card_specs.values():
        roles = set((spec.get("threshold_roles") or {}).keys())
        if not roles:
            continue
        preds = list(spec.get("applies_when") or [])
        preds += [h.get("if", "") for h in (spec.get("interpretation_hints") or [])]
        preds += [w.get("if", "") for w in (spec.get("warning_predicates") or [])]
        referenced = set()
        for pred in preds:
            referenced |= set(re.findall(r"THRESHOLD\.([a-z_][a-z0-9_]*)", pred or ""))
        assert not (roles & referenced), f"{spec['card_id']}: {sorted(roles & referenced)}"


@pytest.mark.parametrize(
    "card_id,name",
    [
        ("gnomad-lof-constraint", "high_pli"),
        ("partner-conditional-dependency", "strong_effect_delta"),
        ("dependency-lineage-selectivity", "broadly_dependent_panel_median"),
    ],
)
def test_named_annotations_are_present(card_id, name):
    """Spot-pins on three annotations that were verified against the method source by hand, so a
    bulk re-run of the annotation script cannot silently drop them."""
    spec = yaml.safe_load((REPO / "cards" / f"{card_id}.card.yaml").read_text())
    assert name in (spec.get("threshold_roles") or {}), f"{card_id} lost its {name} role entry"
