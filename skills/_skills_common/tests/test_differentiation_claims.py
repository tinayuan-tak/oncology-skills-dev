"""Unit tests for differentiation-landscape's claim vector (skills/_skills_common/differentiation_claims.py),
the SEVENTH concrete. Pins the DESCRIPTIVE tiers (direction in atom, not tier) + citable atoms. Pure."""

from __future__ import annotations

from _skills_common.differentiation_claims import differentiation_claim_vector  # noqa: E402


def _cards():
    return [
        {
            "card_id": "co-mutation-and-mutual-exclusivity",
            "summary": {
                "cooccurrence_class": "strong_mutually_exclusive",
                "n_significant_cooccurring": 2,
                "n_significant_mutually_exclusive": 5,
                "top_mutually_exclusive": "BRAF",
                "n_pairs_panel_intersect_eligible": 180,
            },
        },
        {
            "card_id": "expression-clinical-association",
            "summary": {
                "survival_association_class": "expression_high_worse_survival",
                "logrank_p": 0.003,
                "n_patients": 430,
                "n_events": 210,
            },
        },
        {
            "card_id": "precog-prognostic-association",
            "summary": {"prognostic_class": "expression_high_worse_survival", "meta_z": 3.4, "n_precog_datasets": 12},
        },
        {
            "card_id": "pathway-node-leverage",
            "summary": {
                "node_leverage_class": "dominant_node",
                "evidence_scope": "within_indication",
                "paralog_buffering_class": "none",
            },
        },
    ]


def test_descriptive_tiers():
    vec = differentiation_claim_vector({}, _cards())
    assert vec["COMUT"]["signal"] == "strong"  # strong_mutually_exclusive (direction in atom)
    assert vec["SURVIVAL"]["signal"] == "strong"  # high_worse_survival
    assert vec["PROGNOSIS"]["signal"] == "strong"
    assert vec["NODE"]["signal"] == "strong"  # dominant_node


def test_atoms_present_and_citable():
    vec = differentiation_claim_vector({}, _cards())
    assert vec["COMUT"]["evidence_atom"]["values"]["n_significant_mutually_exclusive"] == 5
    assert vec["SURVIVAL"]["evidence_atom"]["cite"]["card_id"] == "expression-clinical-association"
    assert vec["SURVIVAL"]["evidence_atom"]["values"]["logrank_p"] == 0.003
    assert vec["PROGNOSIS"]["evidence_atom"]["values"]["meta_z"] == 3.4


def test_ns_is_absent_gap_is_unmeasured():
    vec = differentiation_claim_vector(
        {},
        [
            {"card_id": "co-mutation-and-mutual-exclusivity", "summary": {"cooccurrence_class": "ns"}},
            {"card_id": "pathway-node-leverage", "summary": {"node_leverage_class": "data_unavailable"}},
        ],
    )
    assert vec["COMUT"]["signal"] == "absent"  # ns = measured no-pattern
    assert vec["NODE"]["signal"] == "unmeasured"  # gap


def test_atoms_absent_without_cards():
    vec = differentiation_claim_vector({}, [])
    for ax in ("COMUT", "SURVIVAL", "PROGNOSIS", "NODE"):
        assert "evidence_atom" not in vec[ax]
