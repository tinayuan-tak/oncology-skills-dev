"""Tests for sc_surface_normal_safety — normal-immune surface-protein liability ladder. No S3:
read_gene_rows is monkeypatched."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

pd = pytest.importorskip("pandas")

from methods.sc_surface_normal_safety import read as R  # noqa: E402
from methods.sc_surface_normal_safety import cli as C  # noqa: E402


def _rows(pairs):
    # pairs: list of (cell_type, positive_fraction, mean_clr)
    return pd.DataFrame([{"gene_symbol": "CD8A", "hgnc_id": "HGNC:1706", "adt_proteins": "CD8",
                          "cell_type": ct, "compartment_scope": "immune_pbmc", "n_cells": 500,
                          "n_donors": 8, "adt_mean_clr_median": clr,
                          "adt_positive_fraction_median": pf} for ct, pf, clr in pairs])


@pytest.mark.parametrize("peak_clr,expected", [
    (4.0, "high_surface_on_normal_immune"),
    (1.0, "moderate_surface_on_normal_immune"),
    (0.2, "low_surface_on_normal_immune"),
    (-0.5, "not_surface_detected_normal_immune"),
])
def test_liability_ladder(monkeypatch, peak_clr, expected):
    # classifier keys on PEAK mean-CLR, not positive_fraction (ambient-background overcall)
    monkeypatch.setattr(R, "read_gene_rows",
                        lambda t: _rows([("CD8 Naive", 0.9, peak_clr), ("B naive", 0.9, -1.5)]))
    s = R.read_sc_surface_normal_safety("CD8A")
    assert s["sc_surface_normal_class"] == expected
    assert s["max_surface_cell_type"] == "CD8 Naive"       # highest mean-CLR lineage
    assert s["max_mean_clr"] == round(peak_clr, 4)


def test_breadth_count_uses_clr_not_posfrac(monkeypatch):
    # B naive has HIGH positive_fraction (0.9) but LOW mean-CLR (-1.0 = spillover) → must NOT count.
    monkeypatch.setattr(R, "read_gene_rows",
                        lambda t: _rows([("CD8 Naive", 0.9, 4.0), ("CD8 TEM", 0.9, 3.9),
                                         ("B naive", 0.9, -1.0)]))
    s = R.read_sc_surface_normal_safety("CD8A")
    assert s["n_celltypes_surface_displaying"] == 2        # only the 2 T lineages clear the CLR floor


def test_product_missing_vs_gene_absent(monkeypatch):
    monkeypatch.setattr(R, "read_gene_rows", lambda t: None)
    assert R.read_sc_surface_normal_safety("CD8A")["sc_surface_normal_class"] == "data_unavailable"
    monkeypatch.setattr(R, "read_gene_rows", lambda t: pd.DataFrame(columns=R._PARQUET_COLS))
    s = R.read_sc_surface_normal_safety("KRAS")
    assert s["sc_surface_normal_class"] == "data_unavailable"
    assert "not surface-profiled" in s["_data_note"]


def test_cli_stamps_version(monkeypatch):
    monkeypatch.setattr(R, "read_gene_rows", lambda t: _rows([("CD8 Naive", 0.9, 4.0)]))
    s = C.build_summary("CD8A", indication="NSCLC")
    assert s["method_version"] == C.METHOD_VERSION and s["sc_surface_normal_class"] == "high_surface_on_normal_immune"
