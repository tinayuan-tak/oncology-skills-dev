"""Unit tests for genomic-alteration-profile's claim vector (skills/_skills_common/genomic_claims.py),
the FOURTH concrete over claim_vector_core. Pin the per-class SNV/CN/FUS driver tiers + the DEP
(alteration-confers-dependency) max-over-stratified-classes + corroboration + the multi-class headline.
Pure over a headline dict — no S3, no card reads.

The KRAS-shaped headline mirrors the frozen KRAS/COADREAD genomic replay fixture; ERBB2/MET-shaped
contrast cases exercise amplification- and fusion-driven mixes (the whole point of the multi-class
skill — it must not read "not a driver" for an amp/fusion-driven target).
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]        # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.genomic_claims import genomic_claim_vector, genomic_key_signals  # noqa: E402


def _by_class(snv_landscape=None, snv_rec=None, cn=None, amp_expr=None, cn_strat=None,
              fusion=None, fusion_strat=None, genie_sv=None, mut_strat=None):
    return {
        "snv_indel": {"verdict": snv_landscape, "recurrence_class": snv_rec,
                      "stratified_dependency_class": mut_strat},
        "copy_number": {"verdict": cn, "stratified_dependency_class": cn_strat,
                        "amp_expr_dependency_class": amp_expr},
        "fusion": {"verdict": fusion, "stratified_dependency_class": fusion_strat,
                   "genie_sv_recurrence_class": genie_sv},
    }


def _kras_headline():
    """KRAS/COADREAD-shaped: recurrent missense SNV driver (top_1pct), no CN/fusion, strong
    mutant-selective + amp-expr dependency, drug-sensitive."""
    return {
        "genomic_alteration_by_class": _by_class(
            snv_landscape="missense_dominant", snv_rec="top_1pct",
            cn="broadly_neutral", amp_expr="amplified_overexpressed_strongly_dependent",
            cn_strat="amplified_moderately_dependent",
            fusion="no_recurrent_fusion", fusion_strat="fusion_positive_moderately_dependent",
            genie_sv="mid", mut_strat="mutant_strongly_dependent"),
        "driver_recurrence_class": "top_1pct", "genie_driver_recurrence_class": "top_1pct",
        "overall_mutation_frequency": 0.42, "patient_focal_cn_class": "focal_neutral",
        "mutation_stratification_class": "mutant_strongly_dependent", "stratified_evidence_scope": "within_indication",
        "cn_stratification_class": "amplified_moderately_dependent",
        "amp_expr_stratification_class": "amplified_overexpressed_strongly_dependent",
        "fusion_stratification_class": "fusion_positive_moderately_dependent",
        "drug_response_stratification_class": "mutant_strongly_drug_sensitive",
    }


def test_kras_snv_driven_with_dependency():
    vec = genomic_claim_vector(_kras_headline(), [])
    assert vec["SNV"]["signal"] == "strong"
    assert vec["CN"]["signal"] == "absent" and vec["FUS"]["signal"] == "absent"
    # DEP = max over the 4 stratified classes (mutant_strongly + amp_expr_strongly → strong), drug-confirmed
    assert vec["DEP"]["signal"] == "strong" and vec["DEP"]["corroboration"] == "high"
    ks = genomic_key_signals(_kras_headline(), [])
    assert ks["headline"] == "SNV/indel-driven alteration, biomarker-stratified dependency."


def test_amplification_driven_is_not_read_as_not_a_driver():
    """ERBB2-shaped: broadly-neutral SNV but recurrently amplified + patient-focal-confirmed. The
    multi-class skill must surface the CN driver, not imply 'not a driver' off the SNV axis."""
    h = {
        "genomic_alteration_by_class": _by_class(
            snv_landscape="no_mutations", cn="recurrently_amplified",
            amp_expr="amplified_overexpressed_strongly_dependent", fusion="no_recurrent_fusion"),
        "driver_recurrence_class": "bottom_decile", "patient_focal_cn_class": "recurrent_focal_amplification",
        "amp_expr_stratification_class": "amplified_overexpressed_strongly_dependent",
        "drug_response_stratification_class": "not_drug_response_stratified",
    }
    vec = genomic_claim_vector(h, [])
    assert vec["SNV"]["signal"] == "absent"        # no SNV
    assert vec["CN"]["signal"] == "strong"         # cell-line amplified + patient-focal confirms → strong
    assert vec["CN"]["corroboration"] == "high"
    assert vec["DEP"]["signal"] == "strong"
    ks = genomic_key_signals(h, [])
    assert ks["headline"].startswith("Copy-number-driven alteration")


def test_fusion_driven():
    h = {
        "genomic_alteration_by_class": _by_class(
            snv_landscape="no_mutations", cn="broadly_neutral",
            fusion="recurrent_fusion_driver", fusion_strat="fusion_positive_strongly_dependent",
            genie_sv="top_1pct"),
        "fusion_stratification_class": "fusion_positive_strongly_dependent",
        "drug_response_stratification_class": "data_unavailable",
    }
    vec = genomic_claim_vector(h, [])
    assert vec["FUS"]["signal"] == "strong" and vec["FUS"]["corroboration"] == "high"
    assert vec["DEP"]["signal"] == "strong"
    assert genomic_key_signals(h, [])["headline"].startswith("Fusion-driven alteration")


def test_multi_class_driver():
    h = {
        "genomic_alteration_by_class": _by_class(
            snv_landscape="missense_dominant", snv_rec="top_decile", cn="recurrently_amplified"),
        "driver_recurrence_class": "top_decile", "patient_focal_cn_class": "recurrent_focal_amplification",
    }
    ks = genomic_key_signals(h, [])
    assert ks["headline"].startswith("Multi-class alteration driver")


def test_passenger_and_wt_dependent_is_absent_dep():
    """A passenger with a WT-dependent (not alteration-conferred) dependency: DEP must be `absent`,
    NOT read as the alteration conferring the dependency."""
    h = {
        "genomic_alteration_by_class": _by_class(
            snv_landscape="missense_dominant", snv_rec="bottom_decile", cn="broadly_neutral",
            fusion="no_recurrent_fusion", mut_strat="wt_strongly_dependent"),
        "driver_recurrence_class": "bottom_decile",
        "mutation_stratification_class": "wt_strongly_dependent",
        "drug_response_stratification_class": "data_unavailable",
    }
    vec = genomic_claim_vector(h, [])
    assert vec["SNV"]["signal"] == "absent"
    assert vec["DEP"]["signal"] == "absent"        # WT is dependent → the ALTERATION does not confer it
    assert genomic_key_signals(h, [])["headline"] == "No recurrent alteration (passenger / not altered)."


def test_dep_underpowered_is_gap_not_absent():
    h = {
        "genomic_alteration_by_class": _by_class(snv_landscape="missense_dominant", snv_rec="mid"),
        "driver_recurrence_class": "mid",
        "mutation_stratification_class": "insufficient_mutation_rate",
        "cn_stratification_class": "data_unavailable",
        "amp_expr_stratification_class": "data_unavailable",
        "fusion_stratification_class": "data_unavailable",
    }
    vec = genomic_claim_vector(h, [])
    assert vec["DEP"]["signal"] == "unmeasured"     # insufficient-rate + data_unavailable → gap, not absent


def test_field_names_are_corroboration():
    vec = genomic_claim_vector(_kras_headline(), [])
    assert "corroboration" in vec["SNV"] and "reliability" not in vec["SNV"]
