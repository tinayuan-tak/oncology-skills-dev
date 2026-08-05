"""Tests for sc_tumor_expression_celltype — pure stats + the monkeypatched assembler.

Mirrors tests/methods/tcga_gtex_expression_distribution/test_stats_and_assembler.py:
  - stats primitives tested purely (synthetic donor×compartment DataFrame, no S3);
  - the S3 boundary (read_gene_compartment_rows) is monkeypatched, never hit;
  - the data_unavailable safety branches (no product, gene-absent) are asserted;
  - the donor-is-replicate roll-up (cross-donor median, NOT cell-weighted) is asserted.
"""
from __future__ import annotations

import pytest

pytest.importorskip("numpy")
pytest.importorskip("pandas")

from methods.sc_tumor_expression_celltype import stats as S
from methods.sc_tumor_expression_celltype import read as R
from methods.sc_tumor_expression_celltype import cli as C


# --- fixtures ----------------------------------------------------------------

def _rows(spec):
    """spec: list of (compartment, dataset_id, donor_id, n_cells, detection_fraction, abundance)."""
    return [
        {"gene_symbol": "EPCAM", "compartment": c, "dataset_id": ds, "donor_id": d,
         "n_cells": n, "detection_fraction": det, "abundance_log1p_cp10k": ab}
        for (c, ds, d, n, det, ab) in spec
    ]


# --- compartment_summary: donor-is-replicate roll-up -------------------------

def test_compartment_summary_uses_cross_donor_median_not_cell_weighted():
    """THE load-bearing rule: one huge donor must NOT dominate. Two malignant donors — a giant
    500k-cell donor at detection 0.9 and a small donor at 0.1 — must roll up to the cross-donor
    MEDIAN (0.5), not the cell-weighted mean (~0.9)."""
    rows = _rows([
        ("malignant", "dsA", "big",   500_000, 0.9, 3.0),
        ("malignant", "dsB", "small",     100, 0.1, 0.4),
    ])
    cs = S.compartment_summary(rows)
    assert cs["malignant"]["n_donors"] == 2
    # median of {0.9, 0.1} == 0.5 — the giant donor did not dominate
    assert cs["malignant"]["median_detection_fraction"] == pytest.approx(0.5)
    assert cs["malignant"]["n_cells_total"] == 500_100


def test_compartment_summary_empty_is_empty_dict():
    assert S.compartment_summary([]) == {}


def test_compartment_summary_collapses_multiple_rows_per_donor_first():
    """If a (dataset,donor,compartment) appears in >1 row (e.g. the caller passed unaggregated
    input), per-donor aggregation happens BEFORE the cross-donor median."""
    rows = _rows([
        ("immune", "dsA", "d1", 100, 0.2, 1.0),
        ("immune", "dsA", "d1", 100, 0.4, 2.0),   # same donor, second row
        ("immune", "dsA", "d2", 100, 0.6, 3.0),
    ])
    cs = S.compartment_summary(rows)
    # d1 -> mean(0.2,0.4)=0.3 ; d2 -> 0.6 ; median across donors = median(0.3,0.6)=0.45
    assert cs["immune"]["n_donors"] == 2
    assert cs["immune"]["median_detection_fraction"] == pytest.approx(0.45)


# --- classify_sc_expression: the ladder --------------------------------------

def test_classify_malignant_broadly_detected():
    cs = {"malignant": {"n_donors": 5, "n_cells_total": 1000,
                        "median_detection_fraction": 0.7, "median_abundance_log1p_cp10k": 3.0}}
    r = S.classify_sc_expression(cs)
    assert r["sc_expression_class"] == "malignant_broadly_detected"
    assert r["malignant_compartment_available"] is True
    assert r["malignant_detection_fraction"] == 0.7


def test_classify_malignant_subset_detected():
    cs = {"malignant": {"n_donors": 5, "n_cells_total": 1000,
                        "median_detection_fraction": 0.25, "median_abundance_log1p_cp10k": 1.0}}
    assert S.classify_sc_expression(cs)["sc_expression_class"] == "malignant_subset_detected"


