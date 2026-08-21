"""target-profile renders the Selectivity leading table from the selectivity_facet (Phase R).

tumor-selectivity's _synthesis_facet carries the 8-question `question_table` (WIN/DIST/INT/SAFE) into
the composed dashboard; these tests pin that a human reader SEES it (the .html gets the shared
question-table section), and that it is purely ADDITIVE + verdict-inert (no facet → section omitted,
render still works).
"""
from __future__ import annotations
import importlib.util
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_run_sel", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


tp = _load()


def _sr():
    return {
        "selectivity": {"skill_dir": "tumor-selectivity", "cards": [{"card_id": "c", "summary": {}}],
                        "verdict": ("field_effect_tumor_selective", "r"), "fired": []},
        "safety": {"skill_dir": "on-target-safety-liability", "cards": [{"card_id": "g", "summary": {}}],
                   "verdict": ("some_safety", "y"), "fired": []},
    }


_LLM = {"executive_summary": {"value": "exec"}, "overall_recommendation": {"value": "hold"},
        "confidence": {"value": "high"}, "tension_analysis": {"value": "t"}}


def _facet():
    return {
        "selectivity_class": "selective_with_normal_liability",
        "driving_rule_id": "tvn-sc-normal-critical-organ-veto",
        "axis_a_selectivity_class": "strong_tumor_selective",
        "sc_normal_safety_essential_class": "critical_organ_liability",
        "question_table": [
            {"id": "Q1", "question": "Over-expressed vs tissue-of-origin?", "primary": "axis-A strong",
             "support": "RNA→protein: rna_protein_concordant",
             "signal": {"tier": "strong", "fill": 5, "polarity": "supports", "label": "strong"},
             "confidence": {"tier": "high", "dots": 3, "label": "high"}},
            {"id": "Q5", "question": "Window vs the WORST critical normal? (the gate)",
             "primary": "sc-normal critical_organ_liability",
             "support": "named-organ liability: kidney loop of Henle epithelial cell",
             "signal": {"tier": "negative", "fill": 1, "polarity": "opposes", "label": "negative"},
             "confidence": {"tier": "high", "dots": 3, "label": "high"}},
        ],
    }


def test_html_renders_selectivity_table_when_facet_present():
    html = tp._render_target_profile_html("FOLR1", "OV", _sr(), _LLM, {}, selectivity_facet=_facet())
    assert "Selectivity at a glance" in html
    assert "s-selectivity-table" in html
    assert "<table" in html and "Q1" in html and "Q5" in html
    assert "selective_with_normal_liability" in html          # the caption verdict
    assert "loop of Henle" in html                            # the named-organ liability surfaced


def test_html_omits_selectivity_table_without_facet():
    html = tp._render_target_profile_html("FOLR1", "OV", _sr(), _LLM, {})
    assert "s-selectivity-table" not in html
    assert "Selectivity at a glance" not in html
