"""civic_variant_interpretation — per-gene CIViC per-variant interpretation.

Tests inject synthetic VariantSummaries / ClinicalEvidence / AssertionSummaries frames
(no S3) and pin: the single-variant-MP→gene join, oncogenicity precedence (graded assertion
> functional > sensitivity-implied), the benign guard, resistance extraction, and the
single-variant-only scope (complex/fusion MPs excluded).
"""

from __future__ import annotations

import pandas as pd

from onc_methods.civic_variant_interpretation import read as R


def _setup(monkeypatch, variants, evidence, assertions):
    """variants: [(mp_id, gene, variant)]; evidence: [(mp_id, etype, edir, sig, therapies)];
    assertions: [(mp_id, atype, sig)]."""
    R._mp_to_gene_variant.cache_clear()
    R._load.cache_clear()
    vs = pd.DataFrame(variants, columns=["single_variant_molecular_profile_id", "gene", "variant"])
    ev = pd.DataFrame(
        evidence, columns=["molecular_profile_id", "evidence_type", "evidence_direction", "significance", "therapies"]
    )
    asrt = pd.DataFrame(assertions, columns=["molecular_profile_id", "assertion_type", "significance"])

    def _fake_read(key):
        if key == R._VARIANT_KEY:
            return vs
        if key == R._EVIDENCE_KEY:
            return ev
        if key == R._ASSERTION_KEY:
            return asrt
        raise KeyError(key)

    monkeypatch.setattr(R, "_read_tsv", _fake_read)


def test_single_variant_join_and_graded_assertion(monkeypatch):
    # BRAF V600E (mp 1): a graded Oncogenic assertion → oncogenic (the strongest call).
    _setup(
        monkeypatch,
        variants=[("1", "BRAF", "V600E")],
        evidence=[("1", "Predictive", "Supports", "Sensitivity/Response", "Vemurafenib")],
        assertions=[("1", "Oncogenic", "Oncogenic")],
    )
    out = R.civic_interpretation_for_gene("BRAF")
    assert out["strongest_oncogenicity_class"] == "oncogenic"  # graded assertion wins over sensitivity
    assert out["has_oncogenic_variant"] is True
    assert out["n_interpreted_variants"] == 1


def test_sensitivity_implies_likely_oncogenic(monkeypatch):
    # EGFR L858R (mp 2): only Predictive Sensitivity evidence, no graded assertion → likely_oncogenic.
    _setup(
        monkeypatch,
        variants=[("2", "EGFR", "L858R")],
        evidence=[("2", "Predictive", "Supports", "Sensitivity/Response", "Osimertinib")],
        assertions=[],
    )
    out = R.civic_interpretation_for_gene("EGFR")
    assert out["strongest_oncogenicity_class"] == "likely_oncogenic"
    assert "L858R" in [v["variant"] for v in out["oncogenic_variants"]]


def test_benign_assertion_not_overridden_by_sensitivity(monkeypatch):
    # A variant graded Benign must NOT be lifted by a stray sensitivity row (guard).
    _setup(
        monkeypatch,
        variants=[("3", "GENEX", "P123P")],
        evidence=[("3", "Predictive", "Supports", "Sensitivity/Response", "DrugX")],
        assertions=[("3", "Oncogenic", "Benign")],
    )
    out = R.civic_interpretation_for_gene("GENEX")
    assert out["strongest_oncogenicity_class"] == "benign"
    assert out["has_oncogenic_variant"] is False


def test_functional_gof_maps_to_likely_oncogenic(monkeypatch):
    _setup(
        monkeypatch,
        variants=[("4", "KIT", "D816V")],
        evidence=[("4", "Functional", "Supports", "Gain of Function", "")],
        assertions=[],
    )
    out = R.civic_interpretation_for_gene("KIT")
    assert out["strongest_oncogenicity_class"] == "likely_oncogenic"


def test_resistance_extraction_with_therapies(monkeypatch):
    # EGFR T790M (mp 5): Predictive Resistance → known_resistance + therapies captured.
    _setup(
        monkeypatch,
        variants=[("5", "EGFR", "T790M")],
        evidence=[
            ("5", "Predictive", "Supports", "Resistance", "Gefitinib"),
            ("5", "Predictive", "Supports", "Resistance", "Erlotinib"),
        ],
        assertions=[],
    )
    out = R.civic_interpretation_for_gene("EGFR")
    assert out["resistance_variant_count"] == 1
    rv = out["resistance_variants"][0]
    assert rv["variant"] == "T790M" and rv["resistance_class"] == "known_resistance"
    assert set(rv["therapies"]) == {"Gefitinib", "Erlotinib"}


def test_known_resistance_dominates_reduced_sensitivity(monkeypatch):
    _setup(
        monkeypatch,
        variants=[("6", "GENEY", "X1Y")],
        evidence=[
            ("6", "Predictive", "Supports", "Reduced Sensitivity", "DrugA"),
            ("6", "Predictive", "Supports", "Resistance", "DrugB"),
        ],
        assertions=[],
    )
    out = R.civic_interpretation_for_gene("GENEY")
    assert out["resistance_variants"][0]["resistance_class"] == "known_resistance"


def test_complex_profile_excluded(monkeypatch):
    # A ClinicalEvidence row on mp 99 that has NO single-variant entry (complex/fusion) is dropped.
    _setup(
        monkeypatch,
        variants=[("7", "ALK", "F1174L")],  # single-variant, kept
        evidence=[
            ("99", "Predictive", "Supports", "Resistance", "Crizotinib"),  # complex mp → excluded
            ("7", "Predictive", "Supports", "Sensitivity/Response", "Crizotinib"),
        ],
        assertions=[],
    )
    out_alk = R.civic_interpretation_for_gene("ALK")
    assert out_alk["n_interpreted_variants"] == 1  # only F1174L, not the complex mp
    assert out_alk["strongest_oncogenicity_class"] == "likely_oncogenic"


def test_gene_absent_is_data_unavailable(monkeypatch):
    _setup(
        monkeypatch,
        variants=[("1", "BRAF", "V600E")],
        evidence=[("1", "Predictive", "Supports", "Sensitivity/Response", "Vemurafenib")],
        assertions=[],
    )
    out = R.civic_interpretation_for_gene("MADEUPGENE")
    assert out["civic_variant_class"] == "data_unavailable"
    assert out["n_interpreted_variants"] == 0
    assert "no single-variant CIViC evidence" in out["civic_interpretation_context"]
