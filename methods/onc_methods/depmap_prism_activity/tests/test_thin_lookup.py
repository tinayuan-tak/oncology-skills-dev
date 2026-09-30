"""Synthetic tests for depmap_prism_activity thin lookup (E6, v3 Log2AUC).

Writes a synthetic aggregate parquet to tmp_path, points cli helpers at it,
verifies:
  - per-target row lookup + summary mapping (Log2AUC primary metric)
  - target-absent → no_compounds_found (NOT data_unavailable)
  - top_compounds bar + lineage bar render (populated + placeholder cases)
  - vocabulary panel renders
  - read.py shim maps release_pin + surfaces bad-pin gracefully
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from onc_methods.depmap_prism_activity import cli as e6cli
from onc_methods.depmap_prism_activity import read as e6read


def _make_synthetic_parquet(out_path: Path):
    """Build a small aggregate parquet matching production v3 schema — KRAS + EGFR + weak gene."""
    top_struct = pa.struct(
        [
            pa.field("compound_id", pa.string()),
            pa.field("drug_name", pa.string()),
            pa.field("moa", pa.string()),
            pa.field("median_log2auc", pa.float32()),
            pa.field("best_responder_lfc", pa.float32()),
            pa.field("single_dose_lfc", pa.float32()),
            pa.field("n_lines_screened", pa.int32()),
            pa.field("polyselective", pa.bool_()),
            pa.field("n_annotated_targets", pa.int32()),
            pa.field("source_release", pa.string()),
            pa.field("prioritized", pa.bool_()),
            pa.field("metric_source", pa.string()),
        ]
    )
    lineage_struct = pa.struct(
        [
            pa.field("lineage", pa.string()),
            pa.field("n_lines_screened", pa.int32()),
            pa.field("median_log2auc", pa.float32()),
            pa.field("best_responder_lfc", pa.float32()),
            pa.field("top_compound_in_lineage", pa.string()),
            pa.field("n_compounds_evaluated", pa.int32()),
        ]
    )
    schema = pa.schema(
        [
            pa.field("gene_symbol", pa.string()),
            pa.field("n_compounds_targeting", pa.int32()),
            pa.field("highest_clinical_phase", pa.string()),
            pa.field("median_log2auc_across_compounds", pa.float32()),
            pa.field("top_compounds", pa.list_(top_struct)),
            pa.field("prism_activity_class", pa.string()),
            pa.field("per_lineage_activity", pa.list_(lineage_struct)),
            pa.field("prism_lineage_selectivity", pa.string()),
        ]
    )

    def tc(cid, name, moa, log2auc, best_lfc, sd_lfc, n, poly, ntgt, rel, prio, metric):
        return {
            "compound_id": cid,
            "drug_name": name,
            "moa": moa,
            "median_log2auc": log2auc,
            "best_responder_lfc": best_lfc,
            "single_dose_lfc": sd_lfc,
            "n_lines_screened": n,
            "polyselective": poly,
            "n_annotated_targets": ntgt,
            "source_release": rel,
            "prioritized": prio,
            "metric_source": metric,
        }

    def ln(lineage, n, log2auc, best_lfc, top, ncmp):
        return {
            "lineage": lineage,
            "n_lines_screened": n,
            "median_log2auc": log2auc,
            "best_responder_lfc": best_lfc,
            "top_compound_in_lineage": top,
            "n_compounds_evaluated": ncmp,
        }

    rows = {
        "gene_symbol": ["EGFR", "KRAS", "WEAKGENE"],
        "n_compounds_targeting": [15, 5, 2],
        "highest_clinical_phase": ["phase_1_plus", "phase_1_plus", "tool"],
        "median_log2auc_across_compounds": [-0.35, -0.16, -0.04],
        "top_compounds": [
            [
                tc(
                    "PRC-EGFR-1",
                    "ERLOTINIB",
                    "EGFR TKI",
                    -0.5,
                    -6.8,
                    None,
                    400,
                    False,
                    1,
                    "oncref-25q4",
                    True,
                    "log2auc",
                ),
                tc(
                    "PRC-EGFR-2",
                    "OSIMERTINIB",
                    "EGFR TKI T790M",
                    -0.42,
                    -9.3,
                    None,
                    400,
                    False,
                    1,
                    "oncref-25q4",
                    True,
                    "log2auc",
                ),
            ],
            [
                tc(
                    "PRC-KRAS-1",
                    "DARAXONRASIB",
                    "pan-RAS",
                    -0.43,
                    -4.7,
                    None,
                    380,
                    False,
                    1,
                    "oncref-25q4",
                    True,
                    "log2auc",
                ),
                tc(
                    "BRD-LON",
                    "LONAFARNIB",
                    "FTase inhibitor",
                    None,
                    None,
                    -0.4,
                    500,
                    True,
                    4,
                    "repurposing-24q2",
                    False,
                    "single_dose_lfc",
                ),
            ],
            [
                tc(
                    "BRD-WEAK",
                    "TOOL-COMPOUND-X",
                    "unknown",
                    None,
                    None,
                    -0.3,
                    400,
                    False,
                    1,
                    "repurposing-24q2",
                    False,
                    "single_dose_lfc",
                ),
            ],
        ],
        "prism_activity_class": ["clinically_active", "clinically_active", "tool_compound_only"],
        "per_lineage_activity": [
            # EGFR: broadly active
            [
                ln("Lung", 60, -0.5, -8.0, "ERLOTINIB", 15),
                ln("HeadNeck", 12, -0.3, -6.0, "OSIMERTINIB", 15),
                ln("Skin", 30, -0.2, -4.0, "AFATINIB", 15),
            ],
            # KRAS: lineage_selective — Bowel/Pancreas active, Skin inactive
            [
                ln("Bowel", 44, -0.35, -4.7, "DARAXONRASIB", 5),
                ln("Pancreas", 42, -0.20, -5.1, "DARAXONRASIB", 5),
                ln("Skin", 52, 0.0, -1.6, "LONAFARNIB", 5),
            ],
            # WEAKGENE: no signal
            [
                ln("Bowel", 20, -0.02, -0.5, "TOOL-COMPOUND-X", 2),
            ],
        ],
        "prism_lineage_selectivity": ["broadly_active", "lineage_selective", "no_lineage_signal"],
    }
    table = pa.Table.from_pydict(rows, schema=schema)
    pq.write_table(table, out_path, row_group_size=64)


# ---------------------------------------------------------------------------
# Parquet lookup
# ---------------------------------------------------------------------------


def test_fetch_prism_row_hit(tmp_path):
    p = tmp_path / "prism.parquet"
    _make_synthetic_parquet(p)
    row = e6cli.fetch_prism_row(str(p), "KRAS")
    assert row is not None
    assert row["gene_symbol"] == "KRAS"
    assert row["prism_activity_class"] == "clinically_active"
    assert row["top_compounds"][0]["drug_name"] == "DARAXONRASIB"


def test_fetch_prism_row_miss(tmp_path):
    p = tmp_path / "prism.parquet"
    _make_synthetic_parquet(p)
    assert e6cli.fetch_prism_row(str(p), "NOT_A_GENE") is None


# ---------------------------------------------------------------------------
# Summary compute
# ---------------------------------------------------------------------------


def test_compute_summary_no_compounds_when_row_missing():
    s = e6cli.compute_summary(None, "GHOSTGENE")
    assert s["prism_activity_class"] == "no_compounds_found"
    assert s["n_compounds_targeting"] == 0
    assert s["top_compounds"] == []
    assert s["median_log2auc_across_compounds"] is None
    assert "_data_note" in s


def test_compute_summary_clinically_active(tmp_path):
    p = tmp_path / "prism.parquet"
    _make_synthetic_parquet(p)
    row = e6cli.fetch_prism_row(str(p), "EGFR")
    s = e6cli.compute_summary(row, "EGFR")
    assert s["prism_activity_class"] == "clinically_active"
    assert s["n_compounds_targeting"] == 15
    assert s["median_log2auc_across_compounds"] == pytest.approx(-0.35, abs=1e-2)
    assert len(s["top_compounds"]) == 2


def test_compute_summary_lineage_selective(tmp_path):
    p = tmp_path / "prism.parquet"
    _make_synthetic_parquet(p)
    row = e6cli.fetch_prism_row(str(p), "KRAS")
    s = e6cli.compute_summary(row, "KRAS")
    assert s["prism_lineage_selectivity"] == "lineage_selective"
    lineages = {e["lineage"] for e in s["per_lineage_activity"]}
    assert lineages == {"Bowel", "Pancreas", "Skin"}


def test_compute_summary_polyselective_flag(tmp_path):
    p = tmp_path / "prism.parquet"
    _make_synthetic_parquet(p)
    row = e6cli.fetch_prism_row(str(p), "KRAS")
    s = e6cli.compute_summary(row, "KRAS")
    poly = [c for c in s["top_compounds"] if c["polyselective"]]
    assert len(poly) == 1
    assert poly[0]["drug_name"] == "LONAFARNIB"
    assert poly[0]["n_annotated_targets"] == 4
    assert poly[0]["metric_source"] == "single_dose_lfc"


def test_compute_summary_coerces_nan_median_to_none():
    """A NaN median_log2auc must surface as None."""
    row = {
        "prism_activity_class": "tool_compound_only",
        "n_compounds_targeting": 1,
        "highest_clinical_phase": "tool",
        "median_log2auc_across_compounds": float("nan"),
        "top_compounds": [],
        "per_lineage_activity": [],
        "prism_lineage_selectivity": "data_unavailable",
    }
    s = e6cli.compute_summary(row, "MYC")
    assert s["median_log2auc_across_compounds"] is None


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


def test_emit_top_compounds_bar_no_compounds_found_placeholder(tmp_path):
    s = e6cli.compute_summary(None, "GHOSTGENE")
    svg = e6cli.emit_top_compounds_bar(s, "GHOSTGENE", tmp_path)
    assert svg.exists() and svg.stat().st_size > 0


def test_emit_lineage_activity_bar_populated(tmp_path):
    p = tmp_path / "prism.parquet"
    _make_synthetic_parquet(p)
    row = e6cli.fetch_prism_row(str(p), "KRAS")
    s = e6cli.compute_summary(row, "KRAS")
    svg = e6cli.emit_lineage_activity_bar(s, "KRAS", tmp_path)
    assert svg.exists() and svg.stat().st_size > 0


def test_emit_lineage_activity_bar_placeholder_when_empty(tmp_path):
    s = e6cli.compute_summary(None, "GHOSTGENE")
    svg = e6cli.emit_lineage_activity_bar(s, "GHOSTGENE", tmp_path)
    assert svg.exists() and svg.stat().st_size > 0


def test_emit_activity_vocabulary_panel(tmp_path):
    p = tmp_path / "prism.parquet"
    _make_synthetic_parquet(p)
    row = e6cli.fetch_prism_row(str(p), "EGFR")
    s = e6cli.compute_summary(row, "EGFR")
    svg = e6cli.emit_activity_vocabulary_panel(s, "EGFR", tmp_path)
    assert svg.exists() and svg.stat().st_size > 0


# ---------------------------------------------------------------------------
# read.py shim
# ---------------------------------------------------------------------------


def test_read_prism_activity_bad_pin_returns_data_unavailable():
    out = e6read.read_prism_activity("KRAS", indication=None, release_pin="bogus")
    assert out["prism_activity_class"] == "data_unavailable"
    assert "_live_read_error" in out
    assert out["median_log2auc_across_compounds"] is None


def test_read_prism_activity_local_parquet(tmp_path, monkeypatch):
    p = tmp_path / "prism.parquet"
    _make_synthetic_parquet(p)
    monkeypatch.setitem(e6cli.RELEASE_PIN_TO_PARQUET, "test-pin", str(p))
    out = e6read.read_prism_activity("KRAS", indication=None, release_pin="test-pin")
    assert out["prism_activity_class"] == "clinically_active"
    assert out["n_compounds_targeting"] == 5
    assert out["prism_lineage_selectivity"] == "lineage_selective"
    out_miss = e6read.read_prism_activity("NOPE", indication=None, release_pin="test-pin")
    assert out_miss["prism_activity_class"] == "no_compounds_found"
    assert out_miss["top_compounds"] == []
