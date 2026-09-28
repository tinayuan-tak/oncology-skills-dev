"""Surfacing guard (Option-A, #695): the INERT descriptive per-compartment inter-donor heterogeneity
vector must appear in the assembled sc-tumor card summary (read_sc_expression_presence), on both the
measured path and the data_unavailable path — mirroring test_heterogeneity_surfacing.py. It reuses the
inter-donor dispersion compartment_summary ALREADY computes for every compartment (NO new pseudobulk
columns) and is verdict-inert (no class call, no gate). Kept in its own file so it does not touch
test_stats_and_assembler.py.
"""

from __future__ import annotations

import pytest

pytest.importorskip("numpy")
pytest.importorskip("pandas")

from methods.sc_tumor_expression_celltype import read as R
from methods.sc_tumor_expression_celltype import stats as S

_ENTRY_KEYS = (
    "compartment",
    "n_donors",
    "median_detection_fraction",
    "detection_fraction_donor_p25",
    "detection_fraction_donor_p75",
    "detection_fraction_donor_iqr",
    "fraction_donors_broadly_detecting",
    "dispersion_available",
)


def _rows(spec):
    return [
        {
            "gene_symbol": "EPCAM",
            "compartment": c,
            "dataset_id": ds,
            "donor_id": d,
            "n_cells": n,
            "detection_fraction": det,
            "abundance_log1p_cp10k": ab,
        }
        for (c, ds, d, n, det, ab) in spec
    ]


def test_per_compartment_heterogeneity_surfaced_on_measured_path(monkeypatch):
    import pandas as pd

    # 5 malignant donors (dispersion testable) + 3 immune donors (dispersion testable) + 1 stromal
    # donor (under-powered → dispersion_available False, fields None). Ordered malignant, stromal, immune.
    rows = pd.DataFrame(
        _rows(
            [
                ("malignant", "dsA", "d1", 300, 0.86, 3.1),
                ("malignant", "dsA", "d2", 250, 0.88, 2.8),
                ("malignant", "dsA", "d3", 280, 0.90, 3.0),
                ("malignant", "dsB", "d4", 220, 0.84, 2.9),
                ("malignant", "dsB", "d5", 260, 0.92, 2.7),
                ("immune", "dsA", "d1", 900, 0.10, 0.5),
                ("immune", "dsA", "d2", 850, 0.14, 0.6),
                ("immune", "dsA", "d3", 800, 0.12, 0.55),
                ("stromal", "dsA", "d1", 500, 0.40, 1.2),
            ]
        )
    )
    monkeypatch.setattr(R, "read_gene_compartment_rows", lambda t, i: rows)
    out = R.read_sc_expression_presence("EPCAM", "COADREAD")

    assert "per_compartment_heterogeneity" in out, "descriptive heterogeneity vector not surfaced"
    vec = out["per_compartment_heterogeneity"]
    assert isinstance(vec, list) and vec, "expected a non-empty per-compartment heterogeneity vector"
    for entry in vec:
        for k in _ENTRY_KEYS:
            assert k in entry, f"{k} missing from a per_compartment_heterogeneity entry"

    by_comp = {e["compartment"]: e for e in vec}
    # canonical order: malignant, stromal, immune (COMPARTMENT_ORDER, measured only)
    assert [e["compartment"] for e in vec] == ["malignant", "stromal", "immune"]

    # malignant: 5 donors → dispersion computed, tight IQR, most donors broadly detect
    mal = by_comp["malignant"]
    assert mal["n_donors"] == 5
    assert mal["dispersion_available"] is True
    assert isinstance(mal["detection_fraction_donor_iqr"], float)
    assert mal["detection_fraction_donor_iqr"] >= 0.0
    assert mal["fraction_donors_broadly_detecting"] == 1.0

    # immune: 3 donors → still dispersion-testable
    assert by_comp["immune"]["dispersion_available"] is True

    # stromal: 1 reliable donor → under-powered → dispersion None, flagged not-available (honest gap)
    strom = by_comp["stromal"]
    assert strom["n_donors"] == 1
    assert strom["dispersion_available"] is False
    assert strom["detection_fraction_donor_iqr"] is None
    assert strom["detection_fraction_donor_p25"] is None
    assert strom["fraction_donors_broadly_detecting"] is None


def test_per_compartment_heterogeneity_surfaced_on_data_unavailable_path(monkeypatch):
    monkeypatch.setattr(R, "read_gene_compartment_rows", lambda t, i: None)
    out = R.read_sc_expression_presence("EPCAM", "PAAD")
    assert "per_compartment_heterogeneity" in out
    assert out["per_compartment_heterogeneity"] == []


def test_vector_verdict_inert_does_not_touch_presence_spine(monkeypatch):
    """The descriptive vector must not alter any presence/gate field — a byte-for-byte guard that the
    surfacing is additive. The spine keys read exactly as the two-axis heterogeneity test expects."""
    import pandas as pd

    rows = pd.DataFrame(
        _rows(
            [
                ("malignant", "dsA", "d1", 300, 0.86, 3.1),
                ("malignant", "dsA", "d2", 250, 0.88, 2.8),
                ("malignant", "dsA", "d3", 280, 0.90, 3.0),
                ("malignant", "dsB", "d4", 220, 0.84, 2.9),
                ("malignant", "dsB", "d5", 260, 0.92, 2.7),
            ]
        )
    )
    monkeypatch.setattr(R, "read_gene_compartment_rows", lambda t, i: rows)
    out = R.read_sc_expression_presence("EPCAM", "COADREAD")
    # presence spine unchanged by the additive readout
    assert out["sc_expression_class"] == "malignant_broadly_detected"
    assert out["tce_antigen_escape_class"] == "escape_risk_low"
    # the malignant entry of the descriptive vector agrees with the malignant-only TCE readout substrate
    mal = next(e for e in out["per_compartment_heterogeneity"] if e["compartment"] == "malignant")
    assert mal["detection_fraction_donor_iqr"] == out["malignant_detection_donor_iqr"]
    assert mal["median_detection_fraction"] == out["malignant_detection_fraction"]


def test_vector_empty_summary_is_empty_list():
    assert S.per_compartment_heterogeneity_vector({}) == []
    assert S.per_compartment_heterogeneity_vector(None) == []
