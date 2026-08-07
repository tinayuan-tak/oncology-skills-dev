"""Tests for sc_normal_expression — pure stats + monkeypatched assembler.

Mirrors tests/methods/sc_tumor_expression_celltype/test_stats_and_assembler.py structure:
  - stats primitives tested purely (synthetic Tier-1 DataFrame, no S3);
  - S3 boundary (read_gene_celltype_rows) monkeypatched, never hit;
  - data_unavailable safety branches (no product, gene absent, low donors) asserted;
  - safety-essential cell type flagging asserted.
"""
from __future__ import annotations

import pytest
import pandas as pd

pytest.importorskip("numpy")
pytest.importorskip("pandas")

from methods.sc_normal_expression import stats as S
from methods.sc_normal_expression import read as R
from methods.sc_normal_expression import cli as C


# --- fixtures ----------------------------------------------------------------

def _tier1_rows(spec) -> pd.DataFrame:
    """Build a Tier-1-shaped DataFrame.
    spec: list of (cell_type, n_donors_reliable, median_det, expressing_donor_fraction)
    """
    return pd.DataFrame([
        {
            "gene_symbol": "EPCAM",
            "ensembl_gene_id": "ENSG00000119888",
            "tissue": "colon",
            "cell_type": ct,
            "n_donors_reliable": n,
            "median_det": med,
            "expressing_donor_fraction": frac,
            "n_cell_types_above_20pct": 0,   # placeholder; not tested at this layer
        }
        for (ct, n, med, frac) in spec
    ])


# --- classify_sc_normal_expression: liability ladder -------------------------

def test_classify_high_liability():
    """Any cell type exceeding BOTH thresholds → HIGH_LIABILITY."""
    rows = _tier1_rows([
        ("colonocyte",   20, 0.85, 0.90),   # well above HIGH thresholds
        ("fibroblast",   15, 0.10, 0.20),
    ])
    r = S.classify_sc_normal_expression(rows)
    assert r["sc_normal_expression_class"] == "HIGH_LIABILITY"
    assert r["max_detection_cell_type"] == "colonocyte"
    assert r["max_detection_fraction"] == pytest.approx(0.85)


def test_classify_moderate_liability_by_det():
    """A cell type above MODERATE_LIABILITY_DET (0.20) but below HIGH threshold → MODERATE."""
    rows = _tier1_rows([
        ("enterocyte",   10, 0.35, 0.25),   # med_det > 0.20, frac < 0.30
        ("fibroblast",   10, 0.05, 0.10),
    ])
    r = S.classify_sc_normal_expression(rows)
    assert r["sc_normal_expression_class"] == "MODERATE_LIABILITY"


def test_classify_moderate_liability_by_donor_fraction():
    """A cell type with frac > 0.30 but med_det < 0.20 → MODERATE (OR logic)."""
    rows = _tier1_rows([
        ("plasma cell",  8, 0.15, 0.55),    # frac > 0.30 triggers moderate
        ("fibroblast",  10, 0.04, 0.10),
    ])
    r = S.classify_sc_normal_expression(rows)
    assert r["sc_normal_expression_class"] == "MODERATE_LIABILITY"


def test_classify_low_liability():
    rows = _tier1_rows([
        ("colonocyte",   12, 0.08, 0.15),   # above NOT_EXPRESSED but below MODERATE
        ("fibroblast",   12, 0.03, 0.05),
    ])
    r = S.classify_sc_normal_expression(rows)
    assert r["sc_normal_expression_class"] == "LOW_LIABILITY"


def test_classify_not_expressed():
    """All cell types below NOT_EXPRESSED_CEILING → NOT_EXPRESSED."""
    rows = _tier1_rows([
        ("colonocyte",   20, 0.005, 0.02),
        ("fibroblast",   20, 0.003, 0.01),
    ])
    r = S.classify_sc_normal_expression(rows)
    assert r["sc_normal_expression_class"] == "NOT_EXPRESSED"


def test_classify_data_unavailable_low_donors():
    """All n_donors_reliable < MIN_RELIABLE_DONORS → data_unavailable."""
    rows = _tier1_rows([
        ("colonocyte",  3, 0.90, 0.95),   # very high detection but n_donors < 5
        ("fibroblast",  2, 0.05, 0.10),
    ])
    r = S.classify_sc_normal_expression(rows)
    assert r["sc_normal_expression_class"] == "data_unavailable"
    assert "_data_note" in r


def test_classify_empty_dataframe_is_data_unavailable():
    r = S.classify_sc_normal_expression(pd.DataFrame())
    assert r["sc_normal_expression_class"] == "data_unavailable"


