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
    cis_coherence_claim_vector,
)


def _cards():
    return [
        {
            "card_id": "cis-feature-expression-coherence",
            "summary": {
                "cis_dosage_class": "cn_dosage_coupled_strong",
                "cn_expr_spearman_r": 0.78,
                "cn_expr_spearman_p": 1e-9,
                "delta_log2tpm_amplified_vs_neutral": 2.1,
                "n_amplified": 24,
                "evidence_scope": "within_indication",
            },
        },
        {
            "card_id": "cellline-methylation-expression-coherence",
            "summary": {
                "methylation_silencing_class": "silencing_coupled_moderate",
                "silencing_driver": "promoter_hypermeth",
                "n_hypermethylated": 15,
            },
        },
        {
            "card_id": "expression-dependency-correlation",
            "summary": {"correlation_class": "strong_negative", "pearson_r": -0.61, "n_cell_lines_evaluated": 40},
        },
        {
            "card_id": "amp-expr-stratified-dependency",
            "summary": {
                "amp_expr_stratification_class": "amplified_overexpressed_strongly_dependent",
                "delta_chronos_amp_expr_vs_rest": -0.5,
            },
        },
    ]


def test_leg_tiers():
    vec = cis_coherence_claim_vector({}, _cards())
    assert vec["CIS_DOSAGE"]["signal"] == "strong"
    assert vec["SILENCING"]["signal"] == "moderate"
    assert vec["EXPR_DEP"]["signal"] == "strong"
    assert vec["CONJOINT"]["signal"] == "strong"


def _patient_card(patient_cis_dosage_class="cn_dosage_coupled_moderate"):
    return {
        "card_id": "patient-cis-coherence",
        "summary": {
            "patient_cis_dosage_class": patient_cis_dosage_class,
            "cn_expr_spearman_r": 0.55,
            "cn_expr_spearman_p": 1e-6,
            "delta_log2tpm_amplified_vs_neutral": 1.4,
            "n_amplified": 60,
            "n_cases_expression": 310,
        },
    }


def test_cis_dosage_leg_is_plain_single_arm_after_migration():
    # SK#1781: CIS_DOSAGE's LEG corroboration was MIGRATED to plain single-source — the cross-grain
    # patient agreement no longer bumps/caps the leg (it now lives in the `cis_dosage_concordance` claim).
    # A measured cell-line arm reads `single_arm` REGARDLESS of the (now-irrelevant-to-the-leg) headline.
    cards = _cards()
    for hl in ({}, {"patient_dosage_agrees_with_cellline": True}, {"patient_dosage_agrees_with_cellline": False}):
        assert cis_coherence_claim_vector(hl, cards)["CIS_DOSAGE"]["corroboration"] == "single_arm"


def test_cis_dosage_concordance_cross_grain_claim():
    # FIRST envelope-v0 concordance claim for the cis_coherence domain (0 → 1).
    # Both grains coupled → high corroboration, concordant_coupled.
    both = cis_coherence_claim_vector({}, _cards() + [_patient_card("cn_dosage_coupled_strong")])
    cd = both["cis_dosage_concordance"]
    assert cd["property_id"] == "cis_dosage_coupling"
    assert cd["integration_method"] == "explicit_deterministic"
    assert cd["concordance_class"] == "cis_dosage_concordant_coupled"
    assert cd["corroboration"] == "high"
    assert cd["corroborating_independent_arm_count"] == 2 and cd["resolved_source_count"] == 2
    assert "signal" not in cd  # verdict-INERT: never a tier/chip
    # raw dosage metrics DEMOTED not dropped
    _cl = next(s for s in cd["source_support"] if s["source"] == "cell_line_model")
    assert _cl["retained_quantitative"]["cn_expr_spearman_r"] == 0.78

    # grains DISAGREE (cell-line coupled, patient uncoupled) → low, discordant.
    disc = cis_coherence_claim_vector({}, _cards() + [_patient_card("cn_dosage_uncoupled")])
    assert disc["cis_dosage_concordance"]["concordance_class"] == "cis_dosage_grain_discordant"
    assert disc["cis_dosage_concordance"]["corroboration"] == "low"

    # only the cell-line grain resolves (no patient card) → single_grain_only, single_arm.
    lone = cis_coherence_claim_vector({}, _cards())
    assert lone["cis_dosage_concordance"]["concordance_class"] == "cis_dosage_single_grain_only"
    assert lone["cis_dosage_concordance"]["corroboration"] == "single_arm"


def test_cis_dosage_concordance_key_omitted_when_neither_grain_resolves():
    # cell-line invariant/untestable (→ None) and NO patient card → BOTH arms gone → key omitted (byte-stable).
    vec = cis_coherence_claim_vector(
        {},
        [{"card_id": "cis-feature-expression-coherence", "summary": {"cis_dosage_class": "cn_invariant_panel"}}],
    )
    assert "cis_dosage_concordance" not in vec
    # a patient grain that ALSO does not resolve keeps the key omitted.
    vec2 = cis_coherence_claim_vector(
        {},
        [
            {"card_id": "cis-feature-expression-coherence", "summary": {"cis_dosage_class": "data_unavailable"}},
            _patient_card("data_unavailable"),
        ],
    )
    assert "cis_dosage_concordance" not in vec2


def test_wrong_direction_is_negative_with_conflict():
    cards = _cards()
    cards[2]["summary"]["correlation_class"] = "positive_anomaly"
    cards[3]["summary"]["amp_expr_stratification_class"] = "amp_expr_negative_more_dependent"
    vec = cis_coherence_claim_vector({}, cards)
    assert vec["EXPR_DEP"]["signal"] == "negative" and "wrong direction" in vec["EXPR_DEP"]["conflict"]
    assert vec["CONJOINT"]["signal"] == "negative" and vec["CONJOINT"]["conflict"]


def test_invariant_is_unmeasured_not_absent():
    vec = cis_coherence_claim_vector(
        {},
        [
            {"card_id": "cis-feature-expression-coherence", "summary": {"cis_dosage_class": "cn_invariant_panel"}},
            {"card_id": "expression-dependency-correlation", "summary": {"correlation_class": "no_correlation"}},
        ],
    )
    assert vec["CIS_DOSAGE"]["signal"] == "unmeasured"  # untestable panel → resolver abstains (not absent)
    assert vec["EXPR_DEP"]["signal"] == "absent"  # measured no-correlation


def test_atoms_present_and_absent():
    vec = cis_coherence_claim_vector({}, _cards())
    assert vec["CIS_DOSAGE"]["evidence_atom"]["values"]["cn_expr_spearman_r"] == 0.78
    assert vec["CIS_DOSAGE"]["evidence_atom"]["entity"]["grain"] == "target_indication"
    empty = cis_coherence_claim_vector({}, [])
    for ax in ("CIS_DOSAGE", "SILENCING", "EXPR_DEP", "CONJOINT"):
        assert "evidence_atom" not in empty[ax]
