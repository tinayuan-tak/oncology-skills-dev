"""Dynamic-dashboard Phase B — a target-profile RUN produces per-card figures.

Previously a target-profile run was rules/summary-only: only the composite panel was drawn, and the
per-card distribution charts (Chronos waterfall, expression density, tumor-vs-normal box) were never
produced. `_emit_card_figures` closes that by invoking the SHARED compose-dashboard figure registry
per card. These tests stub the registry (no S3, no method internals) and pin the loop's contract:
one call per distinct non-missing card, a {card_id: [descriptors]} map, and the interactive-spec
count. Bedrock-free.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_run_cf", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


tp = _load()
# _emit_card_figures + _load_figure_registry moved to tp_evidence_package (2026-08-16 god-module
# split); patch the registry loader there so _emit_card_figures resolves the fake in its own namespace.
import tp_evidence_package  # noqa: E402


def _sub_results():
    return {
        "dependency": {"skill_dir": "functional-requirement", "cards": [
            {"card_id": "pan-cancer-crispr-dependency-distribution", "summary": {"x": 1}},
            {"card_id": "dependency-lineage-selectivity", "summary": {"x": 2}},
        ]},
        "expression": {"skill_dir": "tumor-presence", "cards": [
            {"card_id": "cellline-rna-distribution", "summary": {"x": 3}},
            # a data-blocked card must be SKIPPED (nothing to plot)
            {"card_id": "tumor-rna-vs-adjacent", "summary": {}, "_missing": True},
        ]},
        # a second sub-skill re-listing the same card_id must NOT double-emit
        "selectivity": {"skill_dir": "tumor-selectivity", "cards": [
            {"card_id": "cellline-rna-distribution", "summary": {"x": 3}},
        ]},
    }


class _StubRegistry:
    """Mimics _figure_emitters.emit_figures_for_card without any method/S3 dependency."""
    def __init__(self):
        self.calls = []

    def emit_figures_for_card(self, card_id, summary, out_root, target, indication):
        self.calls.append(card_id)
        # one SVG + one interactive Plotly spec per card (the Phase B shape)
        return [
            {"id": "primary", "path": f"cards/{card_id}/figure_primary.svg",
             "type": "svg", "primary": True},
            {"id": "primary_plotly", "path": f"cards/{card_id}/figure_primary.plotly.json",
             "type": "plotly", "dynamic": True},
        ]


def test_emit_card_figures_one_call_per_distinct_nonmissing_card(monkeypatch, tmp_path):
    stub = _StubRegistry()
    monkeypatch.setattr(tp_evidence_package, "_load_figure_registry", lambda: stub)
    by_card = tp._emit_card_figures(_sub_results(), tmp_path, "KRAS", "COADREAD")
    # 3 distinct non-missing cards; the _missing one skipped, the duplicate not re-called
    assert sorted(stub.calls) == [
        "cellline-rna-distribution",
        "dependency-lineage-selectivity",
        "pan-cancer-crispr-dependency-distribution",
    ]
    assert "tumor-rna-vs-adjacent" not in stub.calls   # data-blocked → skipped
    assert set(by_card) == set(stub.calls)


def test_emit_card_figures_map_carries_plotly_and_svg_descriptors(monkeypatch, tmp_path):
    stub = _StubRegistry()
    monkeypatch.setattr(tp_evidence_package, "_load_figure_registry", lambda: stub)
    by_card = tp._emit_card_figures(_sub_results(), tmp_path, "KRAS", "COADREAD")
    figs = by_card["cellline-rna-distribution"]
    assert any(f.get("dynamic") for f in figs)                # a Plotly spec is present
    assert any(f["path"].endswith(".svg") for f in figs)      # the SVG fallback is present


def test_emit_card_figures_graceful_when_registry_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(tp_evidence_package, "_load_figure_registry", lambda: None)
    assert tp._emit_card_figures(_sub_results(), tmp_path, "KRAS", "COADREAD") == {}


def test_emit_card_figures_swallows_per_card_emit_errors(monkeypatch, tmp_path):
    class _Boom:
        def emit_figures_for_card(self, *a):
            raise RuntimeError("method blew up")
    monkeypatch.setattr(tp_evidence_package, "_load_figure_registry", lambda: _Boom())
    # one bad card must not sink the whole run — returns an empty map, no raise
    assert tp._emit_card_figures(_sub_results(), tmp_path, "KRAS", "COADREAD") == {}
