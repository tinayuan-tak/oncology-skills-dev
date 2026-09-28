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
    _CELLLINE_SILENCING_ARM,
    _PATIENT_SILENCING_ARM,
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


def _protein_card(cis_protein_dosage_class="prot_dosage_coupled_strong"):
    return {
        "card_id": "cis-feature-protein-coherence",
        "summary": {
            "cis_protein_dosage_class": cis_protein_dosage_class,
            "cn_prot_spearman_r": 0.61,
            "cn_prot_slope_log2abundance_per_cn": 0.47,
            "delta_log2abundance_amplified_vs_neutral": 1.6,
            "n_paired_models_cn_protein": 210,
        },
    }


def _rna_card_with_slope():
    # the cell-line RNA card carrying a slope so the mRNA-vs-protein slope RATIO is computable.
    cards = _cards()
    cards[0]["summary"]["cn_expr_slope_log2tpm_per_cn"] = 0.62
    return cards


def test_cis_dosage_protein_coupled_arm_corroborates_within_grain():
    # SK#1783 A3 — a COUPLED protein modality is a SECOND SOURCE (rsc 2->3) but NOT a second independent
    # GRAIN: corroborating_independent_arm_count stays grain-based (2), concordance/corroboration byte-stable.
    two_arm = cis_coherence_claim_vector({}, _cards() + [_patient_card("cn_dosage_coupled_strong")])[
        "cis_dosage_concordance"
    ]
    three_arm = cis_coherence_claim_vector(
        {},
        _rna_card_with_slope()
        + [_patient_card("cn_dosage_coupled_strong"), _protein_card("prot_dosage_coupled_strong")],
    )["cis_dosage_concordance"]
    # the grain-frame trio is byte-identical to the two-arm claim (protein does NOT lift independent grains).
    assert three_arm["concordance_class"] == two_arm["concordance_class"] == "cis_dosage_concordant_coupled"
    assert three_arm["corroboration"] == two_arm["corroboration"] == "high"
    assert three_arm["corroborating_independent_arm_count"] == 2  # UNCHANGED — still two independent grains
    assert three_arm["resolved_source_count"] == 3  # but the protein MODALITY grows resolved sources
    assert "signal" not in three_arm  # still verdict-INERT
    prot = next(s for s in three_arm["source_support"] if s["source"] == "cell_line_protein")
    assert prot["dependence_group"] == "cell_line_model" and prot["assay_modality"] == "ms_protein"
    assert prot["independent_replicate"] is False and prot["corroboration_eligible"] is True
    assert prot["dosage_direction"] == "coupled"
    assert three_arm["protein_modality_corroboration"]["status"] == "protein_corroborates"
    # the cell-line dependence GROUP now folds the protein modality (same grain, distinct assay).
    _grp = next(g for g in three_arm["evidence_dependence"]["groups"] if "cell_line_protein" in g["members"])
    assert _grp["relationship"] == "shared_cell_line_grain_distinct_modality"
    # the slope RATIO is surfaced as the buffering fingerprint.
    assert prot["retained_quantitative"]["mrna_vs_protein_dosage_slope_ratio"] == round(0.47 / 0.62, 4)


def test_cis_dosage_protein_buffered_arm_is_qualified_never_a_false_agree():
    # SK#1783 A3 — a strongly BUFFERED protein slope (protein flat while mRNA tracks CN) is a QUALIFIED
    # quantitative view: a MEASURED (resolved) source but NEVER counted as agreement (corroboration_eligible
    # False), so it does not silently inflate agreement. Still grows resolved_source_count.
    three_arm = cis_coherence_claim_vector(
        {}, _rna_card_with_slope() + [_patient_card("cn_dosage_coupled_strong"), _protein_card("prot_dosage_uncoupled")]
    )["cis_dosage_concordance"]
    assert three_arm["corroborating_independent_arm_count"] == 2  # grain frame UNCHANGED
    assert three_arm["resolved_source_count"] == 3
    prot = next(s for s in three_arm["source_support"] if s["source"] == "cell_line_protein")
    assert prot["resolved"] is True  # a measured read — buffering is real biology, not missing data
    assert prot["corroboration_eligible"] is False  # NEVER a false agree
    assert prot["dosage_direction"] == "buffered"
    assert three_arm["protein_modality_corroboration"]["status"] == "protein_buffered_qualified"


def test_cis_dosage_protein_does_not_lift_a_lone_grain_to_two_independent_arms():
    # SK#1783 A3 crux — with ONLY the cell-line grain resolving (no patient), a coupled protein modality
    # must NOT manufacture a second INDEPENDENT grain: independent arm count stays 1, corroboration stays
    # single_arm; the protein only grows resolved_source_count (1 grain + protein modality = 2 sources).
    lone_plus_prot = cis_coherence_claim_vector(
        {}, _rna_card_with_slope() + [_protein_card("prot_dosage_coupled_strong")]
    )["cis_dosage_concordance"]
    assert lone_plus_prot["concordance_class"] == "cis_dosage_single_grain_only"
    assert lone_plus_prot["corroboration"] == "single_arm"
    assert lone_plus_prot["corroborating_independent_arm_count"] == 1  # NOT lifted to 2 by a same-grain modality
    assert lone_plus_prot["resolved_source_count"] == 2


