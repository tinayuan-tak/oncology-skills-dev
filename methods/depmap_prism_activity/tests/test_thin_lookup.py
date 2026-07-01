"""Synthetic tests for depmap_prism_activity thin lookup (E6).

Writes a synthetic aggregate parquet to tmp_path, points cli helpers at it,
verifies:
  - per-target row lookup + summary mapping
  - target-absent → no_compounds_found (NOT data_unavailable — first-in-class opportunity)
  - top_compounds bar renders (populated case + no-compound case)
  - vocabulary panel renders
  - read.py shim maps release_pin correctly + surfaces bad-pin gracefully
"""

from __future__ import annotations

import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from depmap_prism_activity import cli as e6cli  # noqa: E402
from depmap_prism_activity import read as e6read  # noqa: E402


def _make_synthetic_parquet(out_path: Path):
    """Build a small aggregate parquet matching production schema — KRAS + EGFR + weak gene."""
    top_struct = pa.struct([
        pa.field("compound_id", pa.string()),
        pa.field("drug_name", pa.string()),
        pa.field("moa", pa.string()),
        pa.field("median_lfc", pa.float32()),
        pa.field("fraction_lines_responding", pa.float32()),
        pa.field("n_lines_screened", pa.int32()),
        pa.field("polyselective", pa.bool_()),
        pa.field("n_annotated_targets", pa.int32()),
        pa.field("source_release", pa.string()),
        pa.field("prioritized", pa.bool_()),
    ])
    schema = pa.schema([
        pa.field("gene_symbol", pa.string()),
        pa.field("n_compounds_targeting", pa.int32()),
        pa.field("highest_clinical_phase", pa.string()),
        pa.field("median_lfc_across_compounds", pa.float32()),
        pa.field("top_compounds", pa.list_(top_struct)),
        pa.field("prism_activity_class", pa.string()),
    ])
    rows = {
        "gene_symbol": ["EGFR", "KRAS", "WEAKGENE"],
        "n_compounds_targeting": [15, 5, 2],
        "highest_clinical_phase": ["phase_1_plus", "phase_1_plus", "tool"],
        "median_lfc_across_compounds": [-1.5, -1.2, -0.3],
        "top_compounds": [
            [
                {"compound_id": "PRC-EGFR-1", "drug_name": "ERLOTINIB", "moa": "EGFR TKI",
                 "median_lfc": -2.1, "fraction_lines_responding": 0.55, "n_lines_screened": 400,
                 "polyselective": False, "n_annotated_targets": 1,
                 "source_release": "oncref-25q4", "prioritized": True},
                {"compound_id": "PRC-EGFR-2", "drug_name": "OSIMERTINIB", "moa": "EGFR TKI T790M",
                 "median_lfc": -1.9, "fraction_lines_responding": 0.48, "n_lines_screened": 400,
                 "polyselective": False, "n_annotated_targets": 1,
                 "source_release": "oncref-25q4", "prioritized": True},
            ],
            [
                {"compound_id": "PRC-KRAS-1", "drug_name": "SOTORASIB", "moa": "KRAS G12C",
                 "median_lfc": -1.8, "fraction_lines_responding": 0.35, "n_lines_screened": 380,
                 "polyselective": False, "n_annotated_targets": 1,
                 "source_release": "oncref-25q4", "prioritized": True},
                {"compound_id": "BRD-LON", "drug_name": "LONAFARNIB", "moa": "FTase inhibitor",
                 "median_lfc": -0.4, "fraction_lines_responding": 0.05, "n_lines_screened": 500,
                 "polyselective": True, "n_annotated_targets": 4,
                 "source_release": "repurposing-24q2", "prioritized": False},
            ],
            [
                {"compound_id": "BRD-WEAK", "drug_name": "TOOL-COMPOUND-X", "moa": "unknown",
                 "median_lfc": -0.3, "fraction_lines_responding": 0.02, "n_lines_screened": 400,
                 "polyselective": False, "n_annotated_targets": 1,
                 "source_release": "repurposing-24q2", "prioritized": False},
            ],
        ],
        "prism_activity_class": [
            "clinically_active", "clinically_active", "tool_compound_only",
        ],
    }
    table = pa.Table.from_pydict(rows, schema=schema)
    pq.write_table(table, out_path, row_group_size=64)


# ---------------------------------------------------------------------------
# Parquet lookup path
# ---------------------------------------------------------------------------

def test_fetch_prism_row_hit(tmp_path):
    p = tmp_path / "prism.parquet"
    _make_synthetic_parquet(p)
    row = e6cli.fetch_prism_row(str(p), "KRAS")
    assert row is not None
    assert row["gene_symbol"] == "KRAS"
    assert row["prism_activity_class"] == "clinically_active"
    assert row["top_compounds"][0]["drug_name"] == "SOTORASIB"


def test_fetch_prism_row_miss(tmp_path):
    p = tmp_path / "prism.parquet"
    _make_synthetic_parquet(p)
    assert e6cli.fetch_prism_row(str(p), "NOT_A_GENE") is None


