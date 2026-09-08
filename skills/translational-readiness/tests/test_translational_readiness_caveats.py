"""Hermetic tests for the v1.5.0 preclinical-readiness confidence surface (no pixi env / no live data).

Covers the VERDICT-INERT caveats added in the literature-and-claims arc (14th/FINAL skill):
  - translational_readiness_confidence_caveat  (3 tiers + false-demote guard + thin→None)
  - model_fidelity_caveat            (availability/genotype-match ≠ fidelity/dependence; thin→None)
  - coverage_generalization_caveat   (public-only + status:partial; fires on any real run; empty→None)
  - translational_readiness_provenance (quorum fields; empty→None)

Built by calling the run.py caveat helpers directly with synthetic headline dicts, so no data /
resolver / narrator is touched. Asserts the calibration behaviour the DETERMINISTIC panel showed live
(ERBB2/BRCA guard / KRAS/COADREAD organoid-concordance guard / KRAS/PAAD fidelity-unconfirmed /
MET/NSCLC PDX-attribution-confounded / BAP1/UVM honest-thin).
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

SKILL_DIR = Path(__file__).resolve().parent.parent

tr = load_run_py(SKILL_DIR, "tr_run_caveats")


# ── synthetic headline builders (only the fields the caveats read) ──────────────────────────────────
def _hl(
    model="deep_model_coverage",
    n_models=69,
    geno="matched_sparse",
    n_alt=4,
    pdx="pdx_objective_responders",
    pdx_frac=0.10,
    pdx_treat="drugX",
    org_class="broad_organoid_dependency",
    org_lineage="Breast",
    org_lineage_class="broad_organoid_dependency",
    org_n=25,
    org_small=False,
):
    return {
        "model_availability_class": model,
        "n_patient_derived_models": n_models,
        "genotype_matched_class": geno,
        "n_models_with_alteration": n_alt,
        "pdx_drug_response_class": pdx,
        "pdx_responder_fraction": pdx_frac,
        "pdx_most_active_treatment": pdx_treat,
        "organoid_dependency_class": org_class,
        "organoid_lineage": org_lineage,
        "organoid_lineage_class": org_lineage_class,
        "organoid_lineage_n_screened": org_n,
        "organoid_lineage_small_cohort": org_small,
    }


# ── TIER (iii) MILDER — validated-preclinical-model guard (ERBB2/BRCA: fires even with small-cohort + combo) ─
def test_validated_guard_spares_erbb2_brca_despite_small_cohort_and_combo():
    # ERBB2/BRCA live: small-cohort Breast organoid (n=16) + PDX combination (LJM716 + trastuzumab).
    # The guard fires FIRST → it must NOT be demoted to the sharp small-cohort/attribution tier.
    hl = _hl(
        pdx_treat="LJM716 + trastuzumab",
        pdx_frac=0.0971,
        org_lineage_class="broad_organoid_dependency",
        org_n=16,
        org_small=True,
    )
    c = tr._translational_readiness_confidence_caveat(hl, target="ERBB2", indication="BRCA")
    assert c["reason"] == "validated_preclinical_model"
    assert c["tier"] == "milder" and c["false_demote_guarded"] is True
    assert "22019887" in c["detail"] or "29224780" in c["detail"]  # DeRose 2011 / Sachs 2018


# ── TIER (iii) — indication normalisation (leaf → composite: LUAD→NSCLC, COAD/READ→COADREAD) ───────────
def test_validated_guard_normalises_leaf_to_composite():
    hl = _hl(
        pdx="data_unavailable",
        pdx_frac=None,
        pdx_treat=None,
        org_lineage="Bowel",
        org_lineage_class="pan_organoid_essential",
        org_n=22,
    )
    for ind in ("COADREAD", "COAD", "READ"):
        c = tr._translational_readiness_confidence_caveat(hl, target="KRAS", indication=ind)
        assert c["reason"] == "validated_preclinical_model", ind
    for ind in ("NSCLC", "LUAD", "LUSC"):
        c = tr._translational_readiness_confidence_caveat(hl, target="EGFR", indication=ind)
        assert c["reason"] == "validated_preclinical_model", ind


# ── TIER (ii) SHARP — PDX attribution confound (MET/NSCLC: combination INC280 + trastuzumab) ────────────
def test_pdx_combination_fires_attribution_confounded():
    hl = _hl(
        model="moderate_model_coverage",
        n_models=27,
        geno="none",
        n_alt=0,
        pdx="pdx_objective_responders",
        pdx_frac=0.0877,
        pdx_treat="INC280 + trastuzumab",
        org_class="not_organoid_dependent",
        org_lineage=None,
        org_lineage_class=None,
        org_n=None,
    )
    c = tr._translational_readiness_confidence_caveat(hl, target="MET", indication="NSCLC")
    assert c["reason"] == "small_cohort_or_attribution_confounded"
    assert c["tier"] == "sharp" and c["false_demote_guarded"] is False
    assert "COMBINATION" in c["detail"] and "31511426" in c["detail"]  # Lin/Giuliano 2019


# ── TIER (ii) SHARP — small-cohort organoid (non-guarded target, thin per-lineage cohort) ──────────────
def test_small_cohort_organoid_fires_confounded():
    hl = _hl(
        model="moderate_model_coverage",
        n_models=20,
        geno="matched_sparse",
        n_alt=2,
        pdx="data_unavailable",
        pdx_frac=None,
        pdx_treat=None,
        org_lineage_class="broad_organoid_dependency",
        org_n=9,
        org_small=True,
    )
    c = tr._translational_readiness_confidence_caveat(hl, target="NOVELGENE", indication="PRAD")
    assert c["reason"] == "small_cohort_or_attribution_confounded"
    assert "THIN cohort" in c["detail"] and "28753430" in c["detail"]  # Tsherniak 2017


# ── TIER (ii) — low PDX responder fraction (weak/underpowered) also fires attribution/cohort tier ──────
def test_low_pdx_fraction_single_agent_fires_confounded():
    hl = _hl(
        model="moderate_model_coverage",
        geno="none",
        n_alt=0,
        pdx="pdx_objective_responders",
        pdx_frac=0.0272,
        pdx_treat="HDM201",
        org_class="not_organoid_dependent",
        org_lineage=None,
        org_lineage_class=None,
        org_n=None,
    )
    c = tr._translational_readiness_confidence_caveat(hl, target="MDM2", indication="STAD")
    assert c["reason"] == "small_cohort_or_attribution_confounded"
    assert "LOW" in c["detail"]


# ── TIER (i) SHARP — generic fidelity-unconfirmed default (KRAS/PAAD: models + genotype, no confound) ──
def test_fidelity_unconfirmed_default_kras_paad():
    # KRAS/PAAD is deliberately NOT in the guard (G12D allele; on-target validation lags) → falls through
    # to the generic fidelity-unconfirmed tier (no small-cohort, no PDX confound).
    hl = _hl(
        model="deep_model_coverage",
        n_models=115,
        geno="matched_deep",
        n_alt=71,
        pdx="data_unavailable",
        pdx_frac=None,
        pdx_treat=None,
        org_lineage="Pancreas",
        org_lineage_class="broad_organoid_dependency",
        org_n=23,
        org_small=False,
    )
    c = tr._translational_readiness_confidence_caveat(hl, target="KRAS", indication="PAAD")
    assert c["reason"] == "model_available_fidelity_unconfirmed"
    assert c["tier"] == "sharp" and c["false_demote_guarded"] is False
    assert "28991255" in c["detail"] and "23539594" in c["detail"]  # Ben-David 2017 / Vogelstein 2013


# ── THIN / HONEST-EMPTY (BAP1/UVM — no HCMI models, no genotype, no PDX, only pan-organoid) → None ─────
def test_thin_rare_indication_confidence_and_fidelity_none():
    # BAP1/UVM live: MODEL/GENOTYPE/PDX all data_unavailable; only a pan-organoid (NO indication lineage).
    hl = _hl(
        model="data_unavailable",
        n_models=0,
        geno="data_unavailable",
        n_alt=0,
        pdx="data_unavailable",
        pdx_frac=None,
        pdx_treat=None,
        org_class="selective_organoid_dependency",
        org_lineage=None,
        org_lineage_class=None,
        org_n=None,
    )
    assert tr._translational_readiness_confidence_caveat(hl, target="BAP1", indication="UVM") is None
    assert tr._model_fidelity_caveat(hl, target="BAP1", indication="UVM") is None
    # coverage_generalization STILL fires (leg-class fields are present, even as data_unavailable) — an
    # honest public-only note: UVM patient-derived models exist in the literature but not in the public HCMI card.
    assert (
        tr._coverage_generalization_caveat(hl, target="BAP1", indication="UVM")["reason"]
        == "public_model_only_status_partial"
    )


# ── EMPTY FIXTURE (no leg-class fields at all) → every caveat + provenance None (byte-stable) ──────────
def test_empty_fixture_all_none_byte_stable():
    hl = {}
    assert tr._translational_readiness_confidence_caveat(hl, target="FOO", indication="LUAD") is None
    assert tr._model_fidelity_caveat(hl, target="FOO", indication="LUAD") is None
    assert tr._coverage_generalization_caveat(hl, target="FOO", indication="LUAD") is None
    assert tr._translational_readiness_provenance(hl, target="FOO", indication="LUAD") is None


# ── model_fidelity_caveat fires on any positive substrate (orthogonal to validated status) ─────────────
def test_model_fidelity_caveat_fires_even_for_validated_target():
    hl = _hl()
    m = tr._model_fidelity_caveat(hl, target="ERBB2", indication="BRCA")
    assert m["reason"] == "availability_or_genotype_match_not_fidelity_or_dependence"
    assert "28991255" in m["detail"] and "30550791" in m["detail"]  # Ben-David 2017 / Neal 2018


# ── translational_readiness_provenance quorum ──────────────────────────────────────────────────────────
def test_provenance_quorum_fields():
    hl = _hl(pdx_treat="INC280 + trastuzumab", org_lineage="Breast", org_n=16, org_small=True)
    p = tr._translational_readiness_provenance(hl, target="ERBB2", indication="BRCA")
    assert p["validated_preclinical_model_flag"] is True
    assert p["pdx_treatment_is_combination"] is True
    assert p["public_model_only"] is True and p["status_partial"] is True
    assert set(p["legs_populated"]) == {"MODEL", "GENOTYPE", "ORGANOID", "PDX"}
    assert p["organoid_lineage_small_cohort"] is True


def test_provenance_excludes_data_unavailable_legs():
    hl = _hl(
        model="data_unavailable",
        n_models=0,
        geno="data_unavailable",
        n_alt=0,
        pdx="data_unavailable",
        pdx_frac=None,
        pdx_treat=None,
        org_class="selective_organoid_dependency",
        org_lineage="Bowel",
        org_lineage_class="selective_organoid_dependency",
        org_n=22,
    )
    p = tr._translational_readiness_provenance(hl, target="BAP1", indication="UVM")
    assert p["legs_populated"] == ["ORGANOID"]  # only the ORGANOID leg produced a non-unavailable read


# ── DRIFT GUARD: the curated membership containers are DICTs/SETs, never 2-string tuples ───────────────
def test_curated_containers_are_not_two_string_tuples():
    # A 2-string tuple would be misread by the reference-drift guard as a (rule_id, verdict) pair.
    assert isinstance(tr._VALIDATED_PRECLINICAL_MODEL, dict)
    assert isinstance(tr._TR_IND_ALIAS, dict)
    # every crosswalk VALUE is a str detail (not a 2-tuple), and keys are (target, indication) tuples
    for k, v in tr._VALIDATED_PRECLINICAL_MODEL.items():
        assert isinstance(k, tuple) and len(k) == 2 and isinstance(v, str)


# ── the caveats + provenance are surfaced in the synthesis facet keys ──────────────────────────────────
def test_new_fields_in_synthesis_facet_keys():
    for k in (
        "translational_readiness_confidence_caveat",
        "model_fidelity_caveat",
        "coverage_generalization_caveat",
        "translational_readiness_provenance",
    ):
        assert k in tr._SYNTHESIS_FACET_KEYS
