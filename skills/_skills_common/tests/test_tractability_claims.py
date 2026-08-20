"""Unit tests for tractability-small-molecule's claim vector (skills/_skills_common/tractability_claims.py),
the SIXTH concrete over claim_vector_core. Pins the POSITIVE-valence tiers + citable atoms per axis
(POTENCY/ACTIVITY/STRUCT/DRUG/DEGRADER). Pure over card summaries — no S3."""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.tractability_claims import small_molecule_claim_vector  # noqa: E402


def _cards():
    return [
        {"card_id": "measured-potency-tractability", "summary": {
            "measured_bioactivity_class": "potent_measured_ligand", "chembl_best_pchembl": 8.4,
            "chembl_n_potent_ligands": 37, "best_measured_potency_neglog_m": 8.4}},
        {"card_id": "prism-compound-activity", "summary": {
            "prism_activity_class": "clinical_precedent_only", "n_compounds_targeting": 4,
            "highest_clinical_phase": 4.0}},
        {"card_id": "structure-features-static", "summary": {
            "structural_ligandability_class": "experimental_ligandable", "pdb_coverage_class": "strong",
            "alphafold_confidence_class": "high", "alphafold_plddt_mean": 92.1}},
        {"card_id": "known-drug-tractability", "summary": {
            "known_drug_tractability_class": "approved_drug_tractable", "druggability_tier": "Tclin",
            "has_approved_drug": True, "n_antineoplastic_interactions": 12}},
        {"card_id": "degradation-feasibility", "summary": {
            "degradability_feasibility_class": "ubiquitination_substrate", "e3_substrate_evidence": "curated",
            "n_e3_ligases_literature": 3, "degrader_precedent": "none"}},
    ]


def test_positive_valence_tiers():
    vec = small_molecule_claim_vector({}, _cards())
    assert vec["POTENCY"]["signal"] == "strong"        # potent_measured_ligand
    assert vec["ACTIVITY"]["signal"] == "moderate"     # clinical_precedent_only
    assert vec["STRUCT"]["signal"] == "strong"         # experimental_ligandable
    assert vec["DRUG"]["signal"] == "strong"           # approved_drug_tractable
    assert vec["DEGRADER"]["signal"] == "moderate"     # ubiquitination_substrate


def test_atoms_present_and_citable():
    vec = small_molecule_claim_vector({}, _cards())
    pot = vec["POTENCY"]["evidence_atom"]
    assert pot["cite"]["card_id"] == "measured-potency-tractability"
    assert pot["values"]["chembl_best_pchembl"] == 8.4
    assert vec["STRUCT"]["evidence_atom"]["values"]["alphafold_plddt_mean"] == 92.1
    assert vec["DRUG"]["evidence_atom"]["values"]["druggability_tier"] == "Tclin"


def test_disordered_is_negative_and_gaps_unmeasured():
    vec = small_molecule_claim_vector({}, [
        {"card_id": "structure-features-static", "summary": {"structural_ligandability_class": "disordered_low"}},
        {"card_id": "measured-potency-tractability", "summary": {"measured_bioactivity_class": "data_unavailable"}},
    ])
    assert vec["STRUCT"]["signal"] == "negative"       # disordered → measured-against
    assert vec["POTENCY"]["signal"] == "unmeasured"    # gap


def test_atoms_absent_without_cards():
    vec = small_molecule_claim_vector({}, [])
    for ax in ("POTENCY", "ACTIVITY", "STRUCT", "DRUG", "DEGRADER"):
        assert "evidence_atom" not in vec[ax]
