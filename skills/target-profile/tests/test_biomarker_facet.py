"""Q12 biomarker-convergence facet — deterministic assembly (master-sequencing Part 3c).

Verifies the facet pulls corroboration + stratification + preferred_assay from synthetic sub_results,
and the golden cases the plan names: KRAS-like → strong_selection_biomarker (mutant-stratified);
housekeeping-like → none. No S3/LLM (pure dict fixtures)."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run  # noqa: E402


def _sr(**cards_by_short):
    """Build a sub_results dict: short -> {cards:[{card_id, summary}]} from {short: {card_id: summary}}."""
    out = {}
    for short, card_map in cards_by_short.items():
        out[short] = {"cards": [{"card_id": cid, "summary": s} for cid, s in card_map.items()]}
    return out


def test_kras_like_strong_selection_biomarker_genomic():
    # the plan's golden: mutant-stratified dependency → strong_selection_biomarker, preferred genomic
    sr = _sr(
        genomic_alteration={"mutation-stratified-dependency": {"mutation_stratification_class": "mutant_strongly_dependent"},
                            "alteration-role": {"alteration_role": "direct_driver_gof"}},
        expression={"cellline-rna-protein-concordance": {"rna_as_biomarker": "partial_proxy"}},
    )
    f = run._biomarker_facet(sr)
    assert f["verdict"] == "strong_selection_biomarker"
    assert f["preferred_assay"] == "genomic"
    assert f["stratification_role"]["mutation_stratification_class"] == "mutant_strongly_dependent"


def test_predictive_biomarker_alteration_role_is_genomic_stratifier():
    sr = _sr(genomic_alteration={"alteration-role": {"alteration_role": "predictive_biomarker"}})
    f = run._biomarker_facet(sr)
    assert f["verdict"] == "strong_selection_biomarker"
    assert f["preferred_assay"] == "genomic"


def test_dependency_ppv_performance_flows_to_predictive_hypothesis():
    # Thread 3: dependency-classification performance on the mutation-stratified card should (a) surface
    # in the quantitative block and (b) attach to the genomic predictive hypothesis as dependency_performance.
    sr = _sr(genomic_alteration={"mutation-stratified-dependency": {
        "mutation_stratification_class": "mutant_strongly_dependent",
        "hotspot_dependency_ppv": 0.81, "hotspot_dependency_ppv_lift": 9.65,
        "hotspot_dependency_sensitivity": 0.66, "hotspot_dependency_specificity": 0.99,
        "hotspot_dependency_base_rate": 0.084}})
    f = run._biomarker_facet(sr)
    # (a) quantitative re-surfacing
    assert f["quantitative"]["genomic_alteration"]["hotspot_dependency_ppv_lift"] == 9.65
    # (b) attached to the predictive hypothesis
    pred = [h for h in f["biomarker_hypotheses"]
            if h["intended_use"] == "predictive" and "mutation_stratification_class" in h["basis"]]
    assert pred, "expected a mutation-stratified predictive hypothesis"
    perf = pred[0].get("dependency_performance")
    assert perf is not None
    assert perf["dependency_ppv"] == 0.81 and perf["dependency_ppv_lift"] == 9.65
    assert "NOT drug-response" in perf["_metric_scope"]


def test_dependency_performance_absent_when_ppv_not_provided():
    # No PPV fields on the card → predictive hypothesis still forms, but carries no dependency_performance.
    sr = _sr(genomic_alteration={"mutation-stratified-dependency": {
        "mutation_stratification_class": "mutant_moderately_dependent"}})
    f = run._biomarker_facet(sr)
    pred = [h for h in f["biomarker_hypotheses"] if h["intended_use"] == "predictive"]
    assert pred and "dependency_performance" not in pred[0]


def test_rna_adequate_proxy_prefers_rna():
    # no genomic stratifier; RNA is an adequate proxy → preferred RNA, corroborating_only.
    # phospho re-homed 2026-08-05: it now surfaces under the `mechanism` sub-result, not `expression`.
    sr = _sr(
        expression={"cellline-rna-protein-concordance": {"rna_as_biomarker": "adequate_proxy"}},
        mechanism={"phospho-pathway-activity": {"phospho_activity_class": "phospho_active"}},
    )
    f = run._biomarker_facet(sr)
    assert f["preferred_assay"] == "RNA"
    assert f["verdict"] == "corroborating_only"


def test_poor_proxy_prefers_protein():
    sr = _sr(expression={"cellline-rna-protein-concordance": {"rna_as_biomarker": "poor_proxy"}},
             mechanism={"phospho-pathway-activity": {"phospho_activity_class": "phospho_present"}})
    f = run._biomarker_facet(sr)
    assert f["preferred_assay"] == "protein"
    # corroboration present (phospho_present, from the mechanism sub-result) → corroborating_only
    assert f["verdict"] == "corroborating_only"


def test_poor_proxy_no_corroboration_is_inadequate():
    sr = _sr(expression={"cellline-rna-protein-concordance": {"rna_as_biomarker": "poor_proxy"}})
    f = run._biomarker_facet(sr)
    assert f["preferred_assay"] == "protein"
    assert f["verdict"] == "inadequate"


def test_housekeeping_like_none():
    # the plan's other golden: nothing biomarker-relevant → none. All corroboration signals must be
    # in the excluded set (None / data_unavailable / not_informative) and no stratifier present.
    sr = _sr(
        expression={"cellline-rna-protein-concordance": {"rna_as_biomarker": "data_unavailable"},
                    "phospho-pathway-activity": {"phospho_activity_class": "data_unavailable"},
                    "expression-purity-confound": {"purity_confound_class": "data_unavailable"}},
        genomic_alteration={"alteration-role": {"alteration_role": "data_unavailable"},
                            "mutation-stratified-dependency": {"mutation_stratification_class": "data_unavailable"}},
    )
    f = run._biomarker_facet(sr)
    assert f["verdict"] == "none"
    assert f["preferred_assay"] == "neither"


def test_missing_subskills_null_not_fabricated():
    # sub-skills absent → fields recorded null (honest coverage), verdict none, no crash
    f = run._biomarker_facet({})
    assert f["verdict"] == "none"
    assert f["corroboration_role"] == {} and f["stratification_role"] == {}


def test_facet_is_verdict_inert_shape():
    # the facet must NOT carry an overall_recommendation / nominate field (it's not a gate)
    f = run._biomarker_facet(_sr(genomic_alteration={"alteration-role": {"alteration_role": "predictive_biomarker"}}))
    assert "overall_recommendation" not in f and "nominate" not in f
    assert "_disclaimer" in f  # states the facet-not-gate contract


def test_subtype_stratification_class_is_a_stratification_input_not_a_verdict_promoter():
    """subtype_stratification_class (2026-08-04) feeds the facet's stratification_role — it defines a
    patient-selection population (raises confidence) but must NOT promote the facet verdict to
    strong_selection_biomarker (reserved for GENOMIC stratifiers). One-directional."""
    sr = _sr(expression={"tumor-rna-distribution-by-subtype":
                         {"subtype_stratification_class": "subtype_restricted_with_window"}})
    f = run._biomarker_facet(sr)
    # captured in the stratification block (visible patient-selection context)
    assert f["stratification_role"]["subtype_stratification_class"] == "subtype_restricted_with_window"
    # but NOT a genomic stratifier → verdict is NOT strong_selection_biomarker, assay NOT genomic
    assert f["verdict"] != "strong_selection_biomarker"
    assert f["preferred_assay"] != "genomic"


# ── BEST-role classification (§1): typed, NON-exclusive biomarker_hypotheses ──────────────────
def _roles(f):
    return {h["intended_use"] for h in f["biomarker_hypotheses"]}


def test_best_role_predictive_from_mutation_stratified_dependency():
    sr = _sr(genomic_alteration={"mutation-stratified-dependency":
                                 {"mutation_stratification_class": "mutant_strongly_dependent"}})
    f = run._biomarker_facet(sr)
    assert "predictive" in _roles(f)
    h = next(h for h in f["biomarker_hypotheses"] if h["intended_use"] == "predictive")
    assert h["evidence_strength"] == "strong"
    # the CRISPR-not-inhibitor guardrail must be stated in the note
    assert "NOT auto an inhibitor" in h["_note"] or "not auto an inhibitor" in h["_note"].lower()


def test_best_role_prognostic_kept_separate_from_predictive():
    # expression↔survival alone → PROGNOSTIC only, never predictive
    sr = _sr(differentiation={"expression-clinical-association":
                              {"survival_association_class": "expression_high_worse_survival"}})
    f = run._biomarker_facet(sr)
    assert _roles(f) == {"prognostic"}
    assert "prognostic" in _roles(f) and "predictive" not in _roles(f)


def test_best_role_multi_role_target_carries_several_hypotheses():
    # a target that is BOTH mutation-predictive AND driver-subtyping AND prognostic → 3 distinct roles
    sr = _sr(
        genomic_alteration={"mutation-stratified-dependency": {"mutation_stratification_class": "mutant_strongly_dependent"},
                            "alteration-role": {"alteration_role": "direct_driver_lof"}},
        differentiation={"expression-clinical-association": {"survival_association_class": "expression_high_better_survival"}},
    )
    f = run._biomarker_facet(sr)
    assert {"predictive", "diagnostic_subtyping", "prognostic"}.issubset(_roles(f))
    # they are SEPARATE hypotheses (not collapsed) — at least 3 entries
    assert len(f["biomarker_hypotheses"]) >= 3
    assert set(f["intended_uses"]) == _roles(f)


def test_best_role_pharmacodynamic_from_phospho():
    sr = _sr(mechanism={"phospho-pathway-activity": {"phospho_activity_class": "phospho_active"}})
    f = run._biomarker_facet(sr)
    assert _roles(f) == {"pharmacodynamic"}


def test_best_role_weak_predictive_from_correlation_without_genotype():
    # abundance→dependency correlation but NO genotype stratifier → weakest predictive tier
    sr = _sr(dependency={"abundance-dependency": {"abundance_dependency_class": "protein_predicts_dependency"}})
    f = run._biomarker_facet(sr)
    h = [h for h in f["biomarker_hypotheses"] if h["intended_use"] == "predictive"]
    assert h and h[0]["evidence_strength"] == "weak"


def test_best_role_empty_when_nothing_biomarker_relevant():
    # housekeeping-like: no genotype, no survival, no subtype, no phospho → no typed hypotheses
    sr = _sr(expression={"cellline-rna-protein-concordance": {"rna_as_biomarker": "adequate_proxy"}})
    f = run._biomarker_facet(sr)
    assert f["biomarker_hypotheses"] == [] and f["intended_uses"] == []


def test_best_role_data_unavailable_contributes_no_role():
    sr = _sr(differentiation={"expression-clinical-association": {"survival_association_class": "data_unavailable"}},
             genomic_alteration={"mutation-stratified-dependency": {"mutation_stratification_class": "insufficient_mutation_rate"}})
    f = run._biomarker_facet(sr)
    assert f["biomarker_hypotheses"] == []


# --- A2a: quantitative re-surfacing (the raw stats behind each categorical class) ---

def test_quantitative_block_resurfaces_card_statistics():
    """A2a: the facet re-surfaces the numeric companions the cards compute (r, effect size,
    Mann-Whitney q, delta-Chronos, agreement fractions) alongside the categorical classes."""
    sr = _sr(
        genomic_alteration={"mutation-stratified-dependency": {
            "mutation_stratification_class": "mutant_strongly_dependent",
            "hotspot_mannwhitney_q": 0.002, "hotspot_effect_size": 0.61,
            "delta_chronos_hotspot_mut_vs_wt": -0.83}},
        dependency={"expression-dependency-correlation": {
            "correlation_class": "strong_negative", "pearson_r": -0.55,
            "delta_chronos_top_vs_bottom_quartile": -0.7},
            "crispr-rnai-dependency-concordance": {
            "concordance_class": "concordant", "fraction_agree": 0.88}},
    )
    f = run._biomarker_facet(sr)
    q = f["quantitative"]
    assert q["genomic_alteration"]["hotspot_mannwhitney_q"] == 0.002
    assert q["genomic_alteration"]["hotspot_effect_size"] == 0.61
    assert q["dependency"]["pearson_r"] == -0.55
    assert q["dependency"]["fraction_agree"] == 0.88
    # the categorical roles are still present (re-surfacing is ADDITIVE)
    assert f["stratification_role"]["mutation_stratification_class"] == "mutant_strongly_dependent"


def test_quantitative_is_verdict_inert():
    """Adding the numeric companions must NOT change verdict / preferred_assay / intended_uses —
    they ride in a parallel block; the facet's categorical logic is untouched."""
    base_cards = {"mutation-stratified-dependency": {"mutation_stratification_class": "mutant_strongly_dependent"}}
    with_nums = {"mutation-stratified-dependency": {
        "mutation_stratification_class": "mutant_strongly_dependent",
        "hotspot_mannwhitney_q": 0.002, "hotspot_effect_size": 0.61}}
    f_base = run._biomarker_facet(_sr(genomic_alteration=base_cards))
    f_num = run._biomarker_facet(_sr(genomic_alteration=with_nums))
    for k in ("verdict", "preferred_assay", "intended_uses", "corroboration_role", "stratification_role"):
        assert f_base[k] == f_num[k], f"{k} changed when numeric fields were added (not verdict-inert)"


def test_quantitative_omits_absent_fields_honestly():
    """Absent numeric fields are simply omitted (no fabricated 0/null); a sub-skill with no numeric
    companions present contributes no quantitative entry."""
    sr = _sr(genomic_alteration={"mutation-stratified-dependency": {
        "mutation_stratification_class": "mutant_strongly_dependent"}})  # class only, no numbers
    f = run._biomarker_facet(sr)
    # no numeric companions present → genomic_alteration key absent from quantitative (not {}/null-filled)
    assert "genomic_alteration" not in f["quantitative"]
    assert isinstance(f["quantitative"], dict)
