"""Offline render test for the SHARED headline hero (skills/_skills_common/headline_hero.py).

The hero renders from a fixture `headline_block` with NO live read. Pins the honesty discipline: an
unmeasured axis is a hatched gap (never a zero-length bar), the verdict phrase + confidence appear, and
emit_headline_hero writes the {svg,json} artifacts (png best-effort). Pure — no S3, no matplotlib needed
for the SVG/JSON assertions.
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]        # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.headline_hero import render_headline_hero_svg, emit_headline_hero  # noqa: E402

HERO = {
    "kind": "headline_hero",
    "verdict": {"call": "present", "phrase": "Present (low abundance)", "gate": "presence"},
    "confidence": {"level": "moderate", "coverage": {"n_measured": 3, "n_axes": 4}},
    "tension": {"text": "abundance floor: bottom-decile in CPTAC"},
    "axes": [
        {"key": "A", "label": "abundance", "signal": "strong", "corroboration": "high", "conflict": False},
        {"key": "B", "label": "tumor-elevation", "signal": "moderate", "corroboration": "moderate", "conflict": True},
        {"key": "C", "label": "malignant-intrinsic", "signal": "unmeasured", "corroboration": "unmeasured", "conflict": False},
        {"key": "D", "label": "generality", "signal": "strong", "corroboration": "low", "conflict": False},
    ],
}
BLOCK = {"verdict": HERO["verdict"], "confidence": HERO["confidence"],
         "top_tension": HERO["tension"], "headline_text": "Present (low abundance) — moderate confidence.",
         "hero": HERO}


def test_svg_renders_offline_with_verdict_and_confidence():
    svg = render_headline_hero_svg(HERO, "EPCAM", "COADREAD")
    assert svg.startswith("<svg")
    assert "EPCAM · COADREAD" in svg
    assert "Present (low abundance)" in svg
    assert "confidence" in svg and "moderate" in svg


def test_unmeasured_axis_is_hatched_gap_not_zero_bar():
    svg = render_headline_hero_svg(HERO, "EPCAM", "COADREAD")
    # the unmeasured C axis must render the hatch pattern + gap label, never a 0-width tier bar
    assert "url(#hhna)" in svg
    assert "unmeasured (gap)" in svg


def test_conflict_axis_marked():
    svg = render_headline_hero_svg(HERO, "EPCAM", "COADREAD")
    assert "⚠" in svg                       # B carries a conflict → warning glyph


def test_emit_writes_artifacts(tmp_path):
    decision = {"target": "EPCAM", "indication": "COADREAD", "headline": {"headline_block": BLOCK}}
    paths = emit_headline_hero(decision, tmp_path)
    names = {p.name for p in paths}
    assert "figure_headline_hero.svg" in names
    assert "figure_headline_hero.json" in names
    assert (tmp_path / "figure_headline_hero.svg").read_text().startswith("<svg")


def test_emit_noop_without_block(tmp_path):
    assert emit_headline_hero({"headline": {}}, tmp_path) == []
    assert emit_headline_hero({}, tmp_path) == []