def test_cis_dosage_protein_absent_path_is_byte_stable_to_two_arm_claim():
    # SK#1783 A3 — the protein-ABSENT path (and a data_unavailable/off-roster protein card) is DEEP-EQUAL to
    # the #1781 two-arm claim: the protein arm is purely ADDITIVE, present only when it resolves.
    base = cis_coherence_claim_vector({}, _cards() + [_patient_card("cn_dosage_coupled_strong")])[
        "cis_dosage_concordance"
    ]
    absent = cis_coherence_claim_vector(
        {}, _cards() + [_patient_card("cn_dosage_coupled_strong"), _protein_card("data_unavailable")]
    )["cis_dosage_concordance"]
    assert absent == base
    assert "protein_modality_corroboration" not in base


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


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# SK#1782 — methylation-silencing cross-grain concordance claim (SECOND envelope-v0 cis-domain family)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _patient_silencing_card(patient_methylation_silencing_class="epigenetic_silencing"):
    return {
        "card_id": "patient-cis-coherence",
        "summary": {
            "patient_methylation_silencing_class": patient_methylation_silencing_class,
            "delta_log2tpm_methylated_vs_unmethylated": -1.4,
            "n_methylated": 40,
            "n_unmethylated": 210,
            "mean_log2tpm_methylated": 2.1,
            "mean_log2tpm_unmethylated": 3.6,
            "n_cases_methylation": 250,
            "n_cases_expression": 260,
        },
    }


def _cellline_silencing_card(methylation_silencing_class="silencing_coupled_moderate"):
    return {
        "card_id": "cellline-methylation-expression-coherence",
        "summary": {
            "methylation_silencing_class": methylation_silencing_class,
            "silencing_driver": "subset_hypermethylation",
            "n_hypermethylated": 34,
            "subset_median_delta_log2tpm": -1.8,
            "subset_within_lineage_delta_log2tpm": -1.5,
            "lineage_collapse_ratio": 0.72,
            "subset_mannwhitney_p": 1e-12,
            "methyl_expr_spearman_r": -0.44,
            "broad_quartile_delta_log2tpm": -0.9,
        },
    }


def _silencing_cards(cl="silencing_coupled_moderate", pt="epigenetic_silencing"):
    """A minimal card list with ONLY the two silencing grain cards (the dosage/expr legs are irrelevant to
    the silencing concordance claim)."""
    cards = [_cellline_silencing_card(cl)]
    if pt is not None:
        cards.append(_patient_silencing_card(pt))
    return cards


def test_silencing_leg_is_plain_single_arm_after_migration():
    # SK#1782: the SILENCING leg's corroboration was MIGRATED to plain single-source — the cross-grain
    # patient agreement no longer bumps/caps the leg (it now lives in `methylation_silencing_concordance`).
    # A measured cell-line silencing arm reads `single_arm` REGARDLESS of the headline agreement boolean.
    cards = _cards()
    for hl in (
        {},
        {"patient_silencing_agrees_with_cellline": True},
        {"patient_silencing_agrees_with_cellline": False},
    ):
        assert cis_coherence_claim_vector(hl, cards)["SILENCING"]["corroboration"] == "single_arm"


def test_methylation_silencing_concordance_cross_grain_claim():
    # SECOND envelope-v0 concordance claim for the cis_coherence domain.
    # Both grains silenced → high corroboration, concordant_silenced.
    both = cis_coherence_claim_vector({}, _silencing_cards())
    ms = both["methylation_silencing_concordance"]
    assert ms["property_id"] == "methylation_silencing_coupling"
    assert ms["integration_method"] == "explicit_deterministic"
    assert ms["grain"] == "cross_grain_model_vs_patient"
    assert ms["concordance_class"] == "methylation_silencing_concordant_silenced"
    assert ms["corroboration"] == "high"
    assert ms["corroborating_independent_arm_count"] == 2 and ms["resolved_source_count"] == 2
    assert "signal" not in ms  # verdict-INERT: never a tier/chip
    # raw silencing metrics DEMOTED not dropped
    _cl = next(s for s in ms["source_support"] if s["source"] == "cell_line_model")
    assert _cl["retained_quantitative"]["subset_median_delta_log2tpm"] == -1.8
    _pt = next(s for s in ms["source_support"] if s["source"] == "patient_tumour")
    assert _pt["retained_quantitative"]["delta_log2tpm_methylated_vs_unmethylated"] == -1.4

    # both grains a MEASURED not-silenced floor → high, concordant_unsilenced.
    unsil = cis_coherence_claim_vector({}, _silencing_cards(cl="methylation_uncoupled", pt="no_silencing_signal"))
    assert (
        unsil["methylation_silencing_concordance"]["concordance_class"] == "methylation_silencing_concordant_unsilenced"
    )
    assert unsil["methylation_silencing_concordance"]["corroboration"] == "high"

    # grains DISAGREE (cell-line silenced, patient a measured not-silenced floor) → low, grain_discordant.
    disc = cis_coherence_claim_vector({}, _silencing_cards(pt="no_silencing_signal"))
    assert disc["methylation_silencing_concordance"]["concordance_class"] == "methylation_silencing_grain_discordant"
    assert disc["methylation_silencing_concordance"]["corroboration"] == "low"

    # only the cell-line grain resolves (no patient card) → single_grain_only, single_arm.
    lone = cis_coherence_claim_vector({}, _silencing_cards(pt=None))
    assert lone["methylation_silencing_concordance"]["concordance_class"] == "methylation_silencing_single_grain_only"
    assert lone["methylation_silencing_concordance"]["corroboration"] == "single_arm"