def test_classify_none_is_data_unavailable():
    r = S.classify_sc_normal_expression(None)
    assert r["sc_normal_expression_class"] == "data_unavailable"


# --- safety-essential cell type flagging -------------------------------------

def test_safety_essential_flags_cardiomyocyte():
    rows = _tier1_rows([
        ("cardiomyocyte", 15, 0.40, 0.55),  # above LOW, essential cell type
        ("fibroblast",    15, 0.05, 0.10),
    ])
    r = S.classify_sc_normal_expression(rows)
    assert "cardiomyocyte" in r["safety_essential_flags"]
    assert r["safety_essential_flags"]["cardiomyocyte"] == pytest.approx(0.40)


def test_safety_essential_flags_hepatocyte():
    rows = _tier1_rows([
        ("hepatocyte",   20, 0.30, 0.45),
        ("colonocyte",   20, 0.02, 0.05),
    ])
    r = S.classify_sc_normal_expression(rows)
    assert "hepatocyte" in r["safety_essential_flags"]


def test_safety_essential_flags_empty_when_no_essential():
    rows = _tier1_rows([
        ("fibroblast",   15, 0.05, 0.10),
        ("B cell",       15, 0.03, 0.08),
    ])
    r = S.classify_sc_normal_expression(rows)
    assert r["safety_essential_flags"] == {}


# --- n_cell_types_above_20pct from classify ----------------------------------

def test_n_cell_types_above_20pct_count():
    rows = _tier1_rows([
        ("colonocyte",   10, 0.55, 0.70),   # > 0.20
        ("enterocyte",   10, 0.35, 0.40),   # > 0.20
        ("fibroblast",   10, 0.08, 0.15),   # <= 0.20
    ])
    r = S.classify_sc_normal_expression(rows)
    assert r["n_cell_types_above_20pct"] == 2


# --- read.py with monkeypatched S3 -------------------------------------------

def test_read_target_summary_full_path(monkeypatch):
    rows = _tier1_rows([
        ("colonocyte",   20, 0.85, 0.90),
        ("fibroblast",   15, 0.10, 0.20),
    ])
    monkeypatch.setattr(R, "read_gene_celltype_rows", lambda t, ts: rows)
    out = R.read_target_summary("EPCAM", "COADREAD")
    assert out["sc_normal_expression_class"] == "HIGH_LIABILITY"
    assert out["indication"] == "COADREAD"
    assert out["tissues_queried"] == ["colon"]


def test_read_target_summary_unknown_indication():
    out = R.read_target_summary("EPCAM", "UNKNOWN_IND")
    assert out["sc_normal_expression_class"] == "data_unavailable"
    assert "_data_note" in out


def test_read_target_summary_no_product(monkeypatch):
    """read_gene_celltype_rows returns None → data_unavailable."""
    monkeypatch.setattr(R, "read_gene_celltype_rows", lambda t, ts: None)
    out = R.read_target_summary("EPCAM", "COADREAD")
    assert out["sc_normal_expression_class"] == "data_unavailable"
    assert "_data_note" in out


def test_read_target_summary_gene_absent(monkeypatch):
    """Empty DataFrame (gene not in product) → data_unavailable, 'absent' note."""
    monkeypatch.setattr(R, "read_gene_celltype_rows",
                        lambda t, ts: pd.DataFrame())
    out = R.read_target_summary("MADEUPGENE99", "COADREAD")
    assert out["sc_normal_expression_class"] == "data_unavailable"
    assert "absent" in out.get("_data_note", "")


def test_indication_tissue_map_covers_v1_scope():
    """v1 scope: COADREAD→colon, NSCLC→lung. Others (PAAD, STAD) must not resolve."""
    assert R.INDICATION_TO_TISSUES.get("COADREAD") == ["colon"]
    assert R.INDICATION_TO_TISSUES.get("NSCLC") == ["lung"]
    assert R.INDICATION_TO_TISSUES.get("LUAD") == ["lung"]
    assert R.INDICATION_TO_TISSUES.get("PAAD") is None
    assert R.INDICATION_TO_TISSUES.get("STAD") is None


# --- cli build_summary -------------------------------------------------------

def test_cli_build_summary_adds_method_version(monkeypatch):
    monkeypatch.setattr(R, "read_gene_celltype_rows", lambda t, ts: None)
    out = C.build_summary("EPCAM", "PAAD")
    assert out["method_version"] == C.METHOD_VERSION
    assert out["sc_normal_expression_class"] == "data_unavailable"
