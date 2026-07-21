"""Gate-section dashboard: card-subtabbed gate sections + presence-only focused view (2026-07-21).

The presence gate (A / expression) renders as a section whose SUBTABS are its evidence cards; each
card panel is a 2-column body (plots left, summary rail right) with a verdict/rule strip, key facts,
an indication-lineage focus (COADREAD→Bowel) + human-readable interpretation, and the card's Plotly
figure. Pure projection — no recompute. `presence_only=True` is the focused view: clean "T × I"
header, no About/statusbar/scorecard, tab bootstrap always present.

Bedrock-free (synthetic sub_results + a fake figures dir; no S3, no plotly bundle assertions).
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_gate", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


tp = _load()


def _fired(rid, cid, sig):
    return {"rule_id": rid, "card_id": cid, "field": "f", "value": "v", "signals": sig}


def _sr(per_lineage=None):
    expr = {"expression_call_class": "broadly_high", "median_log2tpm_panel": 5.6, "n_cell_lines": 820}
    if per_lineage is not None:
        expr["per_lineage_stats"] = per_lineage
        expr["n_lineages_evaluated"] = len(per_lineage)
    return {
        "expression": {"skill_dir": "tumor-presence", "cards": [
            {"card_id": "expression-distribution", "summary": expr},
            {"card_id": "protein-abundance-celline", "summary": {"protein_expression_class": "broadly_moderate"}},
            {"card_id": "tumor-elevation-breadth",
             "summary": {"tumor_elevation_breadth_class": "multi_tumor_elevated",
                         "n_cohorts_elevated": 2, "rna_n_indications_elevated": 4}}],
            "verdict": ("broadly_high_expression", "expression-broadly-high-supportive"),
            "fired": [_fired("expression-broadly-high-supportive", "expression-distribution",
                             {"small_molecule": "supportive", "degrader": "supportive"}),
                      _fired("tumor-breadth-multi-supportive", "tumor-elevation-breadth",
                             {"small_molecule": "supportive"})]},
        "dependency": {"skill_dir": "functional-requirement",
                       "cards": [{"card_id": "crispr", "summary": {}}],
                       "verdict": ("lineage_selective", "lineage-selective-supportive"), "fired": []},
    }


_LLM = {"executive_summary": {"value": "KRAS broadly expressed.", "_prompt_hash": "x"},
        "overall_recommendation": {"value": "advance"}, "confidence": {"value": "moderate"},
        "tension_analysis": {"value": "—"}}


def _render(sr, **kw):
    return tp._render_target_profile_html("KRAS", "COAD", sr, _LLM, {},
                                          scorecard=tp._gate_scorecard(sr, None), **kw)


# --- gate section structure ---------------------------------------------------

def test_presence_gate_section_has_card_subtabs():
    h = _render(_sr())
    assert "id=s-gate-a" in h
    # one tab button per card (3 cards)
    assert h.count("data-panel=s-gate-a-p") == 3
    for title in ("Cell-line RNA", "Cell-line protein", "Pan-cancer breadth"):
        assert title in h, title


def test_card_panel_is_two_column_with_rail():
    h = _render(_sr())
    assert "card-body" in h and "card-plots" in h and "card-rail" in h
    # rail carries the rule-fired strip
    assert "Rule fired" in h and "expression-broadly-high-supportive" in h


def test_indication_lineage_focus_and_interpretation():
    per_lineage = [
        {"lineage": "Lung", "n": 90, "median_log2tpm": 6.1, "fraction_expressed": 0.95},
        {"lineage": "Bowel", "n": 103, "median_log2tpm": 5.55, "fraction_expressed": 0.99},
        {"lineage": "Skin", "n": 40, "median_log2tpm": 2.0, "fraction_expressed": 0.5},
    ]
    h = _render(_sr(per_lineage))
    assert "COAD focus (Bowel)" in h                       # indication → lineage
    assert "In Bowel cell lines" in h                       # human-readable interpretation
    assert "highly expressed" in h                          # bucketed level (median 5.55 ≥ 5)


def test_indication_focus_absent_when_lineage_below_floor():
    # per_lineage_stats present but Bowel absent (didn't clear n>=5) → honest 'not available' note
    per_lineage = [{"lineage": "Lung", "n": 90, "median_log2tpm": 6.1, "fraction_expressed": 0.95}]
    h = _render(_sr(per_lineage))
    assert "COAD focus (Bowel)" in h
    assert "isn't available" in h or "No Bowel cell-line cohort" in h


# --- presence-only focused view ----------------------------------------------

def test_presence_only_strips_full_report_sections():
    h = _render(_sr(), presence_only=True)
    assert "About this analysis" not in h
    assert "Evaluated " not in h            # statusbar gone
    assert "Gate scorecard" not in h        # scorecard gone
    assert "Risk by category" not in h
    # but the presence gate + exec summary remain
    assert "id=s-gate-a" in h and "Executive summary" in h


def test_presence_only_clean_header():
    h = _render(_sr(), presence_only=True)
    assert "<h1>KRAS" in h and "COAD</h1>" in h
    assert "target profile</h1>" not in h   # no verbose suffix
    assert "Recommendation:" not in h        # no rec clutter


def test_tab_bootstrap_always_present_when_gate_rendered():
    h = _render(_sr(), presence_only=True)
    assert "tabs-js" in h and "__resizePlots" in h   # tab JS + plotly resize hook


def test_full_report_still_renders_all_sections():
    h = _render(_sr(), presence_only=False)
    assert "Gate scorecard" in h and "id=s-gate-a" in h   # both the scorecard AND the new gate section
