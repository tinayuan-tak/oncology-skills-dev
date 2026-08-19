"""presence_question_table — the 7-question (data · signal · confidence) projection that leads the
tumor-presence dashboard. Verdict-inert; computed from the claim_vector + answer-key card fields.

Hermetic: a fixture headline + cards + an explicit claim_vector (so the test does not depend on the
claim_vector's own computation details) exercise the per-question mapping and the CEACAM5-shaped story
(strong abundance, comparator-discordance window caveat, uniform subtypes, top-1% absolute, malignant-
intrinsic)."""
from __future__ import annotations

import sys
from pathlib import Path

COMMON = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMMON.parent))  # skills/

from _skills_common.presence_question_table import presence_question_table  # noqa: E402


def _fixture():
    headline = {"presence_verdict": "tumor_broadly_expressed"}
    cv = {
        "A": {"signal": "strong", "corroboration": "moderate", "evidence": "anchored: top 1% all-gene"},
        "B": {"signal": "moderate", "corroboration": "moderate", "evidence": "CPTAC:up; RNA-DGE:flat",
              "conflict": "comparator discordance: CPTAC elevated but RNA-DGE flat"},
        "C": {"signal": "strong", "corroboration": "high",
              "evidence": "malignant_broadly_detected (malignant frac 0.76, n=446 donors)"},
        "D": {"signal": "strong", "corroboration": "moderate", "evidence": "breadth broadly_tumor_elevated"},
        "homogeneity": "homogeneous",
    }
    cards = [
        {"card_id": "cellline-rna-distribution", "summary": {"expression_class": "lineage_restricted",
                                                             "allgene_percentile": 29.6, "allgene_percentile_class": "mid"}},
        {"card_id": "cellline-protein-abundance", "summary": {}, "_missing": True},
        {"card_id": "tumor-rna-distribution", "summary": {"allgene_percentile": 99.9, "allgene_percentile_class": "top_1pct"}},
        {"card_id": "tumor-rna-vs-adjacent", "summary": {"allgene_percentile": 27.7, "allgene_percentile_class": "mid"}},
        {"card_id": "tumor-protein-abundance-cptac", "summary": {"allgene_percentile": 99.7, "allgene_percentile_class": "top_1pct"}},
        {"card_id": "tumor-rna-distribution-by-subtype", "summary": {"subtype_stratification_class": "pan_subtype_uniform",
                                                                     "n_subtypes_measured": 14, "n_subtypes_enriched": 0}},
        {"card_id": "cellline-rna-distribution-by-subtype", "summary": {"subtype_stratification_class": "pan_subtype_uniform"}},
        {"card_id": "normal-tissue-liability", "summary": {"normal_tissue_breadth_class": "broad_normal_expression"}},
        {"card_id": "sc-normal-celltype-expression", "summary": {"sc_normal_expression_class": "HIGH_LIABILITY",
                                                                 "max_detection_cell_type": "BEST4+ colonocyte"}},
        {"card_id": "rna-protein-concordance-tumor", "summary": {"rna_as_biomarker": "partial_proxy",
                                                                 "rna_protein_r": 0.41, "n_paired_tumors": 90}},
        {"card_id": "cellline-rna-protein-concordance", "summary": {"rna_as_biomarker": "adequate_proxy", "rna_protein_r": 0.74}},
        {"card_id": "expression-purity-confound", "summary": {"purity_confound_class": "purity_independent"}},
    ]
    return headline, cards, cv


def _by_id(rows):
    return {r["id"]: r for r in rows}


def test_seven_rows_in_order():
    h, cards, cv = _fixture()
    rows = presence_question_table(h, cards, cv)
    assert [r["id"] for r in rows] == ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7"]


def test_q1_abundance_from_claim_A_with_cellline_support():
    r = _by_id(presence_question_table(*_fixture()))["Q1"]
    assert r["signal"]["tier"] == "strong" and r["signal"]["polarity"] == "supports"
    assert "lineage_restricted" in r["support"]  # cell-line proxy is the supporting read


def test_q3_surfaces_window_caveat_from_normal_cards():
    r = _by_id(presence_question_table(*_fixture()))["Q3"]
    # claim B drives the meter; the supporting line carries the discordance + normal-tissue window caveat
    assert "comparator discordance" in r["support"]
    assert "broad_normal_expression" in r["support"] and "HIGH_LIABILITY" in r["support"]
    assert "⚠ window" in r["signal"]["label"]


def test_q4_uniform_is_neutral_not_a_magnitude():
    r = _by_id(presence_question_table(*_fixture()))["Q4"]
    assert r["signal"]["tier"] == "uniform" and r["signal"]["polarity"] == "neutral"
    assert "uniform" in r["primary"]


def test_q5_level_vs_effect_labeled_and_level_drives_signal():
    r = _by_id(presence_question_table(*_fixture()))["Q5"]
    # LEVEL rank (tumor top-1%) drives the signal; effect ranks (CPTAC) are supporting, labeled distinctly
    assert r["signal"]["tier"] == "strong"
    assert "level:" in r["primary"] and "tumor RNA" in r["primary"]
    assert "effect:" in r["support"] and "CPTAC protein effect" in r["support"]
    assert r["confidence"]["tier"] == "high"


def test_q7_intrinsic_from_claim_C_with_purity_support():
    r = _by_id(presence_question_table(*_fixture()))["Q7"]
    assert r["signal"]["tier"] == "strong"
    assert "purity_independent" in r["support"]


def test_verdict_inert_no_exceptions_on_sparse_headline():
    # a near-empty headline/cards must degrade to unmeasured rows, never raise
    rows = presence_question_table({}, [], {"A": {}, "B": {}, "C": {}, "D": {}})
    assert len(rows) == 7
    assert all(r["signal"]["tier"] == "unmeasured" for r in rows if r["id"] in ("Q1", "Q7"))
