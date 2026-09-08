"""tumor-presence (strength, certainty) sidecar — CERTAINTY_MODEL 5th axis (first no-resolver). Verdict-inert."""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parent.parent, "tp_run_strength")


def _cards(rna_bm=None, n_tumor=None, n_cell=None, sc=None, protein=False):
    c = []
    if n_tumor is not None:
        c.append({"card_id": "tumor-rna-distribution", "summary": {"n_tumor_samples": n_tumor}})
    if n_cell is not None:
        c.append({"card_id": "cellline-rna-distribution", "summary": {"n_cell_lines_evaluated": n_cell}})
    if sc is not None:
        c.append({"card_id": "tumor-scrna-celltype-expression", "summary": {"malignant_n_cells": sc}})
    if protein:
        c.append({"card_id": "tumor-protein-abundance-cptac", "summary": {}})
    if rna_bm is not None:
        c.append({"card_id": "rna-protein-concordance-tumor", "summary": {"rna_as_biomarker": rna_bm}})
    return c


def test_broadly_expressed_rna_protein_concordant_high():
    sc = tp._strength_certainty(
        _cards(rna_bm="adequate_proxy", n_tumor=500, sc=3000), verdict_pair=("tumor_broadly_expressed", "x")
    )
    assert sc["strength"] == "strong_positive"
    assert sc["certainty"]["coverage"] == "high"  # n>=100 AND >=2 layers (rna tumor + sc)
    assert sc["certainty"]["corroboration"] == "high"
    assert sc["certainty"]["level"] == "high"


def test_poor_proxy_disagrees_low():
    sc = tp._strength_certainty(
        _cards(rna_bm="poor_proxy", n_tumor=500, sc=3000), verdict_pair=("tumor_broadly_expressed", "x")
    )
    assert sc["certainty"]["corroboration"] == "low"  # RNA does not predict protein
    assert sc["certainty"]["level"] == "low"


def test_proxy_unmeasured_drops_to_coverage():
    sc = tp._strength_certainty(
        _cards(rna_bm=None, n_cell=50),  # cell-line only, no proxy card
        verdict_pair=("broadly_high_expression", "x"),
    )
    assert sc["certainty"]["corroboration"] == "unmeasured"
    assert sc["certainty"]["level"] == sc["certainty"]["coverage"] == "medium"  # n=50, breadth 1


def test_not_informative_forces_low_none():
    sc = tp._strength_certainty([], verdict_pair=("not_informative", None))
    assert sc["strength"] == "none"
    assert sc["certainty"]["level"] == "low"
