"""Synthetic-data tests for depmap_predictability v2 thin lookup.

Writes a v2 parquet to tmp_path, points cli helpers at it, verifies:
  - per-target row lookup + summary mapping
  - missing target → data_unavailable graceful path
  - feature-importance bar SVG renders
  - lineage-conditional panel SVG renders
  - read.py shim maps release_pin correctly
"""

from __future__ import annotations

import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from depmap_predictability import cli as e5cli  # noqa: E402
from depmap_predictability import read as e5read  # noqa: E402


def _make_v2_parquet(out_path: Path):
    """Build a small v2 parquet matching production schema."""
    top_struct = pa.struct([
        pa.field("feature", pa.string()),
        pa.field("feature_class", pa.string()),
        pa.field("importance", pa.float32()),
        pa.field("rf_importance", pa.float32()),
    ])
    lineage_struct = pa.struct([
        pa.field("lineage", pa.string()),
        pa.field("n_cell_lines", pa.int32()),
        pa.field("r2", pa.float32()),
        pa.field("top_feature", pa.string()),
    ])
    schema = pa.schema([
        pa.field("gene_symbol", pa.string()),
        pa.field("n_cell_lines_evaluated", pa.int32()),
        pa.field("pearson_r_rf", pa.float32()),
        pa.field("pearson_r_squared_rf", pa.float32()),
        pa.field("pearson_r_squared_rf_ci_lo", pa.float32()),
        pa.field("pearson_r_squared_rf_ci_hi", pa.float32()),
        pa.field("pearson_r_xgb", pa.float32()),
        pa.field("pearson_r_squared_xgb", pa.float32()),
        pa.field("pearson_r_squared_xgb_ci_lo", pa.float32()),
        pa.field("pearson_r_squared_xgb_ci_hi", pa.float32()),
        pa.field("model_agreement", pa.string()),
        pa.field("delta_r2", pa.float32()),
        pa.field("top_features_rf_shap", pa.list_(top_struct)),
        pa.field("top_features_xgb_shap", pa.list_(top_struct)),
        pa.field("dominant_feature_class", pa.string()),
        pa.field("predictability_class", pa.string()),
        pa.field("per_lineage_predictability", pa.list_(lineage_struct)),
    ])
    rows = {
        "gene_symbol": ["BRAF", "KRAS", "TP53"],
        "n_cell_lines_evaluated": [1180, 1250, 1300],
        "pearson_r_rf": [0.78, 0.76, 0.42],
        "pearson_r_squared_rf": [0.61, 0.58, 0.18],
        "pearson_r_squared_rf_ci_lo": [0.55, 0.50, 0.12],
        "pearson_r_squared_rf_ci_hi": [0.66, 0.65, 0.24],
        "pearson_r_xgb": [0.80, 0.78, 0.44],
        "pearson_r_squared_xgb": [0.64, 0.61, 0.19],
        "pearson_r_squared_xgb_ci_lo": [0.58, 0.55, 0.13],
        "pearson_r_squared_xgb_ci_hi": [0.69, 0.66, 0.26],
        "model_agreement": ["concordant", "concordant", "concordant"],
        "delta_r2": [-0.03, -0.03, -0.01],
        "top_features_rf_shap": [
            [{"feature": "own_mut_hotspot", "feature_class": "own_mut_hotspot",
              "importance": 0.51, "rf_importance": 0.42},
             {"feature": "lineage_Skin", "feature_class": "lineage",
              "importance": 0.18, "rf_importance": 0.09}],
            [{"feature": "own_mut_hotspot", "feature_class": "own_mut_hotspot",
              "importance": 0.42, "rf_importance": 0.38},
             {"feature": "lineage_Bowel", "feature_class": "lineage",
              "importance": 0.20, "rf_importance": 0.10}],
            [{"feature": "own_mut_damaging", "feature_class": "own_mut_damaging",
              "importance": 0.08, "rf_importance": 0.07}],
        ],
        "top_features_xgb_shap": [
            [{"feature": "own_mut_hotspot", "feature_class": "own_mut_hotspot",
              "importance": 0.52, "rf_importance": 0.0}],
            [{"feature": "own_mut_hotspot", "feature_class": "own_mut_hotspot",
              "importance": 0.44, "rf_importance": 0.0}],
            [{"feature": "own_mut_damaging", "feature_class": "own_mut_damaging",
              "importance": 0.09, "rf_importance": 0.0}],
        ],
        "dominant_feature_class": ["own_mut_hotspot", "own_mut_hotspot", "unpredictable"],
        "predictability_class": ["own_omics_driven", "own_omics_driven", "unpredictable"],
        "per_lineage_predictability": [
            [{"lineage": "Skin", "n_cell_lines": 60, "r2": 0.72,
              "top_feature": "own_mut_hotspot"}],
            [{"lineage": "Bowel", "n_cell_lines": 80, "r2": 0.65,
              "top_feature": "own_mut_hotspot"},
             {"lineage": "Pancreas", "n_cell_lines": 45, "r2": 0.60,
              "top_feature": "own_mut_hotspot"}],
            [],
        ],
    }
    table = pa.Table.from_pydict(rows, schema=schema)
    pq.write_table(table, out_path, row_group_size=64)


