"""Unit tests for target-intrinsic's claim vector (skills/_skills_common/target_intrinsic_claims.py),
the TENTH concrete. Pins the two DESCRIPTIVE axes (MODALITY_ROUTING conviction + TRACTABILITY_PRECEDENT),
the basis-driven corroboration, the Tdark=absent (not adverse) discipline, and citable atoms. Pure."""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.target_intrinsic_claims import (  # noqa: E402
    target_intrinsic_claim_vector,
)


def _cards():
    return [
        {
            "card_id": "domain-modality-relevance",
            "summary": {
                "modality_implication_class": "removal_required_scaffolding",
                "modality_implication_basis": "curated",
                "scaffolding_function": "kinase-independent scaffold",
                "modality_context": "RIPK1 necroptosis scaffold",
            },
        },
        {
            "card_id": "target-development-level",
            "summary": {
                "tdl_class": "Tchem",
                "tdl_meaning": "has a potent small-molecule probe",
                "target_family": "Kinase",
                "novelty_score": 0.31,
            },
        },
    ]


def test_tiers_and_basis_corroboration():
    vec = target_intrinsic_claim_vector({}, _cards())
    assert vec["MODALITY_ROUTING"]["signal"] == "strong"  # removal_required_scaffolding = high conviction
    assert vec["MODALITY_ROUTING"]["corroboration"] == "high"  # basis=curated
    assert vec["TRACTABILITY_PRECEDENT"]["signal"] == "moderate"  # Tchem


def test_atoms_present_and_citable():
    vec = target_intrinsic_claim_vector({}, _cards())
    mod = vec["MODALITY_ROUTING"]["evidence_atom"]
    assert mod["cite"]["card_id"] == "domain-modality-relevance"
    assert mod["values"]["modality_implication_basis"] == "curated"
    tdl = vec["TRACTABILITY_PRECEDENT"]["evidence_atom"]
    assert tdl["values"]["tdl_class"] == "Tchem" and tdl["values"]["target_family"] == "Kinase"


def test_tdark_is_absent_heuristic_is_low_corr():
    vec = target_intrinsic_claim_vector(
        {},
        [
            {
                "card_id": "domain-modality-relevance",
                "summary": {"modality_implication_class": "indeterminate", "modality_implication_basis": "heuristic"},
            },
            {"card_id": "target-development-level", "summary": {"tdl_class": "Tdark"}},
        ],
    )
    assert vec["TRACTABILITY_PRECEDENT"]["signal"] == "absent"  # Tdark = measured no-precedent (not adverse)
    assert vec["MODALITY_ROUTING"]["signal"] == "absent"  # indeterminate = heuristic can't call


def test_gap_is_unmeasured():
    vec = target_intrinsic_claim_vector({}, [])
    assert vec["MODALITY_ROUTING"]["signal"] == "unmeasured"
    assert vec["TRACTABILITY_PRECEDENT"]["signal"] == "unmeasured"
    for ax in ("MODALITY_ROUTING", "TRACTABILITY_PRECEDENT"):
        assert "evidence_atom" not in vec[ax]
