"""Tests for the sc_surface_concordance method — surfaces precomputed rna_as_biomarker from
sc-cite-rna-protein-concordance-v1. No S3: the parquet reader (read_gene_rows) is monkeypatched."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

pd = pytest.importorskip("pandas")

from methods.sc_surface_concordance import read as R  # noqa: E402
from methods.sc_surface_concordance import cli as C  # noqa: E402


def _row(gene, pear, spear, cls, n_cells=5000, ds="hao-2021-pbmc-3p"):
    return {
        "dataset_id": ds,
        "gene_symbol": gene,
        "hgnc_id": "HGNC:1706",
        "adt_proteins": "CD8",
        "n_cell_types": 31,
        "n_cells": n_cells,
        "pearson_r_rna_vs_adt": pear,
        "spearman_r_rna_vs_adt": spear,
        "rna_as_biomarker": cls,
        "compartment_scope": "immune_pbmc",
        "matched_via": "cd_crosswalk",
    }


@pytest.mark.parametrize(
    "cls,pear",
    [
        ("adequate_proxy", 0.98),
        ("partial_proxy", 0.45),
        ("poor_proxy", -0.20),
    ],
)
def test_bands_surface_precomputed(monkeypatch, cls, pear):
    monkeypatch.setattr(R, "read_gene_rows", lambda t: pd.DataFrame([_row(t, pear, 0.5, cls)]))
    s = R.read_sc_surface_concordance("CD8A")
    assert s["rna_as_biomarker"] == cls
    assert s["rna_protein_r"] == round(pear, 4)
    assert s["measurement_type"] == "rna_protein_concordance"
    assert s["substrate"] == "cite_seq_surface"
    assert s["compartment_scope"] == "immune_pbmc"


def test_product_missing_is_data_unavailable(monkeypatch):
    monkeypatch.setattr(R, "read_gene_rows", lambda t: None)  # product not on S3
    s = R.read_sc_surface_concordance("CD8A")
    assert s["rna_as_biomarker"] == "data_unavailable"
    assert "coverage gap" in s["_data_note"]


def test_gene_absent_is_data_unavailable_not_pass(monkeypatch):
    monkeypatch.setattr(R, "read_gene_rows", lambda t: pd.DataFrame(columns=R._PARQUET_COLS))  # gene absent
    s = R.read_sc_surface_concordance("KRAS")
    assert s["rna_as_biomarker"] == "data_unavailable"
    assert "not in the CITE-seq surface panel" in s["_data_note"]


def test_multi_dataset_picks_best_powered_and_reports_all(monkeypatch):
    rows = pd.DataFrame(
        [
            _row("CD8A", 0.9, 0.7, "adequate_proxy", n_cells=1000, ds="ds_small"),
            _row("CD8A", 0.6, 0.6, "adequate_proxy", n_cells=9000, ds="ds_big"),
        ]
    )
    monkeypatch.setattr(R, "read_gene_rows", lambda t: rows)
    s = R.read_sc_surface_concordance("CD8A")
    assert s["dataset_id"] == "ds_big"  # best-powered row chosen
    assert s["datasets"] == ["ds_big", "ds_small"]  # all reported


def test_cli_build_summary_stamps_version(monkeypatch):
    monkeypatch.setattr(R, "read_gene_rows", lambda t: pd.DataFrame([_row(t, 0.98, 0.8, "adequate_proxy")]))
    s = C.build_summary("CD8A", indication="NSCLC")  # indication accepted, not consumed
    assert s["method_version"] == C.METHOD_VERSION
    assert s["rna_as_biomarker"] == "adequate_proxy"
