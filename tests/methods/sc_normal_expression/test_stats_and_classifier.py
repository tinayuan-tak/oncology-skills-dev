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
    New schema columns (n_datasets_reliable, q25_abund, q25_det) filled with sensible defaults.
    """
    return pd.DataFrame([
        {
            "gene_symbol": "EPCAM",
            "ensembl_gene_id": "ENSG00000119888",
            "tissue": "colon",
            "cell_type": ct,
            "n_donors_total": n,
            "n_donors_reliable": n,
            "n_datasets_reliable": max(1, n // 5),  # reasonable default: ~1 dataset per 5 donors
            "n_donors_expressing": max(0, n - 2),
            "median_det": med,
            "q25_det": med * 0.7,
            "q75_det": med * 1.3,
            "expressing_donor_fraction": frac,
            "median_abund": med * 3.0,
            "q25_abund": med * 2.0,
            "q75_abund": med * 4.0,
            "detection_pct_rank": 0.5,
            "n_cell_types_above_20pct": 0,
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


def test_classify_high_liability_reports_triggering_cell_not_global_argmax():
    """The cell type with highest raw detection may not be the one that fired HIGH_LIABILITY.
    When Cell A has det=0.85 (fails AND: frac=0.40 < 0.70) and Cell B has det=0.55 (passes AND:
    frac=0.80 > 0.70), HIGH fires and max_detection_cell_type must be Cell B, not Cell A."""
    rows = _tier1_rows([
        ("fibroblast",   20, 0.85, 0.40),   # highest det but fails AND (frac below threshold)
        ("colonocyte",   20, 0.55, 0.80),   # lower det but BOTH thresholds met → fires HIGH
    ])
    r = S.classify_sc_normal_expression(rows)
    assert r["sc_normal_expression_class"] == "HIGH_LIABILITY"
    assert r["max_detection_cell_type"] == "colonocyte"   # the triggering cell, not the argmax
    assert r["max_detection_fraction"] == pytest.approx(0.55)


def test_safety_essential_flags_excludes_near_zero_values():
    """Entries with median_det <= 0.05 (census annotation noise) must NOT appear in safety flags."""
    rows = _tier1_rows([
        ("hepatocyte",   10, 0.03, 0.10),   # essential but below noise floor — must be excluded
        ("fibroblast",   10, 0.50, 0.60),
    ])
    r = S.classify_sc_normal_expression(rows)
    assert "hepatocyte" not in r["safety_essential_flags"]


def test_safety_essential_flags_includes_above_floor():
    """Entries above the 0.05 floor in safety-essential cell types must appear in flags."""
    rows = _tier1_rows([
        ("hepatocyte",   10, 0.08, 0.20),   # above 0.05 floor
        ("fibroblast",   10, 0.05, 0.10),
    ])
    r = S.classify_sc_normal_expression(rows)
    assert "hepatocyte" in r["safety_essential_flags"]
    assert r["safety_essential_flags"]["hepatocyte"] == pytest.approx(0.08)


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
    # COADREAD now queries the matched tissue (colon) UNION the always-on safety-essential tissues
    assert out["tissues_queried"] == ["colon", "heart", "liver", "kidney", "bone_marrow"]


def test_read_target_summary_unknown_indication_still_reads_safety_essential(monkeypatch):
    """Unknown indication no longer abstains-by-mapping: it queries the safety-essential tissues
    (cross-tissue on-target-tox check). With a real product it would classify; here the reader is
    monkeypatched to None (no product) → data_unavailable, but tissues_queried is non-empty."""
    monkeypatch.setattr(R, "read_gene_celltype_rows", lambda t, ts: None)
    out = R.read_target_summary("EPCAM", "UNKNOWN_IND")
    assert out["sc_normal_expression_class"] == "data_unavailable"
    assert out["tissues_queried"] == ["heart", "liver", "kidney", "bone_marrow"]
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


def test_tissues_for_indication_unions_matched_and_safety_essential():
    """tumor-matched tissue(s) UNION the always-on safety-essential tissues, de-duplicated."""
    # COADREAD → colon + safety-essential
    assert R.tissues_for_indication("COADREAD") == ["colon", "heart", "liver", "kidney", "bone_marrow"]
    assert R.tissues_for_indication("NSCLC") == ["lung", "heart", "liver", "kidney", "bone_marrow"]
    # Unknown indication → safety-essential only (never empty)
    assert R.tissues_for_indication("PAAD") == ["heart", "liver", "kidney", "bone_marrow"]
    assert R.tissues_for_indication("UNKNOWN") == ["heart", "liver", "kidney", "bone_marrow"]


def test_all_nine_tissues_have_tier1_products():
    """All 9 emitted tissues route to a Tier-1 product key (hyphenated slugs for multi-word)."""
    for t in ["colon", "lung", "heart", "liver", "kidney", "stomach",
              "bone_marrow", "skin", "small_intestine"]:
        assert t in R.TISSUE_TO_PRODUCT, f"{t} missing from TISSUE_TO_PRODUCT"
    assert R.TISSUE_TO_PRODUCT["bone_marrow"] == "sc-normal-celltype-expression-bone-marrow-v1"
    assert R.TISSUE_TO_PRODUCT["small_intestine"] == "sc-normal-celltype-expression-small-intestine-v1"


# --- cli build_summary -------------------------------------------------------

def test_cli_build_summary_adds_method_version(monkeypatch):
    monkeypatch.setattr(R, "read_gene_celltype_rows", lambda t, ts: None)
    out = C.build_summary("EPCAM", "PAAD")
    assert out["method_version"] == C.METHOD_VERSION
    assert out["sc_normal_expression_class"] == "data_unavailable"
