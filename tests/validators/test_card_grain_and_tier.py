"""Tests for the grain + tier check in validate_cards.py (subgroup-panorama layer).

The grain-check is the guardrail that makes the "subgroup-stratified-expression
trap" structurally impossible: a card claiming a per-subgroup panorama must bind a
per-sample stratified reader, never an emit-time aggregate. These tests assert both
directions — a good card passes, and each bad shape FAILS with a GRAIN/GRAIN_TIER
error — plus lock in that the two shipped live cards + the two fixed traps behave.

Hermetic: builds synthetic card dicts + writes them to tmp YAML; validates against
the real card.schema.json + cross-reference checks. No dependence on emitted data.
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


# ---------- fixtures ----------


def _base_card(**overrides) -> dict:
    """A minimally schema-valid leaf card. Overrides merge shallowly."""
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


def _errors(report) -> str:
    return "\n".join(report.errors)


# ---------- GRAIN: panorama must bind a per-sample reader ----------


def test_panorama_field_on_aggregate_reader_fails(tmp_path):
    """The trap: declares per_subgroup_metrics but binds an aggregate method."""
    card = _base_card(
        methods=[{"call": "dge-deseq2"}],
        required_inputs=[{"product_id": "dge-tumor-vs-adjacent"}],
        outputs={"summary_fields": ["per_subgroup_metrics"]},
    )
    report = _validate(tmp_path, card)
    assert not report.ok
    assert "GRAIN [methods]" in _errors(report)
    assert "not per-sample stratifiable" in _errors(report).lower() or "NOT per-sample" in _errors(report)


def test_per_stratum_spelling_also_caught(tmp_path):
    """The second trap spelling (per_stratum_metrics) is caught identically."""
    card = _base_card(
        methods=[{"call": "tempus-rwd-aggregator"}],
        required_inputs=[{"product_id": "tempus-rwd-stratified-expression"}],
        outputs={"summary_fields": ["per_stratum_metrics"]},
    )
    report = _validate(tmp_path, card)
    assert not report.ok
    assert "GRAIN [methods]" in _errors(report)


def test_status_live_on_aggregate_reader_fails(tmp_path):
    """status: live also triggers the grain requirement, even without the field."""
    card = _base_card(
        methods=[{"call": "dge-deseq2"}],
        required_inputs=[{"product_id": "dge-tumor-vs-adjacent"}],
        subgroup_stratification={"eligible": True, "status": "live", "axes": ["msi_status"]},
    )
    report = _validate(tmp_path, card)
    assert not report.ok
    assert "GRAIN [methods]" in _errors(report)


def test_panorama_field_on_per_sample_reader_passes(tmp_path):
    """A card binding a per-sample stratified reader (depmap-chronos) passes."""
    card = _base_card(
        methods=[{"call": "depmap-chronos"}],
        subgroup_stratification={"eligible": True, "status": "live", "axes": ["msi_status"]},
        outputs={
            "summary_fields": ["per_subgroup_metrics"],
            "summary_fields_record_schemas": {
                "per_subgroup_metrics": {"stratum": "string", "median_chronos": "number"}
            },
        },
    )
    report = _validate(tmp_path, card)
    assert report.ok, _errors(report)


def test_blocked_status_must_not_declare_panorama_field(tmp_path):
    """A blocked card that still declares the record field is contradictory → error."""
    card = _base_card(
        methods=[{"call": "dge-deseq2"}],
        required_inputs=[{"product_id": "dge-tumor-vs-adjacent"}],
        subgroup_stratification={"eligible": True, "status": "blocked_needs_per_sample_reader"},
        outputs={"summary_fields": ["per_subgroup_metrics"]},
    )
    report = _validate(tmp_path, card)
    assert not report.ok
    # Either the GRAIN [methods] (aggregate reader) or GRAIN [outputs] (blocked+field) fires.
    assert "GRAIN" in _errors(report)


def test_blocked_status_without_field_passes(tmp_path):
    """A correctly-blocked card (tag present, no panorama field) is valid."""
    card = _base_card(
        methods=[{"call": "dge-deseq2"}],
        required_inputs=[{"product_id": "dge-tumor-vs-adjacent"}],
        subgroup_stratification={
            "eligible": True,
            "status": "blocked_needs_per_sample_reader",
            "axes": ["msi_status"],
            "rationale": "aggregate substrate; needs per-sample reader",
        },
        outputs={"summary_fields": ["log2fc_tumor_vs_adjacent"]},
    )
    report = _validate(tmp_path, card)
    assert report.ok, _errors(report)


# ---------- TIER: target-tier cards never stratify ----------


def test_tier_target_with_stratification_block_fails(tmp_path):
    card = _base_card(
        tier="target",
        subgroup_stratification={"eligible": True, "status": "live"},
    )
    report = _validate(tmp_path, card)
    assert not report.ok
    assert "GRAIN_TIER" in _errors(report)


def test_tier_target_with_panorama_field_fails(tmp_path):
    card = _base_card(
        tier="target",
        outputs={"summary_fields": ["per_subgroup_metrics"]},
    )
    report = _validate(tmp_path, card)
    assert not report.ok
    assert "GRAIN_TIER" in _errors(report)


def test_tier_target_plain_passes(tmp_path):
    """A target-tier card with no stratification claim is fine."""
    card = _base_card(tier="target")
    report = _validate(tmp_path, card)
    assert report.ok, _errors(report)


# ---------- Regression: the real shipped cards behave ----------


@pytest.mark.parametrize(
    "card_id",
    [
        "subgroup-stratified-mutation-frequency",
        "subgroup-stratified-dependency",
    ],
)
def test_shipped_live_cards_pass(card_id):
    """The 2 new live panorama cards validate clean against the real schema."""
    report = VC.validate_card_file(REPO / "cards" / f"{card_id}.card.yaml")
    assert report.ok, _errors(report)


@pytest.mark.parametrize(
    "card_id",
    [
        "subgroup-stratified-expression",
        "rwd-stratified-expression",
    ],
)
def test_fixed_traps_now_pass(card_id):
    """The 2 formerly-trapped cards are now correctly blocked and validate clean."""
    report = VC.validate_card_file(REPO / "cards" / f"{card_id}.card.yaml")
    assert report.ok, _errors(report)
