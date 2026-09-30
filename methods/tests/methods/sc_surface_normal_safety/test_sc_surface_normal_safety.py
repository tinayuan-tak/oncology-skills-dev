"""Tests for sc_surface_normal_safety — normal-immune surface-protein liability ladder. No S3:
read_gene_rows is monkeypatched."""

from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")

from onc_methods.sc_surface_normal_safety import cli as C
from onc_methods.sc_surface_normal_safety import read as R


def _rows(pairs):
    # pairs: list of (cell_type, positive_fraction, mean_clr)
    return pd.DataFrame(
        [
            {
                "gene_symbol": "CD8A",
                "hgnc_id": "HGNC:1706",
                "adt_proteins": "CD8",
                "cell_type": ct,
                "compartment_scope": "immune_pbmc",
                "n_cells": 500,
                "n_donors": 8,
                "adt_mean_clr_median": clr,
                "adt_positive_fraction_median": pf,
            }
            for ct, pf, clr in pairs
        ]
    )


@pytest.mark.parametrize(
    "peak_clr,expected",
    [
        (4.0, "high_surface_on_normal_immune"),
        (1.0, "moderate_surface_on_normal_immune"),
        (0.2, "low_surface_on_normal_immune"),
        (-0.5, "not_surface_detected_normal_immune"),
    ],
)
def test_liability_ladder(monkeypatch, peak_clr, expected):
    # classifier keys on PEAK mean-CLR, not positive_fraction (ambient-background overcall)
    monkeypatch.setattr(R, "read_gene_rows", lambda t: _rows([("CD8 Naive", 0.9, peak_clr), ("B naive", 0.9, -1.5)]))
    s = R.read_sc_surface_normal_safety("CD8A")
    assert s["sc_surface_normal_class"] == expected
    assert s["max_surface_cell_type"] == "CD8 Naive"  # highest mean-CLR lineage
    assert s["max_mean_clr"] == round(peak_clr, 4)


def test_breadth_count_uses_clr_not_posfrac(monkeypatch):
    # B naive has HIGH positive_fraction (0.9) but LOW mean-CLR (-1.0 = spillover) → must NOT count.
    monkeypatch.setattr(
        R, "read_gene_rows", lambda t: _rows([("CD8 Naive", 0.9, 4.0), ("CD8 TEM", 0.9, 3.9), ("B naive", 0.9, -1.0)])
    )
    s = R.read_sc_surface_normal_safety("CD8A")
    assert s["n_celltypes_surface_displaying"] == 2  # only the 2 T lineages clear the CLR floor


def test_product_missing_vs_gene_absent(monkeypatch):
    monkeypatch.setattr(R, "read_gene_rows", lambda t: None)
    assert R.read_sc_surface_normal_safety("CD8A")["sc_surface_normal_class"] == "data_unavailable"
    monkeypatch.setattr(R, "read_gene_rows", lambda t: pd.DataFrame(columns=R._PARQUET_COLS))
    s = R.read_sc_surface_normal_safety("KRAS")
    assert s["sc_surface_normal_class"] == "data_unavailable"
    assert "not surface-profiled" in s["_data_note"]


def _rows_support(triples):
    # triples: list of (cell_type, mean_clr, n_donors, n_cells)
    return pd.DataFrame(
        [
            {
                "gene_symbol": "CD8A",
                "hgnc_id": "HGNC:1706",
                "adt_proteins": "CD8",
                "cell_type": ct,
                "compartment_scope": "immune_pbmc",
                "n_cells": nc,
                "n_donors": nd,
                "adt_mean_clr_median": clr,
                "adt_positive_fraction_median": 0.9,
            }
            for ct, clr, nd, nc in triples
        ]
    )


def test_thin_support_high_peak_demotes(monkeypatch):
    # A thin cell type (1 donor / 5 cells) with peak CLR clearing _HIGH must NOT set the class;
    # the well-supported lineage below it (moderate CLR) drives the verdict instead.
    monkeypatch.setattr(
        R,
        "read_gene_rows",
        lambda t: _rows_support([("Rare thin", 4.5, 1, 5), ("CD8 Naive", 1.0, 8, 500)]),
    )
    s = R.read_sc_surface_normal_safety("CD8A")
    assert s["sc_surface_normal_class"] == "moderate_surface_on_normal_immune"
    assert s["max_surface_cell_type"] == "CD8 Naive"
    assert s["max_surface_n_donors"] == 8 and s["max_surface_n_cells"] == 500
    assert s["n_cell_types_supported"] == 1 and s["n_cell_types_assessed"] == 2


def test_no_cell_type_meets_floor_is_data_unavailable(monkeypatch):
    monkeypatch.setattr(
        R,
        "read_gene_rows",
        lambda t: _rows_support([("Rare thin", 4.5, 1, 5), ("Rare thin 2", 3.0, 2, 8)]),
    )
    s = R.read_sc_surface_normal_safety("CD8A")
    assert s["sc_surface_normal_class"] == "data_unavailable"
    assert "support floor" in s["_data_note"]


def test_well_supported_high_peak_unchanged(monkeypatch):
    # boundary: exactly the floor (3 donors / 10 cells) passes → class is preserved.
    monkeypatch.setattr(R, "read_gene_rows", lambda t: _rows_support([("CD8 Naive", 4.0, 3, 10)]))
    s = R.read_sc_surface_normal_safety("CD8A")
    assert s["sc_surface_normal_class"] == "high_surface_on_normal_immune"


def test_cli_stamps_version(monkeypatch):
    monkeypatch.setattr(R, "read_gene_rows", lambda t: _rows([("CD8 Naive", 0.9, 4.0)]))
    s = C.build_summary("CD8A", indication="NSCLC")
    assert s["method_version"] == C.METHOD_VERSION and s["sc_surface_normal_class"] == "high_surface_on_normal_immune"
