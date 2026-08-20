"""Surfacing guard (2026-08-20): the two-axis TCE antigen-escape readout must appear in the assembled
sc-tumor card summary (read_sc_expression_presence), on both the measured path and the data_unavailable
path. Kept in its own file so it does not touch test_stats_and_assembler.py (shared with open PR #387).
"""
from __future__ import annotations

import pytest

pytest.importorskip("numpy")
pytest.importorskip("pandas")

from methods.sc_tumor_expression_celltype import read as R

_HET_KEYS = ("within_tumor_coverage_class", "inter_donor_consistency_class", "tce_antigen_escape_class",
             "malignant_detection_donor_iqr", "fraction_donors_broadly_detecting")


def _rows(spec):
    return [
        {"gene_symbol": "EPCAM", "compartment": c, "dataset_id": ds, "donor_id": d,
         "n_cells": n, "detection_fraction": det, "abundance_log1p_cp10k": ab}
        for (c, ds, d, n, det, ab) in spec
    ]


def test_heterogeneity_fields_surfaced_on_measured_path(monkeypatch):
    import pandas as pd
    # 5 malignant donors, all high + tight → high coverage, consistent → escape_risk_low.
    rows = pd.DataFrame(_rows([
        ("malignant", "dsA", "d1", 300, 0.86, 3.1),
        ("malignant", "dsA", "d2", 250, 0.88, 2.8),
        ("malignant", "dsA", "d3", 280, 0.90, 3.0),
        ("malignant", "dsB", "d4", 220, 0.84, 2.9),
        ("malignant", "dsB", "d5", 260, 0.92, 2.7),
        ("immune",    "dsA", "d1", 900, 0.10, 0.5),
    ]))
    monkeypatch.setattr(R, "read_gene_compartment_rows", lambda t, i: rows)
    out = R.read_sc_expression_presence("EPCAM", "COADREAD")
    for k in _HET_KEYS:
        assert k in out, f"{k} not surfaced into the sc card summary"
    assert out["within_tumor_coverage_class"] == "high"
    assert out["inter_donor_consistency_class"] == "consistent"
    assert out["tce_antigen_escape_class"] == "escape_risk_low"
    assert isinstance(out["malignant_detection_donor_iqr"], float)
    # the legacy lenient lens is still present (back-compat)
    assert out["tce_homogeneity_class"] == "homogeneous"


def test_heterogeneity_fields_surfaced_on_data_unavailable_path(monkeypatch):
    monkeypatch.setattr(R, "read_gene_compartment_rows", lambda t, i: None)
    out = R.read_sc_expression_presence("EPCAM", "PAAD")
    for k in _HET_KEYS:
        assert k in out
    assert out["tce_antigen_escape_class"] == "data_unavailable"
    assert out["within_tumor_coverage_class"] == "data_unavailable"
    assert out["malignant_detection_donor_iqr"] is None


def test_patient_variable_escape_surfaced(monkeypatch):
    """Donors disagree (some ~0, some ~0.9) → inter-donor variable → escape_risk_patient_variable
    reaches the card, the patient-selection signal bulk homogeneity could never show."""
    import pandas as pd
    rows = pd.DataFrame(_rows([
        ("malignant", "dsA", "d1", 300, 0.05, 0.2),
        ("malignant", "dsA", "d2", 250, 0.08, 0.3),
        ("malignant", "dsA", "d3", 280, 0.90, 3.0),
        ("malignant", "dsB", "d4", 220, 0.92, 3.1),
        ("malignant", "dsB", "d5", 260, 0.88, 2.9),
    ]))
    monkeypatch.setattr(R, "read_gene_compartment_rows", lambda t, i: rows)
    out = R.read_sc_expression_presence("EPCAM", "COADREAD")
    assert out["inter_donor_consistency_class"] == "variable"
    assert out["tce_antigen_escape_class"] == "escape_risk_patient_variable"
