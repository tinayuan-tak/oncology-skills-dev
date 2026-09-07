"""Addressable-population facet — verdict-inert patient-population sizing (2026-08-14).

Reconstructs the deleted patient-population-and-access layer as a COMPOSITION over signals already on
the fan-out: joins the target's SELECTION BASIS (genomic + dependency verdicts) to the in-indication
PREVALENCE of that basis (mutation-hotspot-frequency: genie_mutation_frequency preferred, MC3 fallback).
Hermetic: synthetic sub_results carrying both `verdict` tuples and the frequency card.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

run = load_run_py(Path(__file__).resolve().parents[1], "tp_run_addrpop")


def _sr(*, gen_verdict=None, dep_verdict=None, hf_summary=None):
    """Build a minimal sub_results with a genomic verdict, dependency verdict, and (in the genomic
    sub-skill's cards) a mutation-hotspot-frequency summary."""
    sr = {}
    gcards = []
    if hf_summary is not None:
        gcards = [{"card_id": "mutation-hotspot-frequency", "summary": hf_summary}]
    sr["genomic_alteration"] = {"verdict": (gen_verdict, "gen-rule") if gen_verdict else None, "cards": gcards}
    sr["dependency"] = {"verdict": (dep_verdict, "dep-rule") if dep_verdict else None, "cards": []}
    return sr


_HF_KRAS = {"genie_mutation_frequency": 0.435, "overall_mutation_frequency": 0.42, "n_samples_in_indication": 559}


def test_snv_stratified_broad_uses_genie_prevalence():
    f = run._addressable_population_facet(_sr(gen_verdict="biomarker_stratified_dependency", hf_summary=_HF_KRAS))
    assert f["selection_basis"] == "snv_indel_stratified"
    assert f["biomarker_prevalence"] == 0.435
    assert f["prevalence_source"] == "genie"  # coverage-correct GENIE preferred over MC3
    assert f["addressable_population_class"] == "broad"  # >= 0.20
    assert f["n_samples_in_indication"] == 559


def test_prevalence_tiers():
    for freq, expected in [
        (0.43, "broad"),
        (0.08, "common"),
        (0.02, "uncommon"),
        (0.004, "rare"),
        (0.0005, "ultra_rare"),
    ]:
        f = run._addressable_population_facet(
            _sr(
                gen_verdict="confirmed_driver",
                hf_summary={"genie_mutation_frequency": freq, "n_samples_in_indication": 100},
            )
        )
        assert f["addressable_population_class"] == expected, f"freq={freq} -> {f['addressable_population_class']}"


def test_mc3_fallback_when_genie_absent():
    f = run._addressable_population_facet(
        _sr(
            gen_verdict="missense_dominant_pattern",
            hf_summary={"overall_mutation_frequency": 0.12, "n_samples_in_indication": 300},
        )
    )
    assert f["prevalence_source"] == "tcga_mc3"
    assert f["biomarker_prevalence"] == 0.12
    assert f["addressable_population_class"] == "common"


def test_broad_dependency_is_biomarker_unrestricted():
    # no alteration-selection verdict, but a real dependency → whole indication is addressable
    f = run._addressable_population_facet(
        _sr(gen_verdict="passenger_pattern", dep_verdict="selective_dependency", hf_summary=_HF_KRAS)
    )
    assert f["selection_basis"] == "biomarker_unrestricted"
    assert f["addressable_population_class"] == "biomarker_unrestricted"


def test_cn_fusion_stratified_not_estimated_this_axis():
    # a CN-defined subgroup: SNV frequency is the wrong denominator → honest not_estimated
    f = run._addressable_population_facet(_sr(gen_verdict="recurrent_amplification_driver", hf_summary=_HF_KRAS))
    assert f["selection_basis"] == "copy_number_or_fusion_stratified"
    assert f["addressable_population_class"] == "not_estimated_this_axis"
    assert f["biomarker_prevalence"] is None  # SNV freq deliberately not used


def test_undetermined_when_no_selection_and_no_dependency():
    f = run._addressable_population_facet(
        _sr(gen_verdict="passenger_pattern", dep_verdict="non_dependent", hf_summary=None)
    )
    assert f["selection_basis"] == "undetermined"
    assert f["addressable_population_class"] is None
