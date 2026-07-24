"""Tests for the measurement_type check in validate_cards.py (DATA_TO_SKILL_CONTRACT Rule 1).

A card's identity is (measurement_type × entity_grain). The check is MIGRATION-SAFE:
  - no measurement_type → WARNING (tracked migration debt), never an error (the ~40 pre-existing
    cards are un-migrated);
  - measurement_type present but unregistered in vocabularies/measurement_types.yaml → ERROR
    (a typo'd/forgotten type the pull resolver could never match);
  - registered type → clean.
These tests assert all three directions + the schema round-trip (measurement_type + entity_grains
are optional, additive fields), monkeypatching the registry so they don't depend on the vocab's
evolving contents.

Hermetic: synthetic card dicts written to tmp YAML, validated against the real card.schema.json.
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


def _validate(tmp_path: Path, card: dict) -> "VC.ValidationReport":
    p = tmp_path / "synthetic.card.yaml"
    p.write_text(yaml.safe_dump(card))
    return VC.validate_card_file(p)


def _errs(r) -> str:
    return "\n".join(r.errors)


def _warns(r) -> str:
    return "\n".join(r.warnings)


# ---------- schema: the new fields are optional + additive ----------

def test_card_without_measurement_type_is_schema_valid(tmp_path):
    """Backward-compat: a pre-migration card (no measurement_type/entity_grains) still validates."""
    report = _validate(tmp_path, _base_card())
    assert report.ok, _errs(report)   # no ERROR; warnings are fine


def test_card_with_measurement_type_and_grains_is_schema_valid(tmp_path, monkeypatch):
    monkeypatch.setattr(VC, "_registered_measurement_types",
                        lambda: {"crispr_lof_dependency"})
    # This test asserts grain-SCHEMA validity, not modality routing. Isolate it from the P4 Tier-3
    # modality_relevance enforcement (2026-07-24) — which reads the REAL vocab, where
    # crispr_lof_dependency is now stamped modality-relevant — by stubbing the modality-relevant set
    # empty, exactly as it already stubs the registered-type set. (The enforcement itself is covered
    # by test_modality_relevance_*.)
    monkeypatch.setattr(VC, "_modality_relevant_types", lambda: set())
    card = _base_card(measurement_type="crispr_lof_dependency",
                      entity_grains=["target", "target_lineage"])
    report = _validate(tmp_path, card)
    assert report.ok, _errs(report)


def test_bad_measurement_type_pattern_rejected_by_schema(tmp_path):
    """Uppercase / hyphens are not valid measurement_type tokens (snake_case only)."""
    card = _base_card(measurement_type="CRISPR-LOF")
    report = _validate(tmp_path, card)
    assert not report.ok
    assert "STRUCTURAL" in _errs(report)


def test_empty_entity_grains_rejected_by_schema(tmp_path):
    card = _base_card(measurement_type="x_dep", entity_grains=[])
    report = _validate(tmp_path, card)
    assert not report.ok
    assert "STRUCTURAL" in _errs(report)


# ---------- migration-safe check behavior ----------

def test_missing_measurement_type_is_warning_not_error(tmp_path):
    report = _validate(tmp_path, _base_card())
    assert report.ok                                    # WARNING, not error
    assert "MEASUREMENT_TYPE_MISSING" in _warns(report)


def test_registered_measurement_type_is_clean(tmp_path, monkeypatch):
    monkeypatch.setattr(VC, "_registered_measurement_types",
                        lambda: {"crispr_lof_dependency", "surface_confirmation"})
    # isolate the modality-relevance check (P4, 2026-07-23): this test exercises ONLY the
    # measurement-type-registered check, so hold the modality-relevant set empty — otherwise the real
    # vocab (where surface_confirmation IS modality-relevant) would leak in and require the field.
    monkeypatch.setattr(VC, "_modality_relevant_types", lambda: set())
    report = _validate(tmp_path, _base_card(measurement_type="surface_confirmation"))
    assert report.ok, _errs(report)
    assert "MEASUREMENT_TYPE_MISSING" not in _warns(report)
    assert "MEASUREMENT_TYPE_UNREGISTERED" not in _errs(report)


def test_unregistered_measurement_type_is_error(tmp_path, monkeypatch):
    monkeypatch.setattr(VC, "_registered_measurement_types",
                        lambda: {"crispr_lof_dependency"})
    report = _validate(tmp_path, _base_card(measurement_type="typoed_claim"))
    assert not report.ok
    assert "MEASUREMENT_TYPE_UNREGISTERED" in _errs(report)


def test_graceful_skip_when_vocab_absent(tmp_path, monkeypatch):
    """When the vocab file can't be read (None), a declared type is neither confirmed nor
    rejected — the check skips rather than false-failing a mid-migration checkout."""
    monkeypatch.setattr(VC, "_registered_measurement_types", lambda: None)
    report = _validate(tmp_path, _base_card(measurement_type="anything_goes"))
    assert report.ok, _errs(report)
    assert "MEASUREMENT_TYPE_UNREGISTERED" not in _errs(report)


# ---------- the real vocab file, once it exists, parses + is self-consistent ----------

def test_real_vocab_registered_types_are_loadable():
    """If vocabularies/measurement_types.yaml exists, it parses to a non-empty type set (guards
    against a malformed vocab silently disabling the check)."""
    reg = VC._registered_measurement_types()
    if reg is None:
        return  # vocab not landed yet in this checkout — nothing to assert
    assert isinstance(reg, set) and reg, "measurement_types.yaml present but yielded no types"
    # every key is a valid snake_case token (mirrors the schema pattern on the card side)
    import re
    for t in reg:
        assert re.fullmatch(r"[a-z][a-z0-9_]*[a-z0-9]", t), f"bad measurement_type key: {t!r}"


# ---------- modality_relevance check (P4, 2026-07-23) ----------
# A card whose measurement_type is MODALITY-RELEVANT (its vocab entry declares modality_relevance)
# must carry a top-level modality_relevance array. Anchored to the vocab, not a hardcoded list.

def test_modality_relevant_type_without_field_is_error(tmp_path, monkeypatch):
    monkeypatch.setattr(VC, "_registered_measurement_types", lambda: {"surface_confirmation"})
    monkeypatch.setattr(VC, "_modality_relevant_types", lambda: {"surface_confirmation"})
    report = _validate(tmp_path, _base_card(measurement_type="surface_confirmation"))
    assert not report.ok
    assert "MODALITY_RELEVANCE_MISSING" in _errs(report)


def test_modality_relevant_type_with_field_is_clean(tmp_path, monkeypatch):
    monkeypatch.setattr(VC, "_registered_measurement_types", lambda: {"surface_confirmation"})
    monkeypatch.setattr(VC, "_modality_relevant_types", lambda: {"surface_confirmation"})
    report = _validate(tmp_path, _base_card(measurement_type="surface_confirmation",
                                            modality_relevance=["adc", "bite_tce", "antibody"]))
    assert report.ok, _errs(report)
    assert "MODALITY_RELEVANCE_MISSING" not in _errs(report)


def test_non_modality_relevant_type_without_field_is_clean(tmp_path, monkeypatch):
    # a type NOT in the modality-relevant set → the field is not required
    monkeypatch.setattr(VC, "_registered_measurement_types", lambda: {"crispr_lof_dependency"})
    monkeypatch.setattr(VC, "_modality_relevant_types", lambda: set())
    report = _validate(tmp_path, _base_card(measurement_type="crispr_lof_dependency"))
    assert report.ok, _errs(report)
    assert "MODALITY_RELEVANCE_MISSING" not in _errs(report)


def test_modality_relevance_enum_enforced_by_schema(tmp_path):
    # a bogus modality value is a structural (schema enum) rejection
    report = _validate(tmp_path, _base_card(modality_relevance=["not_a_modality"]))
    assert not report.ok
    assert "STRUCTURAL" in _errs(report)
