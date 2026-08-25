"""Hermetic (credential-less) tests for the myeloid_compartment per-gene reader.

Monkeypatches the S3 read (`_read_gene_rows`) so the summariser + absence discipline run offline —
no boto3/pyarrow/network. VERDICT-INERT display reader; pins the per-gene myeloid-state shape, the
detection-fraction class thresholds, the CSF1R-family flag, and both data_unavailable paths.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]   # repo root of THIS checkout (worktree-safe)
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from methods.myeloid_compartment import read as R  # noqa: E402


def _df(rows):
    return pd.DataFrame(rows, columns=["gene_symbol", "myeloid_subtype", "cancer_type",
                                       "n_cells", "detection_fraction", "abundance_log1p_cp10k"])


def test_summary_shape_and_class_broadly_detected(monkeypatch):
    df = _df([
        ["CSF1R", "M06_Macro_ISG15", "PAAD", 120, 0.72, 1.90],
        ["CSF1R", "M01_Mono_CD14",   "ESCA", 80,  0.31, 0.80],
        ["CSF1R", "M03_cDC2",        "THCA", 40,  0.05, 0.10],
    ])
    monkeypatch.setattr(R, "_read_gene_rows", lambda target: df)
    out = R.read_target_summary("CSF1R", indication="PAAD")
    assert out["myeloid_expression_class"] == "myeloid_broadly_detected"
    assert out["max_detection_fraction"] == 0.72
    assert out["max_detection_myeloid_subtype"] == "M06_Macro_ISG15"
    assert out["max_detection_cancer_type"] == "PAAD"
    assert out["n_myeloid_groups_measured"] == 3
    # expressing (detection >= 0.25): the ISG15 macro + the CD14 mono → 2 subtypes, 2 cancer types
    assert out["n_myeloid_subtypes_expressing"] == 2
    assert out["expressing_myeloid_subtypes"] == ["M01_Mono_CD14", "M06_Macro_ISG15"]
    assert out["n_cancer_types_expressing"] == 2
    assert out["max_abundance_log1p_cp10k"] == 1.90
    # CSF1R is a canonical myeloid-target antigen
    assert out["myeloid_target_family_flag"] is True
    assert out["product_id"] == R.MANIFEST_ID
    assert out["indication"] == "PAAD"
    # exact key set (verdict-inert display contract; underscore keys excluded)
    assert {k for k in out if not k.startswith("_")} == {
        "myeloid_expression_class", "max_detection_fraction", "max_detection_myeloid_subtype",
        "max_detection_cancer_type", "median_detection_fraction", "max_abundance_log1p_cp10k",
        "n_myeloid_subtypes_expressing", "n_myeloid_groups_measured", "n_cancer_types_expressing",
        "expressing_myeloid_subtypes", "myeloid_target_family_flag", "indication", "product_id"}


def test_class_subset_detected(monkeypatch):
    df = _df([["ERBB2", "M01_Mono_CD14", "ESCA", 60, 0.22, 0.5]])
    monkeypatch.setattr(R, "_read_gene_rows", lambda target: df)
    out = R.read_target_summary("ERBB2")
    assert out["myeloid_expression_class"] == "myeloid_subset_detected"
    assert out["myeloid_target_family_flag"] is False
    assert out["indication"] is None


def test_class_low(monkeypatch):
    df = _df([["FOO1", "M01_Mono_CD14", "ESCA", 60, 0.03, 0.1]])
    monkeypatch.setattr(R, "_read_gene_rows", lambda target: df)
    out = R.read_target_summary("FOO1")
    assert out["myeloid_expression_class"] == "myeloid_low"
    assert out["n_myeloid_subtypes_expressing"] == 0


def test_gene_absent_is_data_unavailable(monkeypatch):
    monkeypatch.setattr(R, "_read_gene_rows", lambda target: _df([]))
    out = R.read_target_summary("TREM2", indication="PAAD")
    assert out["myeloid_expression_class"] == "data_unavailable"
    assert out["myeloid_target_family_flag"] is True   # still flagged (family membership is intrinsic)
    assert "absent" in out["_data_note"]


def test_no_product_is_data_unavailable(monkeypatch):
    monkeypatch.setattr(R, "_read_gene_rows", lambda target: None)
    out = R.read_target_summary("CSF1R")
    assert out["myeloid_expression_class"] == "data_unavailable"
    assert out["product_id"] == R.MANIFEST_ID
