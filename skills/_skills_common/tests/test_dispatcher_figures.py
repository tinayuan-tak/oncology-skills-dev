"""Tests for the OPT-IN --figures hook in the shared dispatcher.

The figure-emitter registry (compose-dashboard/_figure_emitters) already exists; --figures wires it
into run_wired_skill so a subskill data-package gets native per-card figures. These tests pin the
plumbing WITHOUT any S3/method dependency:
  1. write_package collects figures RECURSIVELY (emitters write figures/cards/<card_id>/*.svg) while
     still finding flat figures/ files (backward-compatible);
  2. _emit_card_figures calls the registry once per NON-missing card and skips missing cards;
  3. figure emission is best-effort — a raising emitter never breaks the run.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]        # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common import dispatcher as D
from _skills_common.write_package import write_package


def test_write_package_collects_nested_and_flat_figures(tmp_path):
    """The --figures path writes figures/cards/<card_id>/*.svg; a caller may also drop flat figures.
    write_package must collect BOTH (recursive glob, files only)."""
    nested = tmp_path / "figures" / "cards" / "cellline-rna-distribution"
    nested.mkdir(parents=True)
    (nested / "figure_density_expression.svg").write_text("<svg/>")
    (tmp_path / "figures" / "flat_legacy.svg").write_text("<svg/>")

    written = write_package(
        out_dir=tmp_path, decision={"provenance": {}},
        card_outputs=[{"card_id": "cellline-rna-distribution", "summary": {}}],
        target="EPCAM", indication="COADREAD",
        skill_name="tumor-presence", skill_version="1.7.0", invoked_lenses={},
    )
    names = {p.name for p in written["figures"]}
    assert "figure_density_expression.svg" in names, "nested per-card figure not collected"
    assert "flat_legacy.svg" in names, "flat figure not collected (backward-compat broken)"


def _fake_registry(monkeypatch, emit_fn):
    # dispatcher imports the registry relatively (`from ._figure_emitters import ...`), which resolves
    # to _skills_common._figure_emitters — inject the fake under that fully-qualified name.
    mod = types.ModuleType("_skills_common._figure_emitters")
    mod.emit_figures_for_card = emit_fn
    monkeypatch.setitem(sys.modules, "_skills_common._figure_emitters", mod)


def test_emit_card_figures_calls_registry_and_skips_missing(tmp_path, monkeypatch):
    calls = []

    def emit(card_id, summary, out_root, target, indication):
        calls.append(card_id)
        d = Path(out_root) / "cards" / card_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "figure_x.svg").write_text("<svg/>")
        return [{"id": "x", "path": f"cards/{card_id}/figure_x.svg"}]

    _fake_registry(monkeypatch, emit)
    cards = [{"card_id": "a", "summary": {}},
             {"card_id": "b", "summary": {}, "_missing": True}]   # missing → skipped
    n = D._emit_card_figures(cards, tmp_path, "EPCAM", "COADREAD")
    assert n == 1, "should emit for exactly the one non-missing card"
    assert calls == ["a"], "missing card must be skipped"
    assert (tmp_path / "figures" / "cards" / "a" / "figure_x.svg").exists()


def test_emit_card_figures_is_best_effort_on_error(tmp_path, monkeypatch):
    def emit(*a, **k):
        raise RuntimeError("boom")

    _fake_registry(monkeypatch, emit)
    # a raising emitter must be swallowed — the run never breaks for a figure
    n = D._emit_card_figures([{"card_id": "a", "summary": {}}], tmp_path, "T", "I")
    assert n == 0


def test_emit_card_figures_graceful_when_registry_absent(tmp_path, monkeypatch):
    # simulate the registry being unimportable → 0 figures, no raise
    monkeypatch.setitem(sys.modules, "_skills_common._figure_emitters", None)
    n = D._emit_card_figures([{"card_id": "a", "summary": {}}], tmp_path, "T", "I")
    assert n == 0
