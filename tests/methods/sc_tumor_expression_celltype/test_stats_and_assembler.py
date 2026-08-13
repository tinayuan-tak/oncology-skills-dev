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
    assert cs["malignant"]["n_datasets"] == 2
    # median of {0.9, 0.1} == 0.5 — the giant donor did not dominate
    assert cs["malignant"]["median_detection_fraction"] == pytest.approx(0.5)
    assert cs["malignant"]["n_cells_total"] == 500_100


def test_compartment_summary_n_datasets_collapses_same_dataset():
    """Multiple donors from the same dataset_id must count as 1 dataset, not N donors."""
    rows = _rows([
        ("malignant", "dsA", "d1", 200, 0.7, 2.0),   # both from dsA
        ("malignant", "dsA", "d2", 200, 0.5, 1.5),
        ("malignant", "dsB", "d3", 200, 0.3, 1.0),   # one from dsB
    ])
    cs = S.compartment_summary(rows)
    assert cs["malignant"]["n_donors"] == 3
    assert cs["malignant"]["n_datasets"] == 2   # dsA + dsB, not 3


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


# --- v1 sc-presence depth: full per-compartment vector + CAF readout ---------

def test_per_compartment_vector_orders_and_flags_caf():
    """The full vector: malignant first, canonical order, stromal flagged is_caf."""
    rows = _rows([
        ("stromal", "dsA", "d1", 100, 0.30, 0.4),
        ("malignant", "dsA", "d1", 100, 0.60, 1.0),
        ("immune", "dsA", "d1", 100, 0.05, 0.1),
    ])
    cs = S.compartment_summary(rows)
    vec = S.per_compartment_vector(cs)
    # malignant first (anchor), stromal second (canonical order), immune third
    assert [v["compartment"] for v in vec] == ["malignant", "stromal", "immune"]
    caf = [v for v in vec if v["is_caf"]]
    assert len(caf) == 1 and caf[0]["compartment"] == "stromal"
    assert vec[0]["median_detection_fraction"] == pytest.approx(0.60)


def test_per_compartment_vector_empty_is_empty_list():
    assert S.per_compartment_vector({}) == []


def test_caf_readout_shared_when_both_detect():
    """CAF + malignant both detect within 0.15 → shared_caf_malignant (a dual-compartment target)."""
    rows = _rows([
        ("malignant", "dsA", "d1", 100, 0.40, 1.0),
        ("stromal",   "dsA", "d1", 100, 0.35, 0.9),
    ])
    r = S.caf_readout(S.compartment_summary(rows))
    assert r["caf_compartment_available"] is True
    assert r["caf_vs_malignant_class"] == "shared_caf_malignant"


def test_caf_readout_caf_dominant_and_low():
    # CAF-dominant: stromal clears microenv_min and clearly exceeds malignant
    rows_dom = _rows([("malignant","d","1",100,0.05,0.1),("stromal","d","1",100,0.50,1.0)])
    assert S.caf_readout(S.compartment_summary(rows_dom))["caf_vs_malignant_class"] == "caf_dominant"
    # CAF-low: stromal below microenv_min → not a CAF target
    rows_low = _rows([("malignant","d","1",100,0.60,1.0),("stromal","d","1",100,0.10,0.2)])
    assert S.caf_readout(S.compartment_summary(rows_low))["caf_vs_malignant_class"] == "caf_low"


def test_caf_readout_no_stromal_is_data_unavailable():
    """No stromal compartment measured → abstain, never a fabricated zero."""
    rows = _rows([("malignant", "d", "1", 100, 0.6, 1.0)])
    r = S.caf_readout(S.compartment_summary(rows))
    assert r["caf_compartment_available"] is False
    assert r["caf_vs_malignant_class"] == "data_unavailable"


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
    assert out["product_id"] == "sc-pseudobulk-tumor-crc-coadread-v1"  # 2026-08-13: repointed to the CRC core atlas (explicit malignant call)


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
    """Census landed scope: COADREAD + NSCLC + LUSC (+ their sub-codes). 3CA extends to PAAD +
    HNSC (2026-08-12). STAD must NOT resolve — no 3CA gastric bucket + Census labels gastric
    tumor cells 'unknown'. LUSC resolves its DEDICATED squamous cube (see test_lusc_wiring.py)."""
    assert R._product_key("COADREAD") is not None
    assert R._product_key("NSCLC") is not None
    assert R._product_key("LUAD") is not None
    assert R._product_key("LUSC") is not None
    # LUSC maps to its DEDICATED cube, not the NSCLC umbrella.
    assert R.INDICATION_TO_PRODUCT["LUSC"] == "sc-pseudobulk-donor-celltype-lusc-v1"
    assert R.INDICATION_TO_PRODUCT["LUSC"] != R.INDICATION_TO_PRODUCT["NSCLC"]
    # 3CA-backed indications added 2026-08-12
    assert R.INDICATION_TO_PRODUCT["PAAD"] == "sc-pseudobulk-tumor-3ca-pancreas-v1"
    assert R.INDICATION_TO_PRODUCT["HNSC"] == "sc-pseudobulk-tumor-3ca-hnsc-v1"
    # STAD has no 3CA bucket — must remain data_unavailable
    assert R._product_key("STAD") is None


