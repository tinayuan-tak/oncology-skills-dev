"""Synthetic-data tests for the depmap_predictability thin lookup card.

Writes a tiny parquet to a tmp_path, points the cli helpers at it, verifies:
  - per-target row lookup returns the right summary shape
  - missing target → data_unavailable summary (graceful)
  - feature_importance bar SVG renders (file exists + non-zero)
  - read.py shim returns the same shape as cli's compute_summary
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


def _make_synthetic_parquet(out_path: Path):
    """Build a 3-gene parquet matching the production schema."""
    top_feature_struct = pa.struct([
        pa.field("feature", pa.string()),
        pa.field("feature_class", pa.string()),
        pa.field("importance", pa.float32()),
    ])
    schema = pa.schema([
        pa.field("gene_symbol", pa.string()),
        pa.field("n_cell_lines_evaluated", pa.int32()),
        pa.field("predictability_r2", pa.float32()),
        pa.field("top_features", pa.list_(top_feature_struct)),
        pa.field("dominant_feature_class", pa.string()),
        pa.field("predictability_class", pa.string()),
    ])
    rows = {
        "gene_symbol": ["BRAF", "KRAS", "TP53"],
        "n_cell_lines_evaluated": [1180, 1250, 1300],
        "predictability_r2": [0.61, 0.58, 0.18],
        "top_features": [
            [{"feature": "own_mut_hotspot", "feature_class": "own_mut_hotspot", "importance": 0.51},
             {"feature": "lineage_Skin",   "feature_class": "lineage",         "importance": 0.18}],
            [{"feature": "own_mut_hotspot", "feature_class": "own_mut_hotspot", "importance": 0.42},
             {"feature": "lineage_Bowel",  "feature_class": "lineage",         "importance": 0.20}],
            [{"feature": "own_mut_damaging", "feature_class": "own_mut_damaging", "importance": 0.08}],
        ],
        "dominant_feature_class": ["own_mut_hotspot", "own_mut_hotspot", "unpredictable"],
        "predictability_class":   ["own_omics_driven", "own_omics_driven", "unpredictable"],
    }
    table = pa.Table.from_pydict(rows, schema=schema)
    pq.write_table(table, out_path, row_group_size=64)


def test_fetch_predictability_row_hit(tmp_path):
    parquet = tmp_path / "predictability.parquet"
    _make_synthetic_parquet(parquet)
    row = e5cli.fetch_predictability_row(str(parquet), "KRAS")
    assert row is not None
    assert row["gene_symbol"] == "KRAS"
    assert row["predictability_class"] == "own_omics_driven"
    assert row["top_features"][0]["feature"] == "own_mut_hotspot"


def test_fetch_predictability_row_miss(tmp_path):
    parquet = tmp_path / "predictability.parquet"
    _make_synthetic_parquet(parquet)
    row = e5cli.fetch_predictability_row(str(parquet), "NOT_A_GENE")
    assert row is None


def test_compute_summary_data_unavailable_when_row_none():
    summary = e5cli.compute_summary(None, "NOT_A_GENE")
    assert summary["predictability_class"] == "data_unavailable"
    assert summary["pred_dominant_feature_class"] == "data_unavailable"
    assert "_live_read_error" in summary
    assert summary["pred_top_features"] == []


def test_compute_summary_populated_when_row_present(tmp_path):
    parquet = tmp_path / "predictability.parquet"
    _make_synthetic_parquet(parquet)
    row = e5cli.fetch_predictability_row(str(parquet), "BRAF")
    summary = e5cli.compute_summary(row, "BRAF")
    assert summary["pred_n_cell_lines_evaluated"] == 1180
    assert summary["pred_r2"] == pytest.approx(0.61, abs=1e-2)
    assert summary["predictability_class"] == "own_omics_driven"
    assert summary["pred_dominant_feature"] == "own_mut_hotspot"
    assert summary["pred_dominant_feature_class"] == "own_mut_hotspot"


def test_emit_feature_importance_bar(tmp_path):
    parquet = tmp_path / "predictability.parquet"
    _make_synthetic_parquet(parquet)
    row = e5cli.fetch_predictability_row(str(parquet), "BRAF")
    summary = e5cli.compute_summary(row, "BRAF")
    svg = e5cli.emit_feature_importance_bar(summary, "BRAF", tmp_path)
    assert svg.exists()
    assert svg.stat().st_size > 0


def test_emit_feature_importance_bar_data_unavailable(tmp_path):
    summary = e5cli.compute_summary(None, "GHOST")
    svg = e5cli.emit_feature_importance_bar(summary, "GHOST", tmp_path)
    assert svg.exists()
    assert svg.stat().st_size > 0


def test_read_predictability_returns_data_unavailable_on_bad_pin(monkeypatch):
    """The read.py shim should never throw on bad release_pin — it returns a
    well-shaped data_unavailable summary so the framework's graceful-degradation
    contract holds (matches the E1-E4 pattern)."""
    out = e5read.read_predictability("KRAS", indication=None, release_pin="bogus-pin")
    assert out["predictability_class"] == "data_unavailable"
    assert "_live_read_error" in out


def test_read_predictability_local_parquet_via_monkeypatch(tmp_path, monkeypatch):
    """End-to-end with a local parquet by monkey-patching RELEASE_PIN_TO_PARQUET."""
    parquet = tmp_path / "predictability.parquet"
    _make_synthetic_parquet(parquet)
    monkeypatch.setitem(e5cli.RELEASE_PIN_TO_PARQUET, "test-pin", str(parquet))
    out = e5read.read_predictability("KRAS", indication=None, release_pin="test-pin")
    assert out["predictability_class"] == "own_omics_driven"
    assert out["pred_dominant_feature"] == "own_mut_hotspot"
    # Missing-target path
    out_miss = e5read.read_predictability("NOT_A_GENE", indication=None, release_pin="test-pin")
    assert out_miss["predictability_class"] == "data_unavailable"
