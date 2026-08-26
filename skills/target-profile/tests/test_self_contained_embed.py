"""PR-3 — `--self-contained` HTML embed. Default is interactive Plotly + CDN; self_contained inlines
per-card figures as base64 SVG data-URIs so the report is fully OFFLINE (no external src/CDN, no JS
bootstrap). These pin that contract. Bedrock-free; verdict-inert (figures never touch the spine)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_run_sc", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


tp = _load()

_LLM = {"executive_summary": {"value": "KRAS is modality-constrained."},
        "overall_recommendation": {"value": "hold"}, "confidence": {"value": "high"},
        "tension_analysis": {"value": "t"}}


def _sr():
    return {"dependency": {"skill_dir": "functional-requirement",
                           "cards": [{"card_id": "crispr", "summary": {"median_chronos": -1.2}}],
                           "verdict": ("lineage_selective", "r-x"), "fired": []}}


def _write_figs(tmp_path):
    figures_dir = tmp_path / "figures"
    card_dir = figures_dir / "cards" / "crispr"
    card_dir.mkdir(parents=True)
    (card_dir / "figure_waterfall.plotly.json").write_text(
        json.dumps({"data": [{"type": "bar", "x": [1], "y": [-1]}], "layout": {}}))
    (card_dir / "figure_waterfall.svg").write_text(
        "<svg xmlns='http://www.w3.org/2000/svg'><rect width='10' height='10'/></svg>")
    card_figures = {"crispr": [
        {"id": "waterfall", "path": "cards/crispr/figure_waterfall.plotly.json", "type": "plotly", "dynamic": True},
        {"id": "waterfall_svg", "path": "cards/crispr/figure_waterfall.svg", "type": "svg", "primary": True},
    ]}
    return card_figures, figures_dir


def test_self_contained_inlines_svg_and_has_no_external_deps(tmp_path):
    cf, fd = _write_figs(tmp_path)
    h = tp._render_target_profile_html("KRAS", "COADREAD", _sr(), _LLM, {},
                                       card_figures=cf, figures_dir=fd, embed="self_contained")
    assert "data:image/svg+xml;base64," in h          # figure inlined as a data-URI <img>
    assert "cdn.plot.ly" not in h                      # NO CDN fetch
    assert "class=plotly-spec" not in h                # NO plotly spec scripts
    assert "plt-card-" not in h                        # NO plotly divs


def test_interactive_default_still_uses_plotly_cdn(tmp_path):
    cf, fd = _write_figs(tmp_path)
    h = tp._render_target_profile_html("KRAS", "COADREAD", _sr(), _LLM, {},
                                       card_figures=cf, figures_dir=fd)   # default embed
    assert "cdn.plot.ly" in h and "class=plotly-spec" in h
    assert "data:image/svg+xml;base64," not in h       # interactive path does not inline SVGs