# ---------------------------------------------------------------------------
# Summary compute (vocabulary coverage)
# ---------------------------------------------------------------------------

def test_compute_summary_no_compounds_when_row_missing():
    """CRITICAL: absent row → no_compounds_found (opportunity), NOT data_unavailable."""
    s = e6cli.compute_summary(None, "GHOSTGENE")
    assert s["prism_activity_class"] == "no_compounds_found"
    assert s["n_compounds_targeting"] == 0
    assert s["top_compounds"] == []
    assert "_data_note" in s


def test_compute_summary_clinically_active(tmp_path):
    p = tmp_path / "prism.parquet"
    _make_synthetic_parquet(p)
    row = e6cli.fetch_prism_row(str(p), "EGFR")
    s = e6cli.compute_summary(row, "EGFR")
    assert s["prism_activity_class"] == "clinically_active"
    assert s["n_compounds_targeting"] == 15
    assert s["highest_clinical_phase"] == "phase_1_plus"
    assert len(s["top_compounds"]) == 2


def test_compute_summary_tool_compound_only(tmp_path):
    p = tmp_path / "prism.parquet"
    _make_synthetic_parquet(p)
    row = e6cli.fetch_prism_row(str(p), "WEAKGENE")
    s = e6cli.compute_summary(row, "WEAKGENE")
    assert s["prism_activity_class"] == "tool_compound_only"
    assert s["highest_clinical_phase"] == "tool"


def test_compute_summary_coerces_nan_median_to_none():
    """A NaN median_lfc (compound annotated but no LFC edges) must surface as None
    so warning predicates comparing `== null` fire correctly."""
    row = {
        "prism_activity_class": "tool_compound_only",
        "n_compounds_targeting": 1,
        "highest_clinical_phase": "tool",
        "median_lfc_across_compounds": float("nan"),
        "top_compounds": [],
    }
    s = e6cli.compute_summary(row, "MYC")
    assert s["median_lfc_across_compounds"] is None


def test_compute_summary_polyselective_flag(tmp_path):
    p = tmp_path / "prism.parquet"
    _make_synthetic_parquet(p)
    row = e6cli.fetch_prism_row(str(p), "KRAS")
    s = e6cli.compute_summary(row, "KRAS")
    poly = [c for c in s["top_compounds"] if c["polyselective"]]
    assert len(poly) == 1
    assert poly[0]["drug_name"] == "LONAFARNIB"
    assert poly[0]["n_annotated_targets"] == 4


# ---------------------------------------------------------------------------
# Figure emitters
# ---------------------------------------------------------------------------

def test_emit_top_compounds_bar_populated(tmp_path):
    p = tmp_path / "prism.parquet"
    _make_synthetic_parquet(p)
    row = e6cli.fetch_prism_row(str(p), "KRAS")
    s = e6cli.compute_summary(row, "KRAS")
    svg = e6cli.emit_top_compounds_bar(s, "KRAS", tmp_path)
    assert svg.exists() and svg.stat().st_size > 0


def test_emit_top_compounds_bar_no_compounds_found_renders_placeholder(tmp_path):
    s = e6cli.compute_summary(None, "GHOSTGENE")
    svg = e6cli.emit_top_compounds_bar(s, "GHOSTGENE", tmp_path)
    assert svg.exists() and svg.stat().st_size > 0


def test_emit_activity_vocabulary_panel(tmp_path):
    p = tmp_path / "prism.parquet"
    _make_synthetic_parquet(p)
    row = e6cli.fetch_prism_row(str(p), "EGFR")
    s = e6cli.compute_summary(row, "EGFR")
    svg = e6cli.emit_activity_vocabulary_panel(s, "EGFR", tmp_path)
    assert svg.exists() and svg.stat().st_size > 0


def test_emit_activity_vocabulary_panel_absent(tmp_path):
    s = e6cli.compute_summary(None, "GHOSTGENE")
    svg = e6cli.emit_activity_vocabulary_panel(s, "GHOSTGENE", tmp_path)
    assert svg.exists() and svg.stat().st_size > 0


# ---------------------------------------------------------------------------
# read.py shim
# ---------------------------------------------------------------------------

def test_read_prism_activity_bad_pin_returns_data_unavailable():
    out = e6read.read_prism_activity("KRAS", indication=None, release_pin="bogus")
    assert out["prism_activity_class"] == "data_unavailable"
    assert "_live_read_error" in out


def test_read_prism_activity_local_parquet(tmp_path, monkeypatch):
    p = tmp_path / "prism.parquet"
    _make_synthetic_parquet(p)
    monkeypatch.setitem(e6cli.RELEASE_PIN_TO_PARQUET, "test-pin", str(p))
    out = e6read.read_prism_activity("KRAS", indication=None, release_pin="test-pin")
    assert out["prism_activity_class"] == "clinically_active"
    assert out["n_compounds_targeting"] == 5
    out_miss = e6read.read_prism_activity("NOPE", indication=None, release_pin="test-pin")
    assert out_miss["prism_activity_class"] == "no_compounds_found"
    assert out_miss["top_compounds"] == []
