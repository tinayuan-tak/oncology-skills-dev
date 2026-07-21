"""Dynamic-dashboard Phase B (PR-2) — the HTML report embeds interactive Plotly figures.

When a run produced per-card interactive specs (`card_figures` + `figures_dir`), the report embeds
them inline: a <div> per figure, its Plotly JSON in a sibling <script type=application/json>, plotly.js
inlined ONCE, and a vanilla-JS bootstrap that draws them. When no figure was produced (the default),
the report degrades to static tables with NO JS (guarded by test_html_report_and_scorecard). These
tests pin the dynamic path + the honesty invariants (self-contained: plotly.js inlined not CDN'd;
renderer embeds the method-drawn spec, never re-plots). Bedrock-free — synthetic specs on disk.
"""
from __future__ import annotations

import importlib.util
import json
import re
from html.parser import HTMLParser
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_run_embed", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


tp = _load()

_LLM = {"executive_summary": {"value": "KRAS is modality-constrained.", "_prompt_hash": "abc"},
        "overall_recommendation": {"value": "hold"}, "confidence": {"value": "high"},
        "tension_analysis": {"value": "t"}}


def _sr():
    return {
        "dependency": {"skill_dir": "functional-requirement",
                       "cards": [{"card_id": "crispr", "summary": {"median_chronos": -1.2}}],
                       "verdict": ("lineage_selective", "r-x"), "fired": []},
    }


def _tiny_plotly_spec():
    return json.dumps({"data": [{"type": "bar", "x": [1, 2, 3], "y": [-2.5, -1.0, 0.2]}],
                       "layout": {"title": "KRAS waterfall"}})


def _write_figs(tmp_path):
    """Write a real .plotly.json under figures/cards/crispr/ and return (card_figures, figures_dir)."""
    figures_dir = tmp_path / "figures"
    card_dir = figures_dir / "cards" / "crispr"
    card_dir.mkdir(parents=True)
    (card_dir / "figure_waterfall.plotly.json").write_text(_tiny_plotly_spec())
    card_figures = {"crispr": [
        {"id": "waterfall", "path": "cards/crispr/figure_waterfall.plotly.json",
         "type": "plotly", "dynamic": True},
        {"id": "waterfall_svg", "path": "cards/crispr/figure_waterfall.svg",
         "type": "svg", "primary": True},   # the SVG descriptor is ignored by the embed
    ]}
    return card_figures, figures_dir


def _dynamic_html(tmp_path):
    cf, fd = _write_figs(tmp_path)
    return tp._render_target_profile_html(
        "KRAS", "COADREAD", _sr(), _LLM, {}, card_figures=cf, figures_dir=fd)


def test_dynamic_html_embeds_plotly_div_and_spec(tmp_path):
    h = _dynamic_html(tmp_path)
    assert "class=plotly-fig" in h                        # a figure div is present
    assert "class=plotly-spec" in h                       # its JSON spec block is present
    assert '"KRAS waterfall"' in h                        # the spec content is inlined verbatim
    assert "data-target=plt-dependency-waterfall" in h    # spec wired to its div id


def test_dynamic_html_inlines_plotlyjs_and_bootstrap(tmp_path):
    h = _dynamic_html(tmp_path)
    assert "Plotly.newPlot" in h                          # the vanilla-JS bootstrap
    assert "plotly.js" in h.lower()                        # the inlined bundle (its banner comment)
    # self-contained: no external resource is LOADED. We check the TAGS we emit — not raw substrings,
    # because the inlined ~4.6 MB plotly.js legitimately contains "https://" URLs in its own comments
    # and error strings. The invariant is "nothing is fetched", i.e. no <script src=>, <link>, <img src=http>.
    assert re.search(r"<script\b[^>]*\bsrc=", h) is None   # every <script> is inline (no src=)
    assert "<link" not in h                                 # no external stylesheet
    assert re.search(r"<img\b[^>]*\bsrc=[\"']?https?://", h) is None


def test_dynamic_html_is_wellformed_and_marks_interactive(tmp_path):
    h = _dynamic_html(tmp_path)
    HTMLParser().feed(h)                                  # raises on malformed structure
    assert h.startswith("<!DOCTYPE") and h.rstrip().endswith("</html>")
    assert "Interactive self-contained governance artifact" in h
    # honesty: the footer states charts are pre-computed + embedded, not re-plotted
    assert "embedded, not re-plotted" in h


def test_static_fallback_when_no_figures_has_no_js(tmp_path):
    """A run that produced no interactive figure → static tables, zero JS (plotly.js NOT inlined —
    the ~4.6 MB payload is only paid when there's something to draw)."""
    h = tp._render_target_profile_html("KRAS", "COADREAD", _sr(), _LLM, {})
    assert re.search(r"<script[ >]", h) is None
    assert "Plotly.newPlot" not in h
    assert "Static self-contained governance artifact" in h


def test_missing_spec_file_degrades_to_table_not_crash(tmp_path):
    """A card_figures descriptor whose .plotly.json is absent on disk must NOT blow up the render
    (drops to the static table) — and must NOT inline plotly.js for a figure it couldn't read."""
    cf = {"crispr": [{"id": "ghost", "path": "cards/crispr/missing.plotly.json",
                      "type": "plotly", "dynamic": True}]}
    fd = tmp_path / "figures"
    fd.mkdir()
    h = tp._render_target_profile_html("KRAS", "COADREAD", _sr(), _LLM, {},
                                       card_figures=cf, figures_dir=fd)
    assert "Plotly.newPlot" not in h                      # nothing drawable → no JS layer
    assert "median chronos" in h.lower() or "Median chronos" in h  # the table still rendered
