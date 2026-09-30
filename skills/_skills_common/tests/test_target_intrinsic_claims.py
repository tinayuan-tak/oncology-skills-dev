"""Unit tests for target-intrinsic's claim vector (skills/_skills_common/target_intrinsic_claims.py),
the TENTH concrete. Pins the two DESCRIPTIVE axes (MODALITY_ROUTING conviction + TRACTABILITY_PRECEDENT),
the basis-driven corroboration, the Tdark=absent (not adverse) discipline, and citable atoms. Pure."""

from __future__ import annotations

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
    # `single_arm`, not `high`. The old value came from `_MODALITY_BASIS_CORR`, which mapped
    # `modality_implication_basis` — HOW the routing call was made — onto the corroboration axis:
    # curated → `high`, heuristic → `low`. Provenance quality is not arm count. A curated annotation is one
    # careful source, not two agreeing ones, and (the sharper half) a heuristic call reading `low` put a
    # merely WEAKLY-SOURCED claim on the same rung the eval ledger reserves for arms that CONTRADICT each
    # other. Both rows of that map were wrong, in opposite directions, so the map is retired rather than
    # rebanded. See test_tdark_is_absent_heuristic_is_low_corr below for the heuristic side.
    assert vec["MODALITY_ROUTING"]["corroboration"] == "single_arm"
    assert vec["TRACTABILITY_PRECEDENT"]["signal"] == "moderate"  # Tchem


def test_atoms_present_and_citable():
    vec = target_intrinsic_claim_vector({}, _cards())
    mod = vec["MODALITY_ROUTING"]["evidence_atom"]
    assert mod["cite"]["card_id"] == "domain-modality-relevance"
    assert mod["values"]["modality_implication_basis"] == "curated"
    tdl = vec["TRACTABILITY_PRECEDENT"]["evidence_atom"]
    assert tdl["values"]["tdl_class"] == "Tchem" and tdl["values"]["target_family"] == "Kinase"


def test_tdark_is_absent_and_a_heuristic_basis_is_still_one_arm():
    """Renamed from `test_tdark_is_absent_heuristic_is_low_corr`: the `low_corr` half of the old name had
    already stopped being asserted, so the name documented a behaviour nothing here checked. It is now
    asserted — and to the corrected value. A `heuristic` basis is a weakly-sourced SINGLE arm; `low` would
    put it on the rung the ledger reads as arms contradicting one another, when only one arm ever spoke."""
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
    # The rung the old name promised. Same value as the `curated` case in
    # test_tiers_and_basis_corroboration — deliberately: basis quality is not arm count, so curated and
    # heuristic are both one arm and the two cases must NOT be separable on this axis. What distinguishes
    # them is `modality_implication_basis`, which the evidence atom carries verbatim for anyone who needs it.
    assert vec["MODALITY_ROUTING"]["corroboration"] == "single_arm"


def test_gap_is_unmeasured():
    vec = target_intrinsic_claim_vector({}, [])
    assert vec["MODALITY_ROUTING"]["signal"] == "unmeasured"
    assert vec["TRACTABILITY_PRECEDENT"]["signal"] == "unmeasured"
    for ax in ("MODALITY_ROUTING", "TRACTABILITY_PRECEDENT"):
        assert "evidence_atom" not in vec[ax]
