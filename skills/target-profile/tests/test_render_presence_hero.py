"""target-profile renders the Presence × Context hero from the presence_facet.

#483 plumbed tumor-presence's cross-modal reconciliation into the synthesis (presence_facet). These
tests pin that a human reader also SEES it: the .md gets a "Presence × context" table + proxy/normal
framing; the .html gets the inline SVG state-matrix. Both are DETERMINISTIC VIEWS (labelled not-a-
score) and purely additive — a render with no presence_facet still works and omits the section.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_run", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


tp = _load()


def _sr():
    return {
        "expression": {"skill_dir": "tumor-presence", "cards": [{"card_id": "c", "summary": {}}],
                       "verdict": ("tumor_broadly_expressed", "r"), "fired": []},
        "safety": {"skill_dir": "on-target-safety-liability", "cards": [{"card_id": "g", "summary": {}}],
                   "verdict": ("some_safety", "y"), "fired": []},
    }


_LLM = {"executive_summary": {"value": "exec"}, "overall_recommendation": {"value": "hold"},
        "confidence": {"value": "high"}, "tension_analysis": {"value": "t"}}


def _facet():
    return {
        "presence_verdict": "tumor_broadly_expressed", "driving_rule_id": "tumor-expression-broadly-high-supportive",
        "headline_lens": "bulk_rna/tumor", "cell_line_vs_tumor_discordant": True,
        "presence_interpretation_note": "one-word verdict understates tumor presence",
        "bulk_rna_proxy_quality": "rna_positive_proxy_partial", "bulk_rna_proxy_quality_source": "tumor",
        "rna_as_biomarker": "adequate_proxy", "rna_protein_r": 0.86,
        "rna_as_biomarker_tumor": "partial_proxy", "rna_protein_r_tumor": 0.41,
        "normal_tissue_ihc_breadth_class": "broad_normal_expression",
        "sc_normal_expression_class": "HIGH_LIABILITY",
        "sc_normal_max_det_cell_type": "BEST4+ colonocyte", "sc_normal_max_det_fraction": 1.0,
        "presence_verdict_by_modality": {
            "bulk_rna/cell_line": {"verdict": "lineage_restricted", "evidence_state": "measured",
                                   "driving_rule_id": "expression-lineage-restricted-supportive"},
            "bulk_rna/tumor": {"verdict": "tumor_broadly_expressed", "evidence_state": "measured",
                               "driving_rule_id": "tumor-expression-broadly-high-supportive"},
            "sc_rna/normal": {"verdict": "HIGH_LIABILITY", "evidence_state": "comparator",
                              "driving_rule_id": None},
        },
        # the 7-question rows carried through the facet (rendered as the leading table by target-profile)
        "question_table": [
            {"id": "Q1", "question": "Expressed in cancers at all?", "primary": "median 11 log2TPM",
             "support": "cell-line: lineage_restricted",
             "signal": {"tier": "strong", "fill": 5, "polarity": "supports", "label": "strong"},
             "confidence": {"tier": "moderate", "dots": 2, "label": "moderate"}},
            {"id": "Q3", "question": "Elevated vs normals (adjacent + GTEx)?", "primary": "CPTAC up; RNA-DGE flat",
             "support": "HPA broad_normal_expression · sc HIGH_LIABILITY",
             "signal": {"tier": "moderate", "fill": 3, "polarity": "supports", "label": "moderate ⚠ window"},
             "confidence": {"tier": "moderate", "dots": 2, "label": "moderate"}},
        ],
    }


def test_md_renders_presence_table_when_facet_present():
    md = tp._render_target_profile_md("CEACAM5", "COADREAD", _sr(), _LLM, {}, presence_facet=_facet())
    assert "## Presence × context" in md
    assert "bulk_rna/tumor" in md and "sc_rna/normal" in md
    assert "rna_positive_proxy_partial" in md            # proxy-quality surfaced
    assert "HIGH_LIABILITY" in md                          # normal-tissue window framing
    assert "understates tumor presence" in md             # discordance caveat


def test_md_omits_presence_table_without_facet():
    md = tp._render_target_profile_md("CEACAM5", "COADREAD", _sr(), _LLM, {})
    assert "## Presence × context" not in md


def test_html_inlines_presence_matrix_svg_when_facet_present():
    html = tp._render_target_profile_html("CEACAM5", "COADREAD", _sr(), _LLM, {}, presence_facet=_facet())
    assert "Presence × context" in html
    assert "s-presence-matrix" in html
    assert "<svg" in html                                  # the hero SVG is inlined
    assert "Deterministic VIEW" in html                    # honesty label


def test_html_omits_presence_matrix_without_facet():
    html = tp._render_target_profile_html("CEACAM5", "COADREAD", _sr(), _LLM, {})
    assert "s-presence-matrix" not in html


def test_html_renders_question_table_from_facet():
    """The composed dashboard inherits the 7-question leading table from the presence facet's
    question_table rows, via the shared renderer (same table the standalone gallery shows)."""
    html = tp._render_target_profile_html("CEACAM5", "COADREAD", _sr(), _LLM, {}, presence_facet=_facet())
    assert "s-presence-table" in html and "Presence at a glance" in html
    assert "Expressed in cancers at all?" in html          # a question row
    assert "class=\"qtable\"" in html and "class=\"seg" in html  # table + signal meter markup
    assert "⚠ window" in html                               # the Q3 window caveat carried through


def test_html_omits_question_table_without_facet():
    html = tp._render_target_profile_html("CEACAM5", "COADREAD", _sr(), _LLM, {})
    assert "s-presence-table" not in html