def test_classify_microenvironment_dominant():
    """Low malignant detection but a microenvironment compartment expressing >= microenv_min → the
    sc-unique 'present but not tumor-cell-intrinsic' call."""
    cs = {
        "malignant": {"n_donors": 5, "n_cells_total": 500,
                      "median_detection_fraction": 0.03, "median_abundance_log1p_cp10k": 0.1},
        "immune": {"n_donors": 8, "n_cells_total": 4000,
                   "median_detection_fraction": 0.6, "median_abundance_log1p_cp10k": 2.5},
    }
    r = S.classify_sc_expression(cs)
    assert r["sc_expression_class"] == "microenvironment_dominant"
    assert r["top_microenvironment_compartment"] == "immune"
    assert r["top_microenvironment_detection_fraction"] == pytest.approx(0.6)


def test_classify_broadly_low_everywhere():
    cs = {
        "malignant": {"n_donors": 5, "n_cells_total": 500,
                      "median_detection_fraction": 0.02, "median_abundance_log1p_cp10k": 0.05},
        "immune": {"n_donors": 8, "n_cells_total": 4000,
                   "median_detection_fraction": 0.03, "median_abundance_log1p_cp10k": 0.06},
    }
    assert S.classify_sc_expression(cs)["sc_expression_class"] == "broadly_low"


def test_classify_no_malignant_compartment_is_data_unavailable():
    """The STAD-shaped case: microenvironment measured but NO malignant compartment → cannot make a
    malignant-anchored call → data_unavailable with malignant_compartment_available False."""
    cs = {"immune": {"n_donors": 8, "n_cells_total": 4000,
                     "median_detection_fraction": 0.6, "median_abundance_log1p_cp10k": 2.5}}
    r = S.classify_sc_expression(cs)
    assert r["sc_expression_class"] == "data_unavailable"
    assert r["malignant_compartment_available"] is False


def test_classify_empty_summary_is_data_unavailable():
    r = S.classify_sc_expression({})
    assert r["sc_expression_class"] == "data_unavailable"
    assert r["n_compartments_measured"] == 0


# --- assembler with monkeypatched S3 reader ----------------------------------

def test_assembler_full_path(monkeypatch):
    import pandas as pd
    rows = pd.DataFrame(_rows([
        ("malignant", "dsA", "d1", 300, 0.8, 3.1),
        ("malignant", "dsB", "d2", 250, 0.6, 2.8),
        ("immune",    "dsA", "d1", 900, 0.1, 0.5),
        ("stromal",   "dsB", "d2", 120, 0.05, 0.2),
    ]))
    monkeypatch.setattr(R, "read_gene_compartment_rows", lambda t, i: rows)
    out = R.read_sc_expression_presence("EPCAM", "COADREAD")
    assert out["sc_expression_class"] == "malignant_broadly_detected"
    assert out["n_donor_groups"] == 2
    assert out["n_datasets"] == 2
    assert out["malignant_compartment_available"] is True
    assert "malignant" in out["compartment_detection"]
    assert out["product_id"] == "sc-pseudobulk-donor-celltype-coadread-v1"


def test_assembler_no_product_for_indication(monkeypatch):
    """read_gene_compartment_rows returns None (no landed product) → data_unavailable + a note."""
    monkeypatch.setattr(R, "read_gene_compartment_rows", lambda t, i: None)
    out = R.read_sc_expression_presence("EPCAM", "PAAD")
    assert out["sc_expression_class"] == "data_unavailable"
    assert "_data_note" in out


def test_assembler_gene_absent_from_product(monkeypatch):
    """Empty DataFrame (gene not in the product) → data_unavailable, distinct note from 'no product'."""
    import pandas as pd
    monkeypatch.setattr(R, "read_gene_compartment_rows",
                        lambda t, i: pd.DataFrame(columns=R._PARQUET_COLS))
    out = R.read_sc_expression_presence("MADEUPGENE", "COADREAD")
    assert out["sc_expression_class"] == "data_unavailable"
    assert "absent" in out["_data_note"]


def test_indication_product_map_covers_v1_scope():
    """v1 scope is COADREAD + NSCLC (+ their sub-codes). PAAD/STAD must NOT resolve (excluded)."""
    assert R._product_key("COADREAD") is not None
    assert R._product_key("NSCLC") is not None
    assert R._product_key("LUAD") is not None
    assert R._product_key("PAAD") is None
    assert R._product_key("STAD") is None


def test_cli_build_summary_adds_method_version(monkeypatch):
    monkeypatch.setattr(R, "read_gene_compartment_rows", lambda t, i: None)
    out = C.build_summary("EPCAM", "PAAD")
    assert out["method_version"] == C.METHOD_VERSION
    assert out["sc_expression_class"] == "data_unavailable"
