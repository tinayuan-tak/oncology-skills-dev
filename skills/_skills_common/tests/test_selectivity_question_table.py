"""Selectivity question-table (leading graphic) — offline, no S3.

Pins the 8-row shape + the claim-driven signal mapping + that the SHARED render_question_table_html
renders it. Verdict-inert: a projection over the headline + claim_vector.
"""

from __future__ import annotations
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.selectivity_question_table import selectivity_question_table  # noqa: E402
from _skills_common.selectivity_claims import selectivity_claim_vector  # noqa: E402
from _skills_common.presence_question_table import render_question_table_html  # noqa: E402 (shared renderer)


def _ceacam5_headline():
    """A CEACAM5/COADREAD-shaped headline: field-effect selective, clean window, malignant-intrinsic."""
    return {
        "selectivity_class": "field_effect_tumor_selective",
        "axis_a_selectivity_class": "field_effect_tumor_selective",
        "cells_supporting": 1.0,
        "cells_ran": 3.0,
        "discordant": True,
        "sig_all_cells": False,
        "max_abs_log2fc": 2.94,
        "percentile_crossing_class": "strongly_tumor_enriched",
        "fraction_tumor_above_normal_p95": 0.76,
        "distribution_overlap_tumor_normal": 0.25,
        "selectivity_allgene_percentile": 26.7,
        "selectivity_allgene_percentile_class": "mid",
        "therapeutic_window_class": "clean_window",
        "sc_normal_safety_essential_class": "origin_tissue_liability",
        "sc_tumor_expression_class": "malignant_broadly_detected",
        "sc_malignant_detection_fraction": 0.76,
        "sc_caf_vs_malignant_class": "caf_low",
        "purity_confound_class": "purity_independent",
        "rna_protein_tvn_concordance": "rna_protein_concordant",
        "absolute_surface_density_class": "high",
        "absolute_copies_per_cell": 76000.0,
        "density_floor_verdict": "above_adc_high_payload_floor",
        "absolute_density_grade": "B",
        "spatial_rna_class": "tumour_enriched_rna",
        "spatial_coloc_class": "immune_excluded",
    }


def test_eight_rows_with_expected_ids():
    h = _ceacam5_headline()
    h["claim_vector"] = selectivity_claim_vector(h, [])
    rows = selectivity_question_table(h, [])
    assert [r["id"] for r in rows] == ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8"]
    # every row has the render contract shape
    for r in rows:
        assert set(("id", "question", "primary", "support", "signal", "confidence")) <= set(r)
        assert set(("fill", "polarity", "label")) <= set(r["signal"])
        assert "dots" in r["confidence"]


def test_win_and_dist_positive_for_clean_selective():
    h = _ceacam5_headline()
    h["claim_vector"] = selectivity_claim_vector(h, [])
    rows = {r["id"]: r for r in selectivity_question_table(h, [])}
    # DIST strongly enriched → supports; WIN field-effect → present (not opposing)
    assert rows["Q3"]["signal"]["polarity"] == "supports"
    # Q1 surfaces the RNA→protein concordance in support
    assert "rna_protein_concordant" in rows["Q1"]["support"]
    # clean window → SAFE not opposing
    assert rows["Q5"]["signal"]["polarity"] != "opposes"


def test_critical_organ_liability_opposes_on_q5():
    h = _ceacam5_headline()
    h["sc_normal_safety_essential_class"] = "critical_organ_liability"
    h["sc_normal_max_detection_cell_type"] = "kidney loop of Henle epithelial cell"
    h["selectivity_class"] = "selective_with_normal_liability"
    h["claim_vector"] = selectivity_claim_vector(h, [])
    rows = {r["id"]: r for r in selectivity_question_table(h, [])}
    assert rows["Q5"]["signal"]["polarity"] == "opposes"
    assert "loop of Henle" in rows["Q5"]["support"]


def test_shared_renderer_emits_html():
    h = _ceacam5_headline()
    h["claim_vector"] = selectivity_claim_vector(h, [])
    html = render_question_table_html(selectivity_question_table(h, []), verdict=h["selectivity_class"])
    assert "<table" in html and "Q1" in html and "field_effect_tumor_selective" in html