def test_cli_build_summary_adds_method_version(monkeypatch):
    monkeypatch.setattr(R, "read_gene_compartment_rows", lambda t, i: None)
    out = C.build_summary("EPCAM", "PAAD")
    assert out["method_version"] == C.METHOD_VERSION
    assert out["sc_expression_class"] == "data_unavailable"


# --- classify_tce_homogeneity: the biologics within-tumor homogeneity lens (Phase 3.2) ----------
# A DISTINCT read of malignant_detection_fraction from sc_expression_class: for a TCE, antigen
# heterogeneity is an escape-reservoir program-killer. The 0.25 heterogeneity cut is a deliberate
# design call — the 0.25-0.5 band is neutral (moderately_homogeneous), not opposing.

def test_tce_homogeneous_when_broadly_detected():
    assert S.classify_tce_homogeneity(0.7, True) == "homogeneous"
    assert S.classify_tce_homogeneity(S.TCE_HOMOGENEOUS_MIN, True) == "homogeneous"   # 0.5 inclusive


def test_tce_moderately_homogeneous_is_the_neutral_band():
    # 0.25 <= detection < 0.5 — a real expressing subset, but NOT penalized (the stricter-cut call)
    assert S.classify_tce_homogeneity(0.4, True) == "moderately_homogeneous"
    assert S.classify_tce_homogeneity(S.TCE_HETEROGENEOUS_MAX, True) == "moderately_homogeneous"  # 0.25 inclusive
    assert S.classify_tce_homogeneity(0.49, True) == "moderately_homogeneous"


def test_tce_heterogeneous_below_the_strict_cut():
    # < 0.25 with a malignant compartment present — antigen-low escape reservoir
    assert S.classify_tce_homogeneity(0.24, True) == "heterogeneous"
    assert S.classify_tce_homogeneity(0.02, True) == "heterogeneous"


def test_tce_homogeneity_data_unavailable_abstains_not_zero():
    # no malignant compartment / no detection → data_unavailable (abstain), NEVER coerced to heterogeneous
    assert S.classify_tce_homogeneity(None, False) == "data_unavailable"
    assert S.classify_tce_homogeneity(None, True) == "data_unavailable"
    assert S.classify_tce_homogeneity(0.8, False) == "data_unavailable"   # compartment flag governs


# --- classify_sc_expression emits tce_homogeneity_class alongside the presence class ----
def test_sc_expression_also_emits_tce_homogeneity_broadly():
    cs = {"malignant": {"n_donors": 5, "n_cells_total": 1000,
                        "median_detection_fraction": 0.7, "median_abundance_log1p_cp10k": 3.0}}
    r = S.classify_sc_expression(cs)
    assert r["sc_expression_class"] == "malignant_broadly_detected"
    assert r["tce_homogeneity_class"] == "homogeneous"


def test_sc_expression_subset_maps_to_heterogeneous_or_moderate_by_the_strict_cut():
    # malignant_subset_detected spans 0.1-0.5; the TCE lens splits it at 0.25.
    lo = {"malignant": {"n_donors": 5, "n_cells_total": 1000,
                        "median_detection_fraction": 0.15, "median_abundance_log1p_cp10k": 1.0}}
    hi = {"malignant": {"n_donors": 5, "n_cells_total": 1000,
                        "median_detection_fraction": 0.35, "median_abundance_log1p_cp10k": 1.0}}
    r_lo = S.classify_sc_expression(lo)
    r_hi = S.classify_sc_expression(hi)
    assert r_lo["sc_expression_class"] == "malignant_subset_detected"   # presence class SAME for both
    assert r_hi["sc_expression_class"] == "malignant_subset_detected"
    assert r_lo["tce_homogeneity_class"] == "heterogeneous"             # but TCE lens SPLITS them
    assert r_hi["tce_homogeneity_class"] == "moderately_homogeneous"


def test_sc_expression_empty_and_no_malignant_emit_data_unavailable_homogeneity():
    assert S.classify_sc_expression({})["tce_homogeneity_class"] == "data_unavailable"
    cs = {"immune": {"n_donors": 8, "n_cells_total": 4000,
                     "median_detection_fraction": 0.6, "median_abundance_log1p_cp10k": 2.5}}
    assert S.classify_sc_expression(cs)["tce_homogeneity_class"] == "data_unavailable"


def test_assembler_surfaces_tce_homogeneity_class(monkeypatch):
    import pandas as pd
    rows = pd.DataFrame(_rows([
        ("malignant", "dsA", "d1", 300, 0.8, 3.1),
        ("malignant", "dsB", "d2", 250, 0.6, 2.8),
    ]))
    monkeypatch.setattr(R, "read_gene_compartment_rows", lambda t, i: rows)
    out = R.read_sc_expression_presence("EPCAM", "COADREAD")
    assert out["tce_homogeneity_class"] == "homogeneous"


def test_assembler_data_unavailable_carries_homogeneity(monkeypatch):
    monkeypatch.setattr(R, "read_gene_compartment_rows", lambda t, i: None)
    out = R.read_sc_expression_presence("EPCAM", "PAAD")
    assert out["tce_homogeneity_class"] == "data_unavailable"
