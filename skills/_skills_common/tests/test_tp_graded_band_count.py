"""Tranche 3b/4 — graded_band + count_of_total rulers on the remaining tumor-presence cards.

  - tumor_vs_adjacent_expression : graded_band on log2FC (modest 0.5 / strong 1.5) — the primary frame
  - rna_protein_concordance      : graded_band on r (moderate 0.4 / strong 0.7)
  - tumor_elevation_breadth      : count_of_total (n elevated of n tested, breadth cut)
  - expression_purity_confound   : distance_to_cut on purity↔expression r (intrinsic cut)
  - tumor_protein_ihc_presence   : distance_to_cut on moderate/strong IHC fraction (moderate cut)
Verdict-INERT / display-only.
"""

from _skills_common.display_gloss import gauge_string  # noqa: E402
from _skills_common.evidence_salience import SALIENCE_SPECS, build_interpretation  # noqa: E402


def _primary(mt):
    rf = SALIENCE_SPECS[mt].get("reference_frame")
    return rf[0] if isinstance(rf, list) and rf else rf


def test_graded_band_specs_carry_two_ordered_cuts():
    for mt in ("tumor_vs_adjacent_expression", "rna_protein_concordance"):
        rf = _primary(mt)
        assert rf["kind"] == "graded_band", f"{mt}: primary frame should be graded_band"
        assert len(rf["cuts"]) == 2, f"{mt}: graded_band needs the modest+strong ladder"


def test_graded_band_names_the_strongest_cut_cleared():
    spec = SALIENCE_SPECS["tumor_vs_adjacent_expression"]
    strong = build_interpretation({}, {"log2_fc": 2.1, "expression_call_class": "strongly_elevated"}, spec, None)[0]
    assert "past the 1.5 strong cut" in gauge_string(strong)
    modest = build_interpretation({}, {"log2_fc": 0.8, "expression_call_class": "elevated"}, spec, None)[0]
    assert "past the 0.5 modest cut" in gauge_string(modest)
    flat = build_interpretation({}, {"log2_fc": 0.2, "expression_call_class": "not_informative"}, spec, None)[0]
    assert "short of the 0.5 modest cut" in gauge_string(flat)


def test_count_of_total_reads_count_over_total_past_cut():
    spec = SALIENCE_SPECS["tumor_elevation_breadth"]
    gv = build_interpretation(
        {},
        {"n_cohorts_elevated": 4, "n_cohorts_tested": 6, "tumor_elevation_breadth_class": "broadly_elevated"},
        spec,
        None,
    )
    cot = next(g for g in gv if g["frame"]["kind"] == "count_of_total")  # + a fleet cohort ruler
    assert cot["value"] == 4
    roles = {a["role"]: a["value"] for a in cot["frame"]["anchors"]}
    assert roles.get("total") == 6 and roles.get("cut") == 3
    assert "4 of 6 cohorts" in gauge_string(cot) and "past the 3 cut" in gauge_string(cot)


def test_new_distance_to_cut_cards_gauge_and_read_position():
    p = build_interpretation(
        {},
        {"expression_purity_pearson_r": 0.55, "purity_confound_class": "tumor_intrinsic"},
        SALIENCE_SPECS["expression_purity_confound"],
        None,
    )[0]
    assert p["position"] == "tumor_intrinsic" and p["metric"] == "expression_purity_pearson_r"
    i = build_interpretation(
        {},
        {"fraction_moderate_strong": 0.8, "protein_presence_class": "broadly_detected"},
        SALIENCE_SPECS["tumor_protein_ihc_presence"],
        None,
    )[0]
    assert i["position"] == "broadly_detected" and i["scale"]


def test_subtype_epsilon_graded_band_fires_only_on_the_by_subtype_card():
    spec = SALIENCE_SPECS["tumor_expression_distribution"]
    # by-subtype summary carries the ε² field → the graded_band fires
    sub = build_interpretation(
        {},
        {"subtype_variance_explained": 0.18, "subtype_effect_size_class": "large_subtype_effect"},
        spec,
        "tumor-rna-distribution-by-subtype",
    )
    eps = [g for g in sub if g["metric"] == "subtype_variance_explained"]
    assert len(eps) == 1 and eps[0]["frame"]["kind"] == "graded_band"
    assert "past the 0.14 large cut" in gauge_string(eps[0])
    # main-card summary lacks subtype_variance_explained → the ε² frame drops (byte-stable on the main card)
    main = build_interpretation(
        {}, {"median_log2tpm": 6.1, "tumor_expression_class": "broadly_high"}, spec, "tumor-rna-distribution"
    )
    assert not any(g["metric"] == "subtype_variance_explained" for g in main)


def test_no_value_yields_no_bare_frame_for_new_kinds():
    for mt in ("tumor_elevation_breadth", "expression_purity_confound", "tumor_protein_ihc_presence"):
        assert build_interpretation({}, {}, SALIENCE_SPECS[mt], None) == [], f"{mt}: emitted a bare frame"
