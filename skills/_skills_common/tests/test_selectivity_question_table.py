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

from _skills_common.presence_question_table import render_question_table_html  # noqa: E402 (shared renderer)
from _skills_common.selectivity_claims import selectivity_claim_vector  # noqa: E402
from _skills_common.selectivity_question_table import selectivity_question_table  # noqa: E402


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


def _concordant_headline():
    """CEACAM5-shaped, plus a corroborating CPTAC protein window → both independent arms agree."""
    h = _ceacam5_headline()
    h["protein_tumor_vs_normal_effect_size"] = 1.8
    h["protein_tumor_vs_normal_q_value"] = 0.001
    return h


def test_integrated_signal_attached_to_q1_row_when_claim_resolves():
    # SK#1803: the selectivity_concordance claim reaches the axis-A / tumor-vs-normal (Q1) answer row as
    # an additive integrated_signal.
    h = _concordant_headline()
    h["claim_vector"] = selectivity_claim_vector(h, [])
    rows = {r["id"]: r for r in selectivity_question_table(h, [])}
    isig = rows["Q1"].get("integrated_signal")
    assert isig is not None and isig["kind"] == "selectivity_concordance"
    assert isig["concordance_class"] == "selectivity_window_concordant"
    assert isig["corroboration"] == "high"
    assert isig["provenance_ref"] == "claim_vector.selectivity_concordance"
    assert isig["qualifying_signal"] is None  # concordant → no caveat
    assert isig["positive_signal"] and "statement" in isig["positive_signal"]
    assert isig["boundary_sensitive"] is False
    # NO other question row carries the annotation (Q1 is the tumor-vs-normal window question)
    assert all("integrated_signal" not in rows[k] for k in ("Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8"))
    # verdict-inert: Q1's meter cells are UNCHANGED by the annotation
    q1_bare = {r["id"]: r for r in selectivity_question_table(_ceacam5_headline(), [], claim_vector={})}["Q1"]
    assert rows["Q1"]["signal"] == q1_bare["signal"] and rows["Q1"]["confidence"] == q1_bare["confidence"]


def test_row_byte_stable_when_claim_absent():
    # Neither independent arm resolves → claim omitted → NO integrated_signal key (row byte-stable).
    h = _ceacam5_headline()
    h["axis_a_selectivity_class"] = "data_unavailable"  # RNA unresolved; no protein fields → arm unresolved
    h["claim_vector"] = selectivity_claim_vector(h, [])
    assert "selectivity_concordance" not in h["claim_vector"]
    assert "integrated_signal" not in {r["id"]: r for r in selectivity_question_table(h, [])}["Q1"]
    # a claim_vector present but WITHOUT selectivity_concordance also leaves the row untouched
    cv_no_sc = {"WIN": {"signal": "moderate", "corroboration": "moderate"}}
    assert (
        "integrated_signal"
        not in {r["id"]: r for r in selectivity_question_table(_ceacam5_headline(), [], claim_vector=cv_no_sc)}["Q1"]
    )


def test_integrated_signal_single_source_degrades():
    # Only the RNA arm resolves (no protein fields) → single_source_only, surfaced WITH a caveat.
    h = _ceacam5_headline()
    h["claim_vector"] = selectivity_claim_vector(h, [])
    isig = {r["id"]: r for r in selectivity_question_table(h, [])}["Q1"]["integrated_signal"]
    assert isig["concordance_class"] == "single_source_only"
    assert isig["qualifying_signal"] is not None  # names the gap arm
    assert isig["boundary_sensitive"] is True


def test_shared_renderer_emits_html():
    h = _ceacam5_headline()
    h["claim_vector"] = selectivity_claim_vector(h, [])
    html = render_question_table_html(selectivity_question_table(h, []), verdict=h["selectivity_class"])
    assert "<table" in html and "Q1" in html and "field_effect_tumor_selective" in html


# ── #1831: Q2 must honour comparator_concordance, not the raw cell count ──────────────────────────
def _q2(headline):
    h = dict(headline)
    h["claim_vector"] = selectivity_claim_vector(h, [])
    return {r["id"]: r for r in selectivity_question_table(h, [])}["Q2"]


def test_q2_single_comparator_capped_regardless_of_cell_count():
    """An adjacent-only run (cells A raw + B ComBat = ONE comparison, GTEx never resolved) must NOT
    render as high/'N/N independent comparators agree' even when every cell agrees and sig_all is set —
    the cell-count path must not re-inflate the row when concordance says single-family."""
    h = _ceacam5_headline()
    h.update(
        {
            "cells_supporting": 3.0,
            "cells_ran": 3.0,
            "discordant": False,
            "sig_all_cells": True,
            "comparator_concordance": "single_comparator",
        }
    )
    r = _q2(h)
    assert r["confidence"]["tier"] != "high"
    assert r["signal"]["tier"] != "strong"
    assert "independent comparators agree" not in r["primary"]


def test_q2_discordant_concordance_caps_and_opposes():
    h = _ceacam5_headline()
    h.update(
        {
            "cells_supporting": 3.0,
            "cells_ran": 3.0,
            "discordant": False,
            "sig_all_cells": True,
            "comparator_concordance": "discordant",
        }
    )
    r = _q2(h)
    assert r["confidence"]["tier"] != "high"
    assert r["signal"]["polarity"] == "opposes"


def test_q2_concordant_unchanged_positive_rendering():
    """A genuine two-family concordant call keeps today's rendering (sig_all → high + N/N wording)."""
    h = _ceacam5_headline()
    h.update(
        {
            "cells_supporting": 3.0,
            "cells_ran": 3.0,
            "discordant": False,
            "sig_all_cells": True,
            "comparator_concordance": "concordant",
        }
    )
    r = _q2(h)
    assert r["confidence"]["tier"] == "high"
    assert r["signal"]["tier"] == "strong"
    assert "independent comparators agree" in r["primary"]
