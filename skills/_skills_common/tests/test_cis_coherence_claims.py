"""Unit tests for cis-feature-coherence's claim vector (skills/_skills_common/cis_coherence_claims.py),
the TWELFTH concrete. Pins the 4 leg tiers, the DISTINCTIVE cross-grain patient-agreement corroboration
(bump/cap), the wrong-direction `negative` tiers + conflicts, and the invariant=unmeasured (not absent)
discipline. Pure."""

from __future__ import annotations

from _skills_common.cis_coherence_claims import (  # noqa: E402
    _CELLLINE_ISOFORM_ARM,
    _CELLLINE_SILENCING_ARM,
    _PATIENT_SILENCING_ARM,
    _PATIENT_SPLICE_ARM,
    _PROTEIN_EXPRDEP_ARM,
    _RNA_EXPRDEP_ARM,
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


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# THIRD envelope-v0 concordance family for cis_coherence (SK#1784, epic #1779 A4): expression/abundance→
# dependency concordance. Folds the SAME own-omics→DepMap-Chronos-dependency-coupling property measured by
# two independent ASSAY MODALITIES of the SAME cell-line grain — bulk-RNA (expression-dependency-correlation.
# correlation_class) × MS-protein (abundance-dependency.abundance_dependency_class). Independence is
# MODALITY-only (both share the cell_line_model grain); a same-modality restatement never counts twice.
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
def _rna_dep_card(correlation_class="strong_negative"):
    return {
        "card_id": "expression-dependency-correlation",
        "summary": {
            "correlation_class": correlation_class,
            "pearson_r": -0.61,
            "pearson_p": 1e-8,
            "spearman_r": -0.58,
            "spearman_p": 3e-8,
            "n_cell_lines_evaluated": 42,
            "delta_chronos_top_vs_bottom_quartile": -0.47,
        },
    }


def _protein_dep_card(abundance_dependency_class="protein_predicts_dependency"):
    return {
        "card_id": "abundance-dependency",
        "summary": {
            "abundance_dependency_class": abundance_dependency_class,
            "protein_dependency_pearson_r": -0.55,
            "protein_dependency_pearson_p": 4e-6,
            "protein_dependency_spearman_r": -0.52,
            "n_paired_models": 33,
            "n_dependent_models": 12,
        },
    }


def _exprdep_cards(rna="strong_negative", prot="protein_predicts_dependency"):
    """A minimal card list with ONLY the two expression/abundance→dependency modality cards (the dosage/
    silencing legs are irrelevant to this concordance claim). Either modality card may be omitted (None)."""
    cards = []
    if rna is not None:
        cards.append(_rna_dep_card(rna))
    if prot is not None:
        cards.append(_protein_dep_card(prot))
    return cards


def test_expression_dependency_concordance_cross_modality_claim():
    # THIRD envelope-v0 concordance claim for the cis_coherence domain — SAME-GRAIN CROSS-MODALITY.
    # Both modalities predictive → high corroboration, concordant_coupled.
    both = cis_coherence_claim_vector({}, _exprdep_cards())
    ed = both["expression_dependency_concordance"]
    assert ed["property_id"] == "expression_abundance_dependency_coupling"
    assert ed["integration_method"] == "explicit_deterministic"
    # ★★ #1784 crux: SAME grain, cross-MODALITY (NOT cross-grain).
    assert ed["grain"] == "same_cell_line_grain_cross_modality"
    assert ed["concordance_class"] == "expression_dependency_concordant_coupled"
    assert ed["corroboration"] == "high"
    assert ed["corroborating_independent_arm_count"] == 2 and ed["resolved_source_count"] == 2
    assert "signal" not in ed  # verdict-INERT: never a tier/chip
    # BOTH arms share the cell-line grain; independence is by assay MODALITY (dependence_group).
    _rna = next(s for s in ed["source_support"] if s["source"] == "cell_line_rna")
    _prot = next(s for s in ed["source_support"] if s["source"] == "cell_line_protein")
    assert _rna["grain"] == "cell_line_model" and _prot["grain"] == "cell_line_model"
    assert _rna["dependence_group"] != _prot["dependence_group"]
    # raw correlation metrics DEMOTED not dropped (fidelity/recoverability)
    assert _rna["retained_quantitative"]["pearson_r"] == -0.61
    assert _prot["retained_quantitative"]["protein_dependency_pearson_r"] == -0.55

    # both modalities a MEASURED not-predictive floor → high, concordant_uncoupled.
    unc = cis_coherence_claim_vector({}, _exprdep_cards(rna="no_correlation", prot="no_protein_dependency_link"))
    assert unc["expression_dependency_concordance"]["concordance_class"] == "expression_dependency_concordant_uncoupled"
    assert unc["expression_dependency_concordance"]["corroboration"] == "high"

    # modalities DISAGREE (RNA predictive, protein a measured not-predictive floor) → low, modality_discordant.
    disc = cis_coherence_claim_vector({}, _exprdep_cards(prot="no_protein_dependency_link"))
    assert disc["expression_dependency_concordance"]["concordance_class"] == "expression_dependency_modality_discordant"
    assert disc["expression_dependency_concordance"]["corroboration"] == "low"

    # only the mRNA modality resolves (no protein card) → single_modality_only, single_arm.
    lone = cis_coherence_claim_vector({}, _exprdep_cards(prot=None))
    assert (
        lone["expression_dependency_concordance"]["concordance_class"] == "expression_dependency_single_modality_only"
    )
    assert lone["expression_dependency_concordance"]["corroboration"] == "single_arm"


def test_expression_dependency_positive_anomaly_is_a_measured_refutation_not_a_drop():
    # `positive_anomaly` (measured WRONG direction) is a MEASURED not-predictive arm — with the protein arm
    # predictive, the two modalities DISAGREE (low / modality_discordant), NOT a drop-to-single-arm.
    vec = cis_coherence_claim_vector({}, _exprdep_cards(rna="positive_anomaly", prot="protein_predicts_dependency"))
    ed = vec["expression_dependency_concordance"]
    assert ed["concordance_class"] == "expression_dependency_modality_discordant"
    assert ed["corroboration"] == "low"
    assert ed["concordance_support"]["not_predictive_in"] == "cell_line_rna"


def test_expression_dependency_concordance_key_omitted_when_neither_modality_resolves():
    # mRNA unavailable (→ drop) and NO protein card → BOTH arms gone → key omitted (byte-stable).
    vec = cis_coherence_claim_vector({}, _exprdep_cards(rna="data_unavailable", prot=None))
    assert "expression_dependency_concordance" not in vec
    # a protein modality that ALSO does not resolve (underpowered) keeps the key omitted.
    vec2 = cis_coherence_claim_vector({}, _exprdep_cards(rna="data_unavailable", prot="insufficient_paired_models"))
    assert "expression_dependency_concordance" not in vec2


def test_protein_insufficient_paired_models_drops_it_does_not_disagree():
    # ★★ THE CORRECTNESS CRUX (mirrors the silencing DROP crux). `insufficient_paired_models` (underpowered
    # protein cohort) is MEASURED-but-uninterpretable — it must route to NO rung (DROP), NEVER fabricate a
    # disagreeing arm. With the mRNA arm PREDICTIVE, a wrong `disagree` mapping would drive corroboration to
    # `low` / modality_discordant; the CORRECT DROP leaves only the mRNA arm → single_modality_only / single_arm.
    vec = cis_coherence_claim_vector({}, _exprdep_cards(rna="strong_negative", prot="insufficient_paired_models"))
    ed = vec["expression_dependency_concordance"]
    assert ed["concordance_class"] == "expression_dependency_single_modality_only", (
        "insufficient_paired_models must DROP (no rung), not be read as a disagreeing arm"
    )
    assert ed["corroboration"] == "single_arm"
    assert ed["concordance_support"]["resolved_by"] == "cell_line_rna"


def test_expression_dependency_discordant_protein_never_a_false_agree():
    # A buffered/discordant protein modality (no link) with a predictive mRNA arm must be reported as a
    # DISAGREEMENT (informative — which biomarker assay to prefer), never collapsed into a false agree.
    vec = cis_coherence_claim_vector({}, _exprdep_cards(rna="strong_negative", prot="no_protein_dependency_link"))
    ed = vec["expression_dependency_concordance"]
    assert ed["concordance_class"] == "expression_dependency_modality_discordant"
    assert ed["concordance_support"]["predictive_in"] == "cell_line_rna"
    assert ed["concordance_support"]["not_predictive_in"] == "cell_line_protein"
    assert ed["qualifying_signal"]["source"] == "cell_line_protein"


def test_expression_dependency_concordance_vocab_is_fully_mapped():
    # FAIL-LOUD completeness pin: EVERY declared vocabulary member of each modality is explicitly routed in
    # the class→arm mapping (no token left to an implicit fall-through). A card that grows/renames a token
    # without a matching mapping entry reds here. `data_unavailable` (a TRUTHY sentinel) is mapped explicitly
    # on both modalities, never handled via falsiness.
    expected_rna = {
        "strong_negative",
        "moderate_negative",
        "weak_negative",
        "no_correlation",
        "positive_anomaly",
        "data_unavailable",
    }
    assert set(_RNA_EXPRDEP_ARM) == expected_rna, (
        "mRNA correlation_class vocabulary drifted from the explicit arm mapping — every token must be mapped "
        "to predictive/not_predictive/drop (see expression-dependency-correlation card)"
    )
    expected_protein = {
        "protein_predicts_dependency",
        "weak_protein_dependency_link",
        "no_protein_dependency_link",
        "insufficient_paired_models",
        "data_unavailable",
    }
    assert set(_PROTEIN_EXPRDEP_ARM) == expected_protein, (
        "protein abundance_dependency_class vocabulary drifted from the explicit arm mapping"
    )
    # every value is one of the three defined arm outcomes (no stray/typo outcome)
    assert set(_RNA_EXPRDEP_ARM.values()) | set(_PROTEIN_EXPRDEP_ARM.values()) <= {
        "predictive",
        "not_predictive",
        "drop",
    }


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# FOURTH envelope-v0 concordance family for cis_coherence (SK#1785, epic #1779 B1): isoform-splice
# transcript-FORM concordance. Folds the SAME transcript-FORM-complexity property measured at two DISTINCT
# sample-context GRAINS — cell-line MODEL isoform-dominance (cellline-isoform-expression.
# isoform_expression_class) × patient TUMOUR splice-dysregulation (tumor-splice-dysregulation.
# splicing_dysregulation_class). CROSS-GRAIN independence; the two form vocabularies are related-but-
# distinct, so each token is routed through an explicit class→arm mapping (the `balanced` intermediate +
# `data_unavailable` sentinels DROP).
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
def _isoform_card(isoform_expression_class="isoform_diverse"):
    return {
        "card_id": "cellline-isoform-expression",
        "summary": {
            "isoform_expression_class": isoform_expression_class,
            "dominant_isoform_fraction": 0.41,
            "n_expressed_isoforms": 6,
            "dominant_isoform": "ENST00000256078",
            "n_models": 120,
        },
    }


def _splice_card(splicing_dysregulation_class="tumor_shifted"):
    return {
        "card_id": "tumor-splice-dysregulation",
        "summary": {
            "splicing_dysregulation_class": splicing_dysregulation_class,
            "n_splice_events": 14,
            "max_event_psi_std": 0.28,
            "median_event_psi_std": 0.12,
            "n_variable_events": 5,
            "n_tumor_shifted_events": 4,
            "dominant_event_splice_type": "exon_skip",
            "splicing_context": "PAAD (TCGA SpliceSeq)",
        },
    }


def _isoform_splice_cards(cl="isoform_diverse", pt="tumor_shifted"):
    """A minimal card list with ONLY the two transcript-form grain cards. Either grain may be omitted (None)."""
    cards = []
    if cl is not None:
        cards.append(_isoform_card(cl))
    if pt is not None:
        cards.append(_splice_card(pt))
    return cards


def test_isoform_splice_concordance_cross_grain_claim():
    # FOURTH envelope-v0 concordance claim for the cis_coherence domain — CROSS-GRAIN transcript FORM.
    # Both grains complex → high corroboration, concordant_complex.
    both = cis_coherence_claim_vector({}, _isoform_splice_cards())
    isc = both["isoform_splice_concordance"]
    assert isc["property_id"] == "isoform_splice_form_coupling"
    assert isc["integration_method"] == "explicit_deterministic"
    assert isc["grain"] == "cross_grain_model_vs_patient"
    assert isc["concordance_class"] == "isoform_splice_concordant_complex"
    assert isc["corroboration"] == "high"
    assert isc["corroborating_independent_arm_count"] == 2 and isc["resolved_source_count"] == 2
    assert "signal" not in isc  # verdict-INERT: never a tier/chip
    _cl = next(s for s in isc["source_support"] if s["source"] == "cell_line_model")
    _pt = next(s for s in isc["source_support"] if s["source"] == "patient_tumour")
    assert _cl["grain"] == "cell_line_model" and _pt["grain"] == "patient_tumour"
    # raw transcript-form metrics DEMOTED not dropped (fidelity/recoverability)
    assert _cl["retained_quantitative"]["dominant_isoform_fraction"] == 0.41
    assert _pt["retained_quantitative"]["n_tumor_shifted_events"] == 4

    # both grains a MEASURED simple floor → high, concordant_simple.
    simple = cis_coherence_claim_vector({}, _isoform_splice_cards(cl="single_isoform_dominant", pt="stable"))
    assert simple["isoform_splice_concordance"]["concordance_class"] == "isoform_splice_concordant_simple"
    assert simple["isoform_splice_concordance"]["corroboration"] == "high"

    # highly_variable is ALSO a complex patient arm → concordant_complex with a diverse cell-line arm.
    hv = cis_coherence_claim_vector({}, _isoform_splice_cards(cl="isoform_diverse", pt="highly_variable"))
    assert hv["isoform_splice_concordance"]["concordance_class"] == "isoform_splice_concordant_complex"

    # grains DISAGREE (cell-line diverse=complex, patient stable=simple) → low, grain_discordant.
    disc = cis_coherence_claim_vector({}, _isoform_splice_cards(cl="isoform_diverse", pt="stable"))
    assert disc["isoform_splice_concordance"]["concordance_class"] == "isoform_splice_grain_discordant"
    assert disc["isoform_splice_concordance"]["corroboration"] == "low"
    assert disc["isoform_splice_concordance"]["concordance_support"]["complex_in"] == "cell_line_model"
    assert disc["isoform_splice_concordance"]["concordance_support"]["simple_in"] == "patient_tumour"

    # only the cell-line grain resolves (no patient card) → single_grain_only, single_arm.
    lone = cis_coherence_claim_vector({}, _isoform_splice_cards(pt=None))
    assert lone["isoform_splice_concordance"]["concordance_class"] == "isoform_splice_single_grain_only"
    assert lone["isoform_splice_concordance"]["corroboration"] == "single_arm"
    assert lone["isoform_splice_concordance"]["concordance_support"]["resolved_by"] == "cell_line_model"


def test_isoform_splice_balanced_band_drops_it_does_not_disagree():
    # ★★ THE CORRECTNESS CRUX (mirrors the silencing/exprdep DROP crux). The cell-line `balanced` band
    # (0.50-0.80: a dominant isoform WITH meaningful secondaries) is a MEASURED INTERMEDIATE that resolves
    # NEITHER pole — it must route to NO rung (DROP), NEVER fabricate a disagreeing arm. With the patient arm
    # COMPLEX (tumor_shifted), a wrong `disagree` mapping would drive corroboration to `low` / grain_discordant;
    # the CORRECT DROP leaves only the patient arm → single_grain_only / single_arm.
    vec = cis_coherence_claim_vector({}, _isoform_splice_cards(cl="balanced", pt="tumor_shifted"))
    isc = vec["isoform_splice_concordance"]
    assert isc["concordance_class"] == "isoform_splice_single_grain_only", (
        "the balanced intermediate band must DROP (no rung), not be read as a disagreeing arm"
    )
    assert isc["corroboration"] == "single_arm"
    assert isc["concordance_support"]["resolved_by"] == "patient_tumour"


def test_isoform_splice_concordance_key_omitted_when_neither_grain_resolves():
    # cell-line unavailable (→ drop) and NO patient card → BOTH arms gone → key omitted (byte-stable).
    vec = cis_coherence_claim_vector({}, _isoform_splice_cards(cl="data_unavailable", pt=None))
    assert "isoform_splice_concordance" not in vec
    # a patient grain that ALSO does not resolve (data_unavailable) keeps the key omitted.
    vec2 = cis_coherence_claim_vector({}, _isoform_splice_cards(cl="data_unavailable", pt="data_unavailable"))
    assert "isoform_splice_concordance" not in vec2
    # both DROP-band tokens (balanced + data_unavailable) also omit the key — neither pole resolves.
    vec3 = cis_coherence_claim_vector({}, _isoform_splice_cards(cl="balanced", pt="data_unavailable"))
    assert "isoform_splice_concordance" not in vec3


def test_isoform_splice_discordant_patient_never_a_false_agree():
    # A stable-splicing (simple) patient grain with a diverse (complex) cell-line grain must be reported as a
    # DISAGREEMENT (informative — culture vs tumour-microenvironment; the two readouts measure related-but-
    # distinct form facets), never collapsed into a false agree.
    vec = cis_coherence_claim_vector({}, _isoform_splice_cards(cl="isoform_diverse", pt="stable"))
    isc = vec["isoform_splice_concordance"]
    assert isc["concordance_class"] == "isoform_splice_grain_discordant"
    assert isc["concordance_support"]["complex_in"] == "cell_line_model"
    assert isc["concordance_support"]["simple_in"] == "patient_tumour"
    assert isc["qualifying_signal"]["source"] == "patient_tumour"


def test_isoform_splice_concordance_vocab_is_fully_mapped():
    # FAIL-LOUD completeness pin: EVERY declared vocabulary member of each grain is explicitly routed in the
    # class→arm mapping (no token left to an implicit fall-through). A card that grows/renames a token without
    # a matching mapping entry reds here. `data_unavailable` (a TRUTHY sentinel) is mapped explicitly on both
    # grains, never handled via falsiness.
    expected_cellline = {
        "isoform_diverse",
        "single_isoform_dominant",
        "balanced",
        "data_unavailable",
    }
    assert set(_CELLLINE_ISOFORM_ARM) == expected_cellline, (
        "cell-line isoform_expression_class vocabulary drifted from the explicit arm mapping — every token must "
        "be mapped to form_complex/form_simple/drop (see cellline-isoform-expression card)"
    )
    expected_patient = {
        "tumor_shifted",
        "highly_variable",
        "stable",
        "data_unavailable",
    }
    assert set(_PATIENT_SPLICE_ARM) == expected_patient, (
        "patient splicing_dysregulation_class vocabulary drifted from the explicit arm mapping "
        "(see tumor-splice-dysregulation card)"
    )
    # every value is one of the three defined arm outcomes (no stray/typo outcome)
    assert set(_CELLLINE_ISOFORM_ARM.values()) | set(_PATIENT_SPLICE_ARM.values()) <= {
        "form_complex",
        "form_simple",
        "drop",
    }
