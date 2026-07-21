"""emit_plotly_specs (Gate-C plotly debt, 2026-07-21) for depmap_prism_crispr_concordance.

Interactive twin of emit_concordance_scatter: per-compound Spearman ρ vs CRISPR (x) vs RNAi (y),
same quadrant coloring + reflines at 0.10 / 0.30 (both axes) + 0. Built from the SAME
summary['per_compound_concordance'] the SVG + the shared v4 parquet use — no drift. No S3
(synthetic summary). Plotly optional; thin/absent evidence → no-op.
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
CLI = REPO / "methods" / "depmap_prism_crispr_concordance" / "cli.py"
CONTRACTS = Path("/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")

pytest.importorskip("plotly", reason="plotly not installed in this env")


def _load():
    spec = importlib.util.spec_from_file_location("e7_cli", CLI)
    m = importlib.util.module_from_spec(spec)
    sys.modules["e7_cli"] = m
    spec.loader.exec_module(m)
    return m


cli = _load()


def _decode(v):
    if isinstance(v, dict) and "bdata" in v:
        import numpy as np
        return np.frombuffer(base64.b64decode(v["bdata"]),
                             dtype={"f8": "<f8", "f4": "<f4"}[v["dtype"]]).tolist()
    return list(v)


def _summary():
    return {
        "crispr_prism_concordance_class": "triangulated_target_engaged",
        "n_compounds_evaluated": 4,
        "per_compound_concordance": [
            {"drug_name": "drugA", "spearman_r_crispr": 0.5, "spearman_r_rnai": 0.45},
            {"drug_name": "drugB", "spearman_r_crispr": 0.35, "spearman_r_rnai": 0.1},
            {"drug_name": "drugC", "spearman_r_crispr": 0.05, "spearman_r_rnai": 0.4},
            {"drug_name": "drugD", "spearman_r_crispr": -0.1, "spearman_r_rnai": 0.0},
        ],
    }


def test_emits_valid_scatter_spec():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        written = cli.emit_plotly_specs(_summary(), "KRAS", out, CONTRACTS)
        assert {w["id"] for w in written} == {"concordance_scatter"}
        obj = json.loads((out / "figure_concordance_scatter.plotly.json").read_text())
        assert obj["data"] and obj["data"][0]["mode"] == "markers"
        assert written[0]["type"] == "plotly"


def test_no_drift_series_match_summary():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        cli.emit_plotly_specs(_summary(), "KRAS", out, CONTRACTS)
        obj = json.loads((out / "figure_concordance_scatter.plotly.json").read_text())
        assert sorted(_decode(obj["data"][0]["x"])) == sorted([0.5, 0.35, 0.05, -0.1])
        assert sorted(_decode(obj["data"][0]["y"])) == sorted([0.45, 0.1, 0.4, 0.0])


def test_threshold_reflines_present():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        cli.emit_plotly_specs(_summary(), "KRAS", out, CONTRACTS)
        obj = json.loads((out / "figure_concordance_scatter.plotly.json").read_text())
        xvals = {round(s.get("x0", -99), 2) for s in obj["layout"].get("shapes", [])
                 if s.get("x0") == s.get("x1")}
        assert {0.1, 0.3, 0.0} <= xvals, f"missing threshold/zero reflines; got {xvals}"


def test_thin_evidence_no_op():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        assert cli.emit_plotly_specs({"per_compound_concordance": []}, "KRAS", out, CONTRACTS) == []
        # a row with both rhos None is also thin
        thin = {"per_compound_concordance": [{"drug_name": "x", "spearman_r_crispr": None,
                                              "spearman_r_rnai": None}]}
        assert cli.emit_plotly_specs(thin, "KRAS", out, CONTRACTS) == []
