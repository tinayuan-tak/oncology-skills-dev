"""Unit tests for on-target-safety-liability's claim vector (skills/_skills_common/safety_claims.py),
the FIFTH concrete over claim_vector_core. Pins the INVERSE-valence LIABILITY tiers (strong = concern,
tolerant = absent, protective = negative) + the citable atoms + the mutant-selective-GoF conditioning
conflict. Pure over a headline dict + card summaries — no S3."""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]        # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.safety_claims import safety_claim_vector  # noqa: E402


def _headline(**over):
    h = {"constraint_class": "highly_constrained", "pli_score": 0.99, "loeuf_score": 0.21,
         "obs_lof_count": 2, "exp_lof_count": 40.0,
         "burden_safety_class": "lof_risk_phenotype", "burden_min_pvalue": 3e-9, "burden_top_disease": "cardiomyopathy",
         "dosage_sensitivity_class": "autosomal_dominant_loss", "germline_inheritance_mode": "dominant",
         "clinvar_pathogenic_class": "germline_pathogenic", "clinvar_top_disease": "Noonan",
         "mouse_ko_phenotype_class": "lethal_ko", "mouse_ko_top_lethal": "embryonic_lethal",
         "alteration_functional_direction": "loss_of_function"}
    h.update(over)
    return h


def _cards():
    return [
        {"card_id": "gnomad-lof-constraint", "summary": {
            "constraint_class": "highly_constrained", "pli_score": 0.99, "loeuf_score": 0.21,
            "mis_z_score": 3.1, "obs_lof_count": 2, "exp_lof_count": 40.0}},
        {"card_id": "gene-burden-safety", "summary": {
            "burden_safety_class": "lof_risk_phenotype", "min_pvalue": 3e-9, "top_disease": "cardiomyopathy"}},
        {"card_id": "clingen-dosage", "summary": {
            "dosage_sensitivity_class": "autosomal_dominant_loss", "germline_inheritance_mode": "dominant"}},
        {"card_id": "clinvar-pathogenicity-safety", "summary": {
            "clinvar_pathogenic_class": "germline_pathogenic", "top_disease": "Noonan"}},
        {"card_id": "mouse-ko-phenotype", "summary": {
            "ko_phenotype_class": "lethal_ko", "top_lethal_label": "embryonic_lethal"}},
    ]


def test_liability_tiers_strong_when_constrained():
    vec = safety_claim_vector(_headline(), _cards())
    assert vec["CONSTRAINT"]["signal"] == "strong"      # highly_constrained = strong CONCERN
    assert vec["BURDEN"]["signal"] == "strong"          # lof_risk_phenotype
    assert vec["DOSAGE"]["signal"] == "strong"          # autosomal_dominant_loss
    assert vec["CLINVAR"]["signal"] == "strong" and vec["MOUSE_KO"]["signal"] == "strong"


def test_inverse_valence_tolerant_is_absent_protective_is_negative():
    vec = safety_claim_vector(_headline(constraint_class="tolerant", burden_safety_class="protective",
                                        dosage_sensitivity_class="dosage_sufficient",
                                        mouse_ko_phenotype_class="no_phenotype"), _cards())
    assert vec["CONSTRAINT"]["signal"] == "absent"      # MEASURED LoF-tolerant → not a concern
    assert vec["BURDEN"]["signal"] == "negative"        # protective → measured opposite
    assert vec["DOSAGE"]["signal"] == "absent"
    assert vec["MOUSE_KO"]["signal"] == "absent"


def test_gap_is_unmeasured_not_absent():
    vec = safety_claim_vector(_headline(constraint_class="indeterminate"), _cards())
    assert vec["CONSTRAINT"]["signal"] == "unmeasured"  # gap ≠ measured-tolerant


def test_atoms_present_and_citable():
    vec = safety_claim_vector(_headline(), _cards())
    a = vec["CONSTRAINT"]["evidence_atom"]
    assert a["cite"]["card_id"] == "gnomad-lof-constraint"
    assert a["values"]["pli_score"] == 0.99 and a["values"]["loeuf_score"] == 0.21
    assert a["entity"]["valence"] == "liability"
    assert vec["BURDEN"]["evidence_atom"]["values"]["min_pvalue"] == 3e-9


def test_mutant_selective_gof_conditions_constraint_conflict():
    # activating-GoF mechanism → the WT-constraint concern is flagged as DOWNGRADED (a conflict), tier kept
    vec = safety_claim_vector(_headline(alteration_functional_direction="activating"), _cards())
    assert vec["CONSTRAINT"]["signal"] == "strong"      # tier unchanged (this is the SIGNAL)
    assert "DOWNGRADED" in (vec["CONSTRAINT"]["conflict"] or "")


def test_atoms_absent_without_cards():
    vec = safety_claim_vector(_headline(), [])
    for ax in ("CONSTRAINT", "BURDEN", "DOSAGE", "CLINVAR", "MOUSE_KO"):
        assert "evidence_atom" not in vec[ax], f"{ax} atom present with no source card"
