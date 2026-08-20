"""Unit tests for surface-modality-fit's claim vector (skills/_skills_common/surface_claims.py),
the EIGHTH concrete. Pins the UNIFORM-valence tiers (strong = better surface substrate; SAFETY/SHED
liabilities as `negative`) + citable atoms. Pure."""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.surface_claims import surface_claim_vector, surface_key_signals  # noqa: E402


def _cards():
    return [
        {"card_id": "adc-tce-modality-fit", "summary": {
            "fit_class": "ADC_preferred", "fit_rationale": "large ECD + internalizing",
            "endocytosis_confidence": "high", "surface_family_class": "cd_molecule",
            "is_adc_topology_favorable": True, "is_tce_topology_favorable": True}},
        {"card_id": "surface-topology-and-ptm", "summary": {
            "topology_class": "single_pass_type_1", "ecd_engineerability_class": "large_ecd",
            "tm_pass_count": 1, "extracellular_residue_count": 620, "ecd_orientation": "type_1"}},
        {"card_id": "surface-abundance-density", "summary": {
            "surface_density_class": "high", "density_evidence_level": "measured",
            "estimated_copies_per_cell_median": 210000, "hpa_ihc_intensity_class": "high",
            "is_tce_viable": True, "is_adc_high_payload_viable": True}},
        {"card_id": "normal-tissue-liability", "summary": {
            "normal_tissue_breadth_class": "restricted_normal_expression",
            "essential_tissue_flag": False, "n_specific_tissues": 2}},
        {"card_id": "shed-ectodomain-liability", "summary": {
            "shed_liability_class": "not_shed_membrane_retained", "shed_evidence_tier": "annotation"}},
    ]


def test_uniform_valence_tiers():
    vec = surface_claim_vector({}, _cards())
    assert vec["FIT"]["signal"] == "strong"          # ADC_preferred
    assert vec["TOPOLOGY"]["signal"] == "strong"     # large_ecd
    assert vec["DENSITY"]["signal"] == "strong"      # high
    assert vec["SAFETY"]["signal"] == "moderate"     # restricted_normal_expression (clean-ish window)
    assert vec["SHED"]["signal"] == "strong"         # membrane-retained


def test_atoms_present_and_citable():
    vec = surface_claim_vector({}, _cards())
    assert vec["FIT"]["evidence_atom"]["cite"]["card_id"] == "adc-tce-modality-fit"
    assert vec["FIT"]["evidence_atom"]["values"]["fit_class"] == "ADC_preferred"
    assert vec["DENSITY"]["evidence_atom"]["values"]["estimated_copies_per_cell_median"] == 210000
    assert vec["TOPOLOGY"]["evidence_atom"]["values"]["extracellular_residue_count"] == 620


def test_liabilities_are_negative_not_absent():
    """A MEASURED adverse read is a real liability (`negative`), distinct from a measured no-substrate
    (`absent`) and from a data gap (`unmeasured`)."""
    vec = surface_claim_vector({}, [
        {"card_id": "normal-tissue-liability", "summary": {"normal_tissue_breadth_class": "broad_normal_expression"}},
        {"card_id": "shed-ectodomain-liability", "summary": {"shed_liability_class": "clinically_shed", "serum_marker": "CA125"}},
        {"card_id": "adc-tce-modality-fit", "summary": {"fit_class": "neither_viable"}},
        {"card_id": "surface-abundance-density", "summary": {"surface_density_class": "unmeasured"}},
    ])
    assert vec["SAFETY"]["signal"] == "negative"     # broad normal = MEASURED liability
    assert vec["SHED"]["signal"] == "negative"       # clinically shed = MEASURED liability
    assert vec["FIT"]["signal"] == "absent"          # neither_viable = measured no-substrate
    assert vec["DENSITY"]["signal"] == "unmeasured"  # gap


def test_key_signals_flag_liability_caveats():
    ks = surface_key_signals({}, [
        {"card_id": "normal-tissue-liability", "summary": {"normal_tissue_breadth_class": "broad_normal_expression"}},
        {"card_id": "shed-ectodomain-liability", "summary": {"shed_liability_class": "clinically_shed"}},
    ])
    assert "liability" in (ks.get("caveat") or "").lower()


def test_atoms_absent_without_cards():
    vec = surface_claim_vector({}, [])
    for ax in ("FIT", "TOPOLOGY", "DENSITY", "SAFETY", "SHED"):
        assert "evidence_atom" not in vec[ax]