def test_fetch_predictability_row_hit(tmp_path):
    p = tmp_path / "predictability.parquet"
    _make_v2_parquet(p)
    row = e5cli.fetch_predictability_row(str(p), "KRAS")
    assert row is not None
    assert row["gene_symbol"] == "KRAS"
    assert row["predictability_class"] == "own_omics_driven"
    assert row["top_features_rf_shap"][0]["feature"] == "own_mut_hotspot"


def test_fetch_predictability_row_miss(tmp_path):
    p = tmp_path / "predictability.parquet"
    _make_v2_parquet(p)
    row = e5cli.fetch_predictability_row(str(p), "NOT_A_GENE")
    assert row is None


def test_compute_summary_data_unavailable():
    s = e5cli.compute_summary(None, "GHOST")
    assert s["predictability_class"] == "data_unavailable"
    assert s["pred_dominant_feature_class"] == "data_unavailable"
    assert s["pred_top_features_rf"] == []
    assert "_live_read_error" in s


def test_compute_summary_populated(tmp_path):
    p = tmp_path / "predictability.parquet"
    _make_v2_parquet(p)
    row = e5cli.fetch_predictability_row(str(p), "BRAF")
    s = e5cli.compute_summary(row, "BRAF")
    assert s["pred_n_cell_lines_evaluated"] == 1180
    assert s["pearson_r_rf"] == pytest.approx(0.78, abs=1e-2)
    assert s["predictability_class"] == "own_omics_driven"
    assert s["pred_dominant_feature"] == "own_mut_hotspot"
    assert s["pred_dominant_feature_class"] == "own_mut_hotspot"
    assert s["model_agreement"] == "concordant"
    assert len(s["per_lineage_predictability"]) == 1


def test_emit_feature_importance_bar(tmp_path):
    p = tmp_path / "predictability.parquet"
    _make_v2_parquet(p)
    row = e5cli.fetch_predictability_row(str(p), "KRAS")
    s = e5cli.compute_summary(row, "KRAS")
    svg = e5cli.emit_feature_importance_bar(s, "KRAS", tmp_path)
    assert svg.exists() and svg.stat().st_size > 0


def test_emit_feature_importance_bar_data_unavailable(tmp_path):
    s = e5cli.compute_summary(None, "GHOST")
    svg = e5cli.emit_feature_importance_bar(s, "GHOST", tmp_path)
    assert svg.exists() and svg.stat().st_size > 0


def test_emit_lineage_conditional_panel(tmp_path):
    p = tmp_path / "predictability.parquet"
    _make_v2_parquet(p)
    row = e5cli.fetch_predictability_row(str(p), "KRAS")
    s = e5cli.compute_summary(row, "KRAS")
    svg = e5cli.emit_lineage_conditional_panel(s, "KRAS", tmp_path)
    assert svg.exists() and svg.stat().st_size > 0


def test_emit_lineage_conditional_panel_empty(tmp_path):
    p = tmp_path / "predictability.parquet"
    _make_v2_parquet(p)
    row = e5cli.fetch_predictability_row(str(p), "TP53")
    s = e5cli.compute_summary(row, "TP53")
    svg = e5cli.emit_lineage_conditional_panel(s, "TP53", tmp_path)
    assert svg.exists() and svg.stat().st_size > 0  # placeholder renders


def test_read_predictability_bad_pin_returns_data_unavailable():
    out = e5read.read_predictability("KRAS", indication=None, release_pin="bogus")
    assert out["predictability_class"] == "data_unavailable"
    assert "_live_read_error" in out


def test_read_predictability_local_parquet(tmp_path, monkeypatch):
    p = tmp_path / "predictability.parquet"
    _make_v2_parquet(p)
    monkeypatch.setitem(e5cli.RELEASE_PIN_TO_PARQUET, "test-pin", str(p))
    out = e5read.read_predictability("KRAS", indication=None, release_pin="test-pin")
    assert out["predictability_class"] == "own_omics_driven"
    assert out["pred_dominant_feature"] == "own_mut_hotspot"
    out_miss = e5read.read_predictability("NOPE", indication=None, release_pin="test-pin")
    assert out_miss["predictability_class"] == "data_unavailable"
