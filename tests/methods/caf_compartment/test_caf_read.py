"""Hermetic (credential-less) tests for the caf_compartment per-gene reader.

Monkeypatches the S3 read (`_read_gene_rows`) so the summariser + absence discipline run offline.
VERDICT-INERT display reader; pins the per-gene CAF-state shape, class thresholds, and both
data_unavailable paths.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from methods.caf_compartment import read as R  # noqa: E402


def _df(rows):
    return pd.DataFrame(rows, columns=["gene_symbol", "caf_subtype", "cancer_type",
                                       "n_cells", "detection_fraction", "abundance_log1p_cp10k"])


def test_summary_shape_and_class_broadly_detected(monkeypatch):
    df = _df([
        ["FAP", "CAFinfla", "PDAC",   200, 0.52, 1.40],
        ["FAP", "CAFadi",   "breast", 90,  0.40, 1.10],
        ["FAP", "CAFmyo",   "lung",   150, 0.06, 0.20],
    ])
    monkeypatch.setattr(R, "_read_gene_rows", lambda target: df)
    out = R.read_target_summary("FAP", indication="PAAD")
    assert out["caf_expression_class"] == "caf_broadly_detected"
    assert out["max_detection_fraction"] == 0.52
    assert out["max_detection_caf_subtype"] == "CAFinfla"
    assert out["max_detection_cancer_type"] == "PDAC"
    assert out["n_caf_groups_measured"] == 3
    assert out["n_caf_subtypes_expressing"] == 2                 # CAFinfla + CAFadi >= 0.25
    assert out["expressing_caf_subtypes"] == ["CAFadi", "CAFinfla"]
    assert out["n_cancer_types_expressing"] == 2
    assert out["product_id"] == R.MANIFEST_ID
    assert out["indication"] == "PAAD"
    assert {k for k in out if not k.startswith("_")} == {
        "caf_expression_class", "max_detection_fraction", "max_detection_caf_subtype",
        "max_detection_cancer_type", "median_detection_fraction", "max_abundance_log1p_cp10k",
        "n_caf_subtypes_expressing", "n_caf_groups_measured", "n_cancer_types_expressing",
        "expressing_caf_subtypes", "indication", "product_id"}


def test_class_subset_and_low(monkeypatch):
    monkeypatch.setattr(R, "_read_gene_rows", lambda target: _df([["X", "CAFmyo", "lung", 50, 0.18, 0.4]]))
    assert R.read_target_summary("X")["caf_expression_class"] == "caf_subset_detected"
    monkeypatch.setattr(R, "_read_gene_rows", lambda target: _df([["X", "CAFmyo", "lung", 50, 0.02, 0.1]]))
    assert R.read_target_summary("X")["caf_expression_class"] == "caf_low"


def test_gene_absent_is_data_unavailable(monkeypatch):
    monkeypatch.setattr(R, "_read_gene_rows", lambda target: _df([]))
    out = R.read_target_summary("PDGFRB", indication="PAAD")
    assert out["caf_expression_class"] == "data_unavailable"
    assert "absent" in out["_data_note"]


def test_no_product_is_data_unavailable(monkeypatch):
    monkeypatch.setattr(R, "_read_gene_rows", lambda target: None)
    out = R.read_target_summary("ACTA2")
    assert out["caf_expression_class"] == "data_unavailable"
    assert out["product_id"] == R.MANIFEST_ID
