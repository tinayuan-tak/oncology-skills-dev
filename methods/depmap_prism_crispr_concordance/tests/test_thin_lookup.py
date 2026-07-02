"""Synthetic tests for depmap_prism_crispr_concordance thin lookup (E7).

Writes a v4-shape parquet to tmp_path, verifies concordance-specific field access,
figure emission, and read.py shim behavior.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from depmap_prism_crispr_concordance import cli as e7cli  # noqa: E402
from depmap_prism_crispr_concordance import read as e7read  # noqa: E402


def _make_synthetic_v4_parquet(out_path: Path):
    """Build a small v4-shape parquet — KRAS (triangulated) + BROADCYTOTOXIC (off_target) + WEAKGENE (thin)."""
    top_struct = pa.struct([
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
    ])
    lineage_struct = pa.struct([
        pa.field("lineage", pa.string()),
        pa.field("n_lines_screened", pa.int32()),
        pa.field("median_log2auc", pa.float32()),
        pa.field("best_responder_lfc", pa.float32()),
        pa.field("top_compound_in_lineage", pa.string()),
        pa.field("n_compounds_evaluated", pa.int32()),
    ])
    concordance_struct = pa.struct([
        pa.field("compound_id", pa.string()),
        pa.field("n_intersected_crispr", pa.int32()),
        pa.field("spearman_r_crispr", pa.float32()),
        pa.field("n_intersected_rnai", pa.int32()),
        pa.field("spearman_r_rnai", pa.float32()),
        pa.field("metric_used", pa.string()),
    ])
    dual_struct = pa.struct([
        pa.field("model_id", pa.string()),
        pa.field("lineage", pa.string()),
        pa.field("chronos_dep", pa.float32()),
        pa.field("best_compound_lfc", pa.float32()),
        pa.field("best_compound_id", pa.string()),
    ])
    schema = pa.schema([
        pa.field("gene_symbol", pa.string()),
        pa.field("n_compounds_targeting", pa.int32()),
        pa.field("highest_clinical_phase", pa.string()),
        pa.field("median_log2auc_across_compounds", pa.float32()),
        pa.field("top_compounds", pa.list_(top_struct)),
        pa.field("prism_activity_class", pa.string()),
        pa.field("per_lineage_activity", pa.list_(lineage_struct)),
        pa.field("prism_lineage_selectivity", pa.string()),
        pa.field("per_compound_concordance", pa.list_(concordance_struct)),
        pa.field("crispr_prism_concordance_class", pa.string()),
        pa.field("dual_responders", pa.list_(dual_struct)),
    ])

    def tc(cid, name):
        return {"compound_id": cid, "drug_name": name, "moa": "test",
                "median_log2auc": -0.3, "best_responder_lfc": -3.0, "single_dose_lfc": None,
                "n_lines_screened": 200, "polyselective": False, "n_annotated_targets": 1,
                "source_release": "oncref-25q4", "prioritized": True, "metric_source": "log2auc"}
    def ln(lineage):
        return {"lineage": lineage, "n_lines_screened": 30, "median_log2auc": -0.2,
                "best_responder_lfc": -3.0, "top_compound_in_lineage": "SOTORASIB",
                "n_compounds_evaluated": 1}
    def cd(cid, rc, rr):
        return {"compound_id": cid, "n_intersected_crispr": 45, "spearman_r_crispr": rc,
                "n_intersected_rnai": 30, "spearman_r_rnai": rr, "metric_used": "lfc"}
    def dr(mid, lineage, chr_dep, lfc, best_cid):
        return {"model_id": mid, "lineage": lineage, "chronos_dep": chr_dep,
                "best_compound_lfc": lfc, "best_compound_id": best_cid}

    rows = {
        "gene_symbol": ["KRAS", "OFFGENE", "WEAKGENE"],
        "n_compounds_targeting": [2, 1, 1],
        "highest_clinical_phase": ["phase_1_plus", "tool", "tool"],
        "median_log2auc_across_compounds": [-0.35, -0.15, -0.05],
        "top_compounds": [
            [tc("PRC-KRAS-1", "SOTORASIB"), tc("PRC-KRAS-2", "ADAGRASIB")],
            [tc("PRC-OFF-1", "TOXIC-COMPOUND")],
            [tc("PRC-WEAK-1", "WEAK-COMPOUND")],
        ],
        "prism_activity_class": ["clinically_active", "tool_compound_only", "tool_compound_only"],
        "per_lineage_activity": [[ln("Bowel")], [], []],
        "prism_lineage_selectivity": ["lineage_selective", "no_lineage_signal", "data_unavailable"],
        "per_compound_concordance": [
            [cd("PRC-KRAS-1", 0.65, 0.42), cd("PRC-KRAS-2", 0.55, 0.35)],   # triangulated
            [cd("PRC-OFF-1", 0.02, 0.04)],                                    # off-target
            [],                                                                # thin
        ],
        "crispr_prism_concordance_class": [
            "triangulated_target_engaged", "discordant_off_target_likely", "thin_evidence",
        ],
        "dual_responders": [
            [dr("ACH-KDEP-1", "Bowel", -1.4, -3.2, "PRC-KRAS-1"),
             dr("ACH-KDEP-2", "Pancreas", -1.1, -2.8, "PRC-KRAS-2")],
            [],
            [],
        ],
    }
    table = pa.Table.from_pydict(rows, schema=schema)
    pq.write_table(table, out_path, row_group_size=64)


def test_fetch_concordance_row_hit(tmp_path):
    p = tmp_path / "v4.parquet"
    _make_synthetic_v4_parquet(p)
    row = e7cli.fetch_concordance_row(str(p), "KRAS")
    assert row is not None
    assert row["crispr_prism_concordance_class"] == "triangulated_target_engaged"
    assert len(row["dual_responders"]) == 2


def test_fetch_concordance_row_miss(tmp_path):
    p = tmp_path / "v4.parquet"
    _make_synthetic_v4_parquet(p)
    assert e7cli.fetch_concordance_row(str(p), "NOT_A_GENE") is None


def test_compute_summary_missing_row():
    s = e7cli.compute_summary(None, "GHOST")
    assert s["crispr_prism_concordance_class"] == "data_unavailable"
    assert s["n_compounds_evaluated"] == 0
    assert s["dual_responders"] == []
    assert "_data_note" in s


def test_compute_summary_triangulated_populated(tmp_path):
    p = tmp_path / "v4.parquet"
    _make_synthetic_v4_parquet(p)
    row = e7cli.fetch_concordance_row(str(p), "KRAS")
    s = e7cli.compute_summary(row, "KRAS")
    assert s["crispr_prism_concordance_class"] == "triangulated_target_engaged"
    assert s["n_compounds_evaluated"] == 2
    assert s["best_spearman_r_crispr"] == pytest.approx(0.65, abs=1e-3)
    assert s["best_spearman_r_rnai"] == pytest.approx(0.42, abs=1e-3)
    assert s["n_dual_responders"] == 2
    # drug_name enrichment: compound_id → drug_name from top_compounds
    per = s["per_compound_concordance"]
    assert per[0]["drug_name"] == "SOTORASIB"
    assert per[1]["drug_name"] == "ADAGRASIB"


def test_compute_summary_off_target(tmp_path):
    p = tmp_path / "v4.parquet"
    _make_synthetic_v4_parquet(p)
    row = e7cli.fetch_concordance_row(str(p), "OFFGENE")
    s = e7cli.compute_summary(row, "OFFGENE")
    assert s["crispr_prism_concordance_class"] == "discordant_off_target_likely"
    assert s["n_dual_responders"] == 0


def test_emit_concordance_scatter_populated(tmp_path):
    p = tmp_path / "v4.parquet"
    _make_synthetic_v4_parquet(p)
    row = e7cli.fetch_concordance_row(str(p), "KRAS")
    s = e7cli.compute_summary(row, "KRAS")
    svg = e7cli.emit_concordance_scatter(s, "KRAS", tmp_path)
    assert svg.exists() and svg.stat().st_size > 0


def test_emit_concordance_scatter_placeholder(tmp_path):
    s = e7cli.compute_summary(None, "GHOST")
    svg = e7cli.emit_concordance_scatter(s, "GHOST", tmp_path)
    assert svg.exists() and svg.stat().st_size > 0


def test_emit_dual_responders_bar_populated(tmp_path):
    p = tmp_path / "v4.parquet"
    _make_synthetic_v4_parquet(p)
    row = e7cli.fetch_concordance_row(str(p), "KRAS")
    s = e7cli.compute_summary(row, "KRAS")
    svg = e7cli.emit_dual_responders_bar(s, "KRAS", tmp_path)
    assert svg.exists() and svg.stat().st_size > 0


def test_emit_dual_responders_bar_placeholder(tmp_path):
    p = tmp_path / "v4.parquet"
    _make_synthetic_v4_parquet(p)
    row = e7cli.fetch_concordance_row(str(p), "OFFGENE")
    s = e7cli.compute_summary(row, "OFFGENE")
    svg = e7cli.emit_dual_responders_bar(s, "OFFGENE", tmp_path)
    assert svg.exists() and svg.stat().st_size > 0


def test_emit_concordance_vocab_panel(tmp_path):
    p = tmp_path / "v4.parquet"
    _make_synthetic_v4_parquet(p)
    row = e7cli.fetch_concordance_row(str(p), "KRAS")
    s = e7cli.compute_summary(row, "KRAS")
    svg = e7cli.emit_concordance_vocabulary_panel(s, "KRAS", tmp_path)
    assert svg.exists() and svg.stat().st_size > 0


def test_read_shim_bad_pin_returns_data_unavailable():
    out = e7read.read_prism_crispr_concordance("KRAS", indication=None, release_pin="bogus")
    assert out["crispr_prism_concordance_class"] == "data_unavailable"
    assert "_live_read_error" in out


def test_read_shim_local_parquet(tmp_path, monkeypatch):
    p = tmp_path / "v4.parquet"
    _make_synthetic_v4_parquet(p)
    monkeypatch.setitem(e7cli.RELEASE_PIN_TO_PARQUET, "test-pin", str(p))
    out = e7read.read_prism_crispr_concordance("KRAS", indication=None, release_pin="test-pin")
    assert out["crispr_prism_concordance_class"] == "triangulated_target_engaged"
    out_miss = e7read.read_prism_crispr_concordance("NOPE", indication=None, release_pin="test-pin")
    assert out_miss["crispr_prism_concordance_class"] == "data_unavailable"
