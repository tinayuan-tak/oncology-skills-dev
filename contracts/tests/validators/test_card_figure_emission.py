"""Tests for the figure-emission check in validate_cards.py (viz-coverage layer).

The check makes the "declared-not-emitted" class structurally enforceable: a card
declaring a figure must have a live-path emitter registered in compose-dashboard
CARD_FIGURE_EMITTERS (parsed from the skills repo; the render skill only embeds a
pre-existing figure path). These tests assert the branches: a card_id WITH a
registered emitter passes; a NEW non-registered non-waiver card ERRORS; a waiver
card WARNS (tracked debt); a card declaring no figure is untouched; and the check
graceful-skips if the registry is unreachable.

Hermetic: synthetic card dicts written to tmp YAML, validated against the real
card.schema.json. Emitter membership is monkeypatched so tests don't depend on the
live registry contents.
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
        "card_id": "synthetic-figure-card",
        "version": "1.0.0",
        "question": "Synthetic figure card for {target.symbol} in {indication.label}?",
        "applies_when": ["target.depmap_screened == true"],
        "required_inputs": [{"product_id": "depmap-consortium-26q1"}],
        "methods": [{"call": "depmap-expression-distribution"}],  # a known emitter
        "outputs": {"summary_fields": ["median_log2tpm_panel"]},
        "caveats": ["A caveat long enough to satisfy the minLength constraint."],
        "schema_version": 1,
    }
    card.update(overrides)
    return card


def _validate(tmp_path: Path, card: dict):
    p = tmp_path / "synthetic.card.yaml"
    p.write_text(yaml.safe_dump(card))
    return VC.validate_card_file(p)


def _has(report, needle: str) -> bool:
    return any(needle in m for m in report.errors + report.warnings)


# A fixed fake registry so tests don't depend on the live skills repo contents.
_FAKE_EMITTERS = {"cellline-rna-distribution", "some-registered-card"}


def _patch_registry(monkeypatch, value):
    monkeypatch.setattr(VC, "_registered_figure_emitters", lambda: value)


# --- passes: card_id IS in the emitter registry ---


def test_registered_card_passes(tmp_path, monkeypatch):
    _patch_registry(monkeypatch, _FAKE_EMITTERS)
    card = _base_card(
        card_id="cellline-rna-distribution",
        outputs={"summary_fields": ["x"], "figure": "density_expression"},
    )
    report = _validate(tmp_path, card)
    assert not _has(report, "FIGURE_DECLARED_NOT_EMITTED")
    assert not _has(report, "FIGURE_DEBT")


# --- passes: no figure declared → check is a no-op ---


def test_no_figure_declared_is_noop(tmp_path, monkeypatch):
    _patch_registry(monkeypatch, _FAKE_EMITTERS)
    card = _base_card(outputs={"summary_fields": ["x"]})  # no figure/figures
    report = _validate(tmp_path, card)
    assert not _has(report, "FIGURE_")


# --- graceful skip: registry unreachable → no check, no false failure ---


def test_registry_unreachable_graceful_skip(tmp_path, monkeypatch):
    _patch_registry(monkeypatch, None)
    card = _base_card(
        card_id="brand-new-summary-only-card",
        outputs={"summary_fields": ["x"], "figure": "some_panel"},
    )
    report = _validate(tmp_path, card)
    assert not _has(report, "FIGURE_")  # skipped entirely


# --- ERROR: new card declaring a figure, no emitter, not on waiver ---


def test_new_declared_not_emitted_errors(tmp_path, monkeypatch):
    _patch_registry(monkeypatch, _FAKE_EMITTERS)
    card = _base_card(
        card_id="brand-new-summary-only-card",
        outputs={"summary_fields": ["x"], "figure": "some_panel"},
    )
    report = _validate(tmp_path, card)
    assert not report.ok
    assert _has(report, "FIGURE_DECLARED_NOT_EMITTED")


# --- WARN: card on the KNOWN_FIGURE_DEBT waiver → tracked debt, build stays green ---


def test_waiver_card_warns_not_errors(tmp_path, monkeypatch):
    _patch_registry(monkeypatch, _FAKE_EMITTERS)  # shed-ectodomain-liability NOT registered
    # shed-ectodomain-liability is on KNOWN_FIGURE_DEBT (not yet backfilled). The 2
    # safety cards were REMOVED from the waiver on 2026-07-20 once their emitters landed.
    card = _base_card(
        card_id="shed-ectodomain-liability",
        outputs={"summary_fields": ["x"], "figure": "shed_liability_evidence_panel"},
    )
    report = _validate(tmp_path, card)
    assert report.ok, "a waiver card must not error (build stays green)"
    assert _has(report, "FIGURE_DEBT")


# --- the plural `figures:` form is also detected ---


def test_figures_plural_form_detected(tmp_path, monkeypatch):
    _patch_registry(monkeypatch, _FAKE_EMITTERS)
    card = _base_card(
        card_id="brand-new-multi-figure-card",
        outputs={"summary_fields": ["x"], "figures": [{"id": "fig_a", "type": "bar"}]},
    )
    report = _validate(tmp_path, card)
    assert _has(report, "FIGURE_DECLARED_NOT_EMITTED")


# --- guard: waiver ∩ live registry is empty (a registered card shouldn't also be debt) ---


def test_waiver_disjoint_from_live_registry():
    live = VC._registered_figure_emitters()
    if live is None:
        return  # skills repo absent in this checkout — nothing to check
    overlap = VC.KNOWN_FIGURE_DEBT & live
    assert not overlap, f"cards both registered AND on the debt waiver (remove from waiver): {overlap}"