def test_methylation_silencing_concordance_key_omitted_when_neither_grain_resolves():
    # cell-line invariant/untestable (→ drop) and NO patient card → BOTH arms gone → key omitted (byte-stable).
    vec = cis_coherence_claim_vector({}, _silencing_cards(cl="methylation_invariant_panel", pt=None))
    assert "methylation_silencing_concordance" not in vec
    # a patient grain that ALSO does not resolve (insufficient data) keeps the key omitted.
    vec2 = cis_coherence_claim_vector({}, _silencing_cards(cl="data_unavailable", pt="insufficient_methylation_data"))
    assert "methylation_silencing_concordance" not in vec2


def test_silencing_lineage_confounded_drops_it_does_not_disagree():
    # ★★ THE CORRECTNESS CRUX. `silencing_lineage_confounded` is MEASURED but NOT interpretable as cis
    # silencing — it must route to NO rung (DROP), NEVER fabricate a disagreeing arm. With the patient grain
    # SILENCED, a wrong `disagree` mapping would drive corroboration to `low` / grain_discordant; the CORRECT
    # DROP behaviour leaves only the patient arm → single_grain_only / single_arm.
    vec = cis_coherence_claim_vector({}, _silencing_cards(cl="silencing_lineage_confounded", pt="epigenetic_silencing"))
    ms = vec["methylation_silencing_concordance"]
    assert ms["concordance_class"] == "methylation_silencing_single_grain_only", (
        "silencing_lineage_confounded must DROP (no rung), not be read as a disagreeing arm"
    )
    assert ms["corroboration"] == "single_arm"
    assert ms["concordance_support"]["resolved_by"] == "patient_tumour"


def test_patient_insufficient_methylation_data_drops_it_does_not_disagree():
    # ★★ mirror crux on the patient grain: `insufficient_methylation_data` (uncovered cohort) DROPS. With the
    # cell-line grain SILENCED, the CORRECT behaviour is single_grain_only / single_arm — NOT a discordance.
    vec = cis_coherence_claim_vector(
        {}, _silencing_cards(cl="silencing_coupled_strong", pt="insufficient_methylation_data")
    )
    ms = vec["methylation_silencing_concordance"]
    assert ms["concordance_class"] == "methylation_silencing_single_grain_only", (
        "patient insufficient_methylation_data must DROP (no rung), not be read as a disagreeing arm"
    )
    assert ms["corroboration"] == "single_arm"
    assert ms["concordance_support"]["resolved_by"] == "cell_line_model"


def test_silencing_concordance_vocab_is_fully_mapped():
    # FAIL-LOUD completeness pin: EVERY declared vocabulary member of each grain is explicitly routed in the
    # class→arm mapping (no token left to an implicit fall-through). A card that grows/renames a token
    # without a matching mapping entry reds here. `data_unavailable` (a TRUTHY sentinel) is mapped
    # explicitly on both grains, never handled via falsiness.
    expected_cellline = {
        "silencing_coupled_strong",
        "silencing_coupled_moderate",
        "silencing_lineage_confounded",
        "methylation_uncoupled",
        "methylation_invariant_panel",
        "data_unavailable",
    }
    assert set(_CELLLINE_SILENCING_ARM) == expected_cellline, (
        "cell-line methylation_silencing_class vocabulary drifted from the explicit arm mapping — every "
        "token must be mapped to silenced/not_silenced/drop (see cellline-methylation-expression-coherence.card.yaml)"
    )
    expected_patient = {
        "epigenetic_silencing",
        "no_silencing_signal",
        "insufficient_methylation_data",
        "data_unavailable",
    }
    assert set(_PATIENT_SILENCING_ARM) == expected_patient, (
        "patient patient_methylation_silencing_class vocabulary drifted from the explicit arm mapping"
    )
    # every value is one of the three defined arm outcomes (no stray/typo outcome)
    assert set(_CELLLINE_SILENCING_ARM.values()) | set(_PATIENT_SILENCING_ARM.values()) <= {
        "silenced",
        "not_silenced",
        "drop",
    }
