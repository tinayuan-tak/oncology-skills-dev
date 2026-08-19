"""dependency_question_table — the 7-question (data · signal · confidence) projection that leads the
functional-requirement dashboard. Verdict-inert; computed from the DEP/SEL/COND/CHEM claim_vector +
answer-key card fields.

Hermetic: a fixture headline + cards + explicit claim_vector (KRAS/COADREAD-shaped: strong selective
CRISPR dependency, concordant RNAi, Bowel lineage-selective via the by_scope reduction, chemically
confirmed, cross-consortium corroborated) exercise the per-question mapping, including the Q2 window
INVERSION (near pan-essential = tox) and the Q3 preference for the indication-lineage reduction."""
from __future__ import annotations

import sys
from pathlib import Path

COMMON = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMMON.parent))  # skills/

from _skills_common.dependency_question_table import dependency_question_table  # noqa: E402


def _fixture():
    headline = {
        "dependency_verdict": "lineage_selective",
        "crispr_call": "strongly_selective", "rnai_call": "strongly_selective",
        "concordance_call": "moderately_concordant_dependent", "lineage_selectivity": "lineage_selective",
        "paralog_buffering_class": "none", "partner_conditional_class": "no_partner_mapped",
        "prism_concordance_class": "crispr_confirmed_engagement", "n_compounds_evaluated": 4,
        "cross_consortium_class": "concordant_dependent", "predictability_class": "own_omics_driven",
        "pred_dominant_feature_class": "own_expression", "dependency_confidence": "high",
        "n_lineages_evaluated": 26,
        "dependency_verdict_by_scope": {
            "pan_cancer": {"verdict": "lineage_selective"},
            "indication": {"class": "selective_in_indication", "depmap_lineage": "Bowel",
                           "q_value": 3.8e-16, "shared_lineage_caveat": False},
            "subtype": {"class": "not_scoped_this_run"}},
    }
    cv = {
        "DEP":  {"signal": "strong", "corroboration": "high", "evidence": "CRISPR strongly_selective; RNAi strongly_selective"},
        "SEL":  {"signal": "strong", "corroboration": "moderate", "evidence": "lineage enrichment: lineage_selective"},
        "COND": {"signal": "unmeasured", "corroboration": "unmeasured", "evidence": "partner-conditional: no_partner_mapped"},
        "CHEM": {"signal": "moderate", "corroboration": "moderate", "evidence": "PRISM×CRISPR: crispr_confirmed_engagement"},
    }
    cards = [
        {"card_id": "pan-cancer-crispr-dependency-distribution",
         "summary": {"dep_control_position_class": "between_controls", "selectivity_index": 0.62,
                     "n_cell_lines_evaluated": 1538, "dep_control_position_context": "selective window"}},
        {"card_id": "crispr-rnai-dependency-concordance",
         "summary": {"concordance_class": "moderately_concordant_dependent", "fraction_agree": 0.746, "n_in_both": 556}},
    ]
    return headline, cards, cv


def _by_id(rows):
    return {r["id"]: r for r in rows}


def test_seven_rows_in_order():
    rows = dependency_question_table(*_fixture())
    assert [r["id"] for r in rows] == ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7"]


def test_q1_lethal_from_claim_DEP_with_rnai_concordance_support():
    r = _by_id(dependency_question_table(*_fixture()))["Q1"]
    assert r["signal"]["tier"] == "strong" and r["signal"]["polarity"] == "supports"
    assert "RNAi strongly_selective" in r["support"] and "concordance" in r["support"]


def test_q2_window_between_controls_supports_but_pan_essential_inverts():
    r = _by_id(dependency_question_table(*_fixture()))["Q2"]
    # between_controls = a selective therapeutic window → supports
    assert r["signal"]["polarity"] == "supports" and r["signal"]["fill"] == 5
    assert "selectivity index" in r["primary"]
    # the INVERSION: near pan-essential is a tox liability, NOT a win
    h, cards, cv = _fixture()
    cards[0]["summary"]["dep_control_position_class"] = "as_essential_as_pan_essential"
    r2 = _by_id(dependency_question_table(h, cards, cv))["Q2"]
    assert r2["signal"]["polarity"] == "opposes" and "tox" in r2["signal"]["label"]


def test_q3_prefers_indication_lineage_reduction():
    r = _by_id(dependency_question_table(*_fixture()))["Q3"]
    # the by_scope indication rung (Bowel selective_in_indication) drives, not "selective to SOME lineage"
    assert "Bowel" in r["primary"] and "selective_in_indication" in r["primary"]
    assert r["signal"]["tier"] == "strong"


def test_q4_concordance_and_q6_chemical():
    rows = _by_id(dependency_question_table(*_fixture()))
    assert rows["Q4"]["signal"]["tier"] == "moderate" and "agree" in rows["Q4"]["primary"]
    assert rows["Q6"]["signal"]["tier"] == "moderate" and "4 PRISM compounds" in rows["Q6"]["support"]


def test_q7_corroboration_is_the_confidence_axis():
    r = _by_id(dependency_question_table(*_fixture()))["Q7"]
    assert r["signal"]["tier"] == "strong"                 # concordant_dependent cross-consortium
    assert "own_omics_driven" in r["support"]
    assert r["confidence"]["tier"] == "high"


def test_verdict_inert_no_exceptions_on_sparse_headline():
    rows = dependency_question_table({}, [], {"DEP": {}, "SEL": {}, "COND": {}, "CHEM": {}})
    assert len(rows) == 7
    assert all(r["signal"]["tier"] == "unmeasured" for r in rows if r["id"] in ("Q1", "Q5"))
