"""emit_plotly_specs (Gate-C plotly debt, 2026-07-21) for depmap_chronos (lineage-selectivity).

Interactive twin of emit_forest_plot: per-lineage median Chronos + p25–p75 IQR bar, target lineage
highlighted (red diamond), reflines at 0 / -0.5 / -1.0. Built from the SAME per_lineage_records the
SVG + plot_data.parquet use — no drift. No S3 (synthetic records). Plotly optional.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CLI = REPO / "methods" / "depmap_chronos" / "cli.py"
CONTRACTS = Path("/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")

pytest.importorskip("plotly", reason="plotly not installed in this env")


def _load():
    spec = importlib.util.spec_from_file_location("chr2_cli", CLI)
    m = importlib.util.module_from_spec(spec)
    sys.modules["chr2_cli"] = m
    spec.loader.exec_module(m)
    return m


cli = _load()


def _decode(v):
    if isinstance(v, dict) and "bdata" in v:
        import numpy as np

        return np.frombuffer(base64.b64decode(v["bdata"]), dtype={"f8": "<f8", "f4": "<f4"}[v["dtype"]]).tolist()
    return list(v)


def _records():
    # pre-sorted ascending by median_chronos (most dependent first), as the method emits.
    return [
        {"lineage": "Bowel", "median_chronos": -1.3, "p25_chronos": -1.6, "p75_chronos": -0.9, "n": 40},
        {"lineage": "Lung", "median_chronos": -0.6, "p25_chronos": -0.9, "p75_chronos": -0.2, "n": 55},
        {"lineage": "Skin", "median_chronos": -0.1, "p25_chronos": -0.3, "p75_chronos": 0.1, "n": 30},
    ]


def test_emits_valid_forest_spec():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        written = cli.emit_plotly_specs(_records(), "Bowel", "KRAS", "COADREAD", {}, out, CONTRACTS)
        assert {w["id"] for w in written} == {"forest_plot"}
        obj = json.loads((out / "figure_forest_plot.plotly.json").read_text())
        assert obj["data"] and obj["data"][-1]["mode"] == "markers"  # last trace = median markers
        assert written[0]["type"] == "plotly"


def test_no_drift_medians_match_records():
    """The median-marker x-values equal the record medians (no drift from the SVG / plot_data)."""
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        cli.emit_plotly_specs(_records(), "Bowel", "KRAS", "COADREAD", {}, out, CONTRACTS)
        obj = json.loads((out / "figure_forest_plot.plotly.json").read_text())
        markers = obj["data"][-1]  # the go.Scatter markers trace
        assert sorted(_decode(markers["x"])) == sorted([-1.3, -0.6, -0.1])


def test_reference_lines_at_chronos_thresholds():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        cli.emit_plotly_specs(_records(), "Bowel", "KRAS", "COADREAD", {}, out, CONTRACTS)
        obj = json.loads((out / "figure_forest_plot.plotly.json").read_text())
        xvals = {round(s.get("x0", -99), 2) for s in obj["layout"].get("shapes", []) if s.get("x0") == s.get("x1")}
        assert {0.0, -0.5, -1.0} <= xvals, f"missing Chronos reflines; got {xvals}"


def test_empty_records_no_op():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        assert cli.emit_plotly_specs([], "Bowel", "KRAS", "COADREAD", {}, out, CONTRACTS) == []
