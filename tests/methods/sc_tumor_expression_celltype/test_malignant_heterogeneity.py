"""Two-axis TCE antigen-escape heterogeneity (2026-08-20).

The prior tce_homogeneity_class re-binned malignant_detection_fraction alone with a lenient 0.5 bar.
These tests cover the replacement: compartment_summary now emits INTER-DONOR dispersion of detection
fraction (the per-donor array it previously discarded), and malignant_heterogeneity_readout combines a
WITHIN-tumour coverage axis (detection fraction) with an INTER-tumour consistency axis (donor dispersion)
into an antigen-escape call. Pure stats — synthetic donor×compartment rows, no S3.
"""
from __future__ import annotations

import pytest

pytest.importorskip("numpy")
pytest.importorskip("pandas")

from methods.sc_tumor_expression_celltype import stats as S


def _rows(spec):
    """spec: list of (compartment, dataset_id, donor_id, n_cells, detection_fraction, abundance)."""
    return [
        {"gene_symbol": "T", "compartment": c, "dataset_id": ds, "donor_id": d,
         "n_cells": n, "detection_fraction": det, "abundance_log1p_cp10k": ab}
        for (c, ds, d, n, det, ab) in spec
    ]


def _uniform_malignant(dets):
    """One malignant compartment across len(dets) donors (distinct datasets) at the given detections."""
    return _rows([("malignant", f"ds{i}", f"dn{i}", 100, det, 1.0) for i, det in enumerate(dets)])


# ── inter-donor dispersion in compartment_summary ────────────────────────────────────────────────
def test_dispersion_fields_present_and_correct_with_enough_donors():
    cs = S.compartment_summary(_uniform_malignant([0.2, 0.4, 0.6, 0.8]))
    m = cs["malignant"]
    assert m["n_donors"] == 4
    # p25/p75 of [0.2,0.4,0.6,0.8] = 0.35 / 0.65 → IQR 0.30
    assert m["detection_fraction_donor_iqr"] == pytest.approx(0.30, abs=1e-6)
    assert m["detection_fraction_donor_p25"] == pytest.approx(0.35, abs=1e-6)
    assert m["detection_fraction_donor_p75"] == pytest.approx(0.65, abs=1e-6)
    # 2 of 4 donors (0.6, 0.8) are >= DONOR_BROAD_DETECTION_MIN (0.5)
    assert m["fraction_donors_broadly_detecting"] == pytest.approx(0.5, abs=1e-6)


def test_dispersion_none_when_under_powered():
    """IQR on <3 donors is meaningless — emit None (honest gap), never a fabricated 0."""
    cs = S.compartment_summary(_uniform_malignant([0.9, 0.9]))
    m = cs["malignant"]
    assert m["n_donors"] == 2
    assert m["detection_fraction_donor_iqr"] is None
    assert m["fraction_donors_broadly_detecting"] is None
    # the legacy median is still emitted (backward-compat)
    assert m["median_detection_fraction"] == pytest.approx(0.9)


def test_median_unchanged_backward_compatible():
    """The pre-existing keys keep their values — this change is purely additive."""
    cs = S.compartment_summary(_uniform_malignant([0.2, 0.4, 0.6, 0.8]))
    assert cs["malignant"]["median_detection_fraction"] == pytest.approx(0.5)


# ── two-axis readout: escape-risk class ──────────────────────────────────────────────────────────
def test_escape_risk_low_high_coverage_consistent():
    """High within-tumour coverage AND tight across donors → the TCE-favourable case."""
    r = S.malignant_heterogeneity_readout(S.compartment_summary(_uniform_malignant([0.85, 0.88, 0.9, 0.92])))
    assert r["within_tumor_coverage_class"] == "high"
    assert r["inter_donor_consistency_class"] == "consistent"
    assert r["tce_antigen_escape_class"] == "escape_risk_low"


def test_escape_risk_high_when_within_tumor_coverage_low():
    """Coverage-first: median detection < 0.5 is an escape reservoir regardless of donor consistency."""
    r = S.malignant_heterogeneity_readout(S.compartment_summary(_uniform_malignant([0.1, 0.12, 0.15, 0.13])))
    assert r["within_tumor_coverage_class"] == "low"
    assert r["tce_antigen_escape_class"] == "escape_risk_high"


def test_escape_risk_patient_variable_when_donors_disagree():
    """Some patients express broadly, others near-zero → high inter-donor IQR → patient-variable escape,
    even though the median coverage may clear the partial/high bar."""
    r = S.malignant_heterogeneity_readout(S.compartment_summary(_uniform_malignant([0.05, 0.1, 0.9, 0.95])))
    assert r["inter_donor_consistency_class"] == "variable"
    assert r["tce_antigen_escape_class"] == "escape_risk_patient_variable"


def test_coverage_high_donor_underpowered_flagged_not_faked():
    """High coverage but too few donors to test consistency → an honest 'underpowered' escape class,
    not a false escape_risk_low."""
    r = S.malignant_heterogeneity_readout(S.compartment_summary(_uniform_malignant([0.9, 0.92])))
    assert r["within_tumor_coverage_class"] == "high"
    assert r["inter_donor_consistency_class"] == "underpowered"
    assert r["tce_antigen_escape_class"] == "coverage_high_donor_underpowered"


def test_data_unavailable_when_no_malignant_compartment():
    r = S.malignant_heterogeneity_readout(S.compartment_summary(
        _rows([("stromal", "ds0", "dn0", 100, 0.4, 1.0)])))
    assert r["tce_antigen_escape_class"] == "data_unavailable"
    assert r["within_tumor_coverage_class"] == "data_unavailable"


def test_tighter_bar_than_legacy_homogeneity():
    """The design intent: 0.5-0.75 malignant detection is 'partial' coverage here (escape_risk_moderate),
    whereas the legacy single-number classifier called >=0.5 'homogeneous'. Guards the tightening."""
    cs = S.compartment_summary(_uniform_malignant([0.55, 0.6, 0.62, 0.58]))
    r = S.malignant_heterogeneity_readout(cs)
    assert r["within_tumor_coverage_class"] == "partial"
    assert r["tce_antigen_escape_class"] in ("escape_risk_moderate",)
    # legacy classifier would (still) call this homogeneous — proving the two are distinct lenses
    assert S.classify_tce_homogeneity(cs["malignant"]["median_detection_fraction"], True) == "homogeneous"
