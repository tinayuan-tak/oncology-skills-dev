"""Unit tests for cis-feature-coherence's claim vector (skills/_skills_common/cis_coherence_claims.py),
the TWELFTH concrete. Pins the 4 leg tiers, the DISTINCTIVE cross-grain patient-agreement corroboration
(bump/cap), the wrong-direction `negative` tiers + conflicts, and the invariant=unmeasured (not absent)
discipline. Pure."""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.cis_coherence_claims import (  # noqa: E402
    cis_coherence_claim_vector)


def _cards():
    return [
        {"card_id": "cis-feature-expression-coherence", "summary": {
            "cis_dosage_class": "cn_dosage_coupled_strong", "cn_expr_spearman_r": 0.78,
            "cn_expr_spearman_p": 1e-9, "delta_log2tpm_amplified_vs_neutral": 2.1, "n_amplified": 24,
            "evidence_scope": "within_indication"}},
        {"card_id": "cellline-methylation-expression-coherence", "summary": {
            "methylation_silencing_class": "silencing_coupled_moderate", "silencing_driver": "promoter_hypermeth",
            "n_hypermethylated": 15}},
        {"card_id": "expression-dependency-correlation", "summary": {
            "correlation_class": "strong_negative", "pearson_r": -0.61, "n_cell_lines_evaluated": 40}},
        {"card_id": "amp-expr-stratified-dependency", "summary": {
            "amp_expr_stratification_class": "amplified_overexpressed_strongly_dependent",
            "delta_chronos_amp_expr_vs_rest": -0.5}},
    ]


def test_leg_tiers():
    vec = cis_coherence_claim_vector({}, _cards())
    assert vec["CIS_DOSAGE"]["signal"] == "strong"
    assert vec["SILENCING"]["signal"] == "moderate"
    assert vec["EXPR_DEP"]["signal"] == "strong"
    assert vec["CONJOINT"]["signal"] == "strong"


def test_patient_agreement_corroboration_bump_and_cap():
    cards = _cards()
    # patient arm AGREES → CIS_DOSAGE corroboration bumps to high
    hi = cis_coherence_claim_vector({"patient_dosage_agrees_with_cellline": True}, cards)
    assert hi["CIS_DOSAGE"]["corroboration"] == "high"
    # patient arm DISAGREES → capped low
    lo = cis_coherence_claim_vector({"patient_dosage_agrees_with_cellline": False}, cards)
    assert lo["CIS_DOSAGE"]["corroboration"] == "low"
    # no patient arm → stays moderate (never manufactured from a gap)
    mid = cis_coherence_claim_vector({}, cards)
    assert mid["CIS_DOSAGE"]["corroboration"] == "moderate"


def test_wrong_direction_is_negative_with_conflict():
    cards = _cards()
    cards[2]["summary"]["correlation_class"] = "positive_anomaly"
    cards[3]["summary"]["amp_expr_stratification_class"] = "amp_expr_negative_more_dependent"
    vec = cis_coherence_claim_vector({}, cards)
    assert vec["EXPR_DEP"]["signal"] == "negative" and "wrong direction" in vec["EXPR_DEP"]["conflict"]
    assert vec["CONJOINT"]["signal"] == "negative" and vec["CONJOINT"]["conflict"]


def test_invariant_is_unmeasured_not_absent():
    vec = cis_coherence_claim_vector({}, [
        {"card_id": "cis-feature-expression-coherence", "summary": {"cis_dosage_class": "cn_invariant_panel"}},
        {"card_id": "expression-dependency-correlation", "summary": {"correlation_class": "no_correlation"}},
    ])
    assert vec["CIS_DOSAGE"]["signal"] == "unmeasured"   # untestable panel → resolver abstains (not absent)
    assert vec["EXPR_DEP"]["signal"] == "absent"          # measured no-correlation


def test_atoms_present_and_absent():
    vec = cis_coherence_claim_vector({}, _cards())
    assert vec["CIS_DOSAGE"]["evidence_atom"]["values"]["cn_expr_spearman_r"] == 0.78
    assert vec["CIS_DOSAGE"]["evidence_atom"]["entity"]["grain"] == "target_indication"
    empty = cis_coherence_claim_vector({}, [])
    for ax in ("CIS_DOSAGE", "SILENCING", "EXPR_DEP", "CONJOINT"):
        assert "evidence_atom" not in empty[ax]
