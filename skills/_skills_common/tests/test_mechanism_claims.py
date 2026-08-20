"""Unit tests for mechanism-and-pharmacology's claim vector (skills/_skills_common/mechanism_claims.py),
the ELEVENTH concrete. Pins the NETWORK annotation-density CAP (never strong), PHOSPHO as the real
positive signal, the not_phosphoprotein=absent (measured N/A) discipline, and citable atoms. Pure."""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.mechanism_claims import mechanism_claim_vector, mechanism_key_signals  # noqa: E402


def _cards():
    return [
        {"card_id": "signaling-network-mechanism", "summary": {
            "network_class": "well_characterized", "n_upstream_regulators": 12, "n_downstream_effectors": 30,
            "has_actionable_moa": True, "moa_classes_present": ["kinase", "gtpase"]}},
        {"card_id": "phospho-pathway-activity", "summary": {
            "phospho_activity_class": "phospho_active", "n_phosphosites": 8, "max_site_detection_fraction": 0.72}},
        {"card_id": "pathway-activity-context", "summary": {
            "pathway_activity_class": "relatively_high", "relatively_high_pathways": ["MAPK"]}},
        {"card_id": "tahoe-drug-perturbation", "summary": {
            "tahoe_perturbation_class": "drug_suppressed", "n_perturbing_drugs": 4, "strongest_mover_drug": "trametinib"}},
        {"card_id": "dependency-predictability", "summary": {
            "predictability_class": "own_omics_driven", "pred_dominant_feature_class": "own_mut_hotspot"}},
    ]


def test_network_capped_at_moderate_phospho_is_strong():
    vec = mechanism_claim_vector({}, _cards())
    assert vec["NETWORK"]["signal"] == "moderate"      # well_characterized CAPPED (annotation density)
    assert vec["PHOSPHO"]["signal"] == "strong"        # phospho_active — the real positive signal
    assert vec["PATHWAY"]["signal"] == "moderate"
    assert vec["PERTURBATION"]["signal"] == "moderate"  # engagement (direction in atom)
    assert vec["PREDICTABILITY"]["signal"] == "moderate"


def test_atoms_present_and_citable():
    vec = mechanism_claim_vector({}, _cards())
    net = vec["NETWORK"]["evidence_atom"]
    assert net["values"]["has_actionable_moa"] is True     # MoA hooks folded into NETWORK atom
    assert net["values"]["n_upstream_regulators"] == 12
    assert vec["PHOSPHO"]["evidence_atom"]["values"]["max_site_detection_fraction"] == 0.72
    assert vec["PERTURBATION"]["evidence_atom"]["values"]["strongest_mover_drug"] == "trametinib"


def test_not_phosphoprotein_is_absent_gap_is_unmeasured():
    vec = mechanism_claim_vector({}, [
        {"card_id": "phospho-pathway-activity", "summary": {"phospho_activity_class": "not_phosphoprotein"}},
        {"card_id": "signaling-network-mechanism", "summary": {"network_class": "data_unavailable"}},
    ])
    assert vec["PHOSPHO"]["signal"] == "absent"        # measured biological N/A (e.g. a GTPase)
    assert vec["NETWORK"]["signal"] == "unmeasured"    # gap


def test_atoms_absent_without_cards():
    vec = mechanism_claim_vector({}, [])
    for ax in ("NETWORK", "PHOSPHO", "PATHWAY", "PERTURBATION", "PREDICTABILITY"):
        assert "evidence_atom" not in vec[ax]
