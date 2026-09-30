"""emit_plotly_specs (Gate-C plotly debt, 2026-07-21) for depmap_crispr_rnai_concordance.

Interactive twin of emit_concordance_scatter: CRISPR Chronos (x) vs RNAi DEMETER2 (y) for lines
assayed in BOTH, same quadrant thresholds (-0.5 CRISPR / -0.25 RNAi). Built from the SAME per_line
concordance list the SVG + plot_data.parquet use — no drift. No S3 (synthetic per_line). Plotly optional.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CLI = REPO / "onc_methods" / "depmap_crispr_rnai_concordance" / "cli.py"
# Portable sibling root: was hardcoded to the author's /home/sagemaker-user checkout, so the
# guard below reported "not available" on every CI runner -- even though the workflow checks
# this sibling out and exports its root. `or` rather than a .get() default, so an EMPTY value
# falls back too instead of yielding Path("") == the CWD, which reads as a plausible wrong root.
CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT") or REPO.parent / "rnd-computational-biology-oncology-target-contracts"
)

pytest.importorskip("plotly", reason="plotly not installed in this env")


def _load():
    spec = importlib.util.spec_from_file_location("conc_cli", CLI)
    m = importlib.util.module_from_spec(spec)
    sys.modules["conc_cli"] = m
    spec.loader.exec_module(m)
    return m


cli = _load()


def _decode(v):
    if isinstance(v, dict) and "bdata" in v:
        import numpy as np

        return np.frombuffer(base64.b64decode(v["bdata"]), dtype={"f8": "<f8", "f4": "<f4"}[v["dtype"]]).tolist()
    return list(v)


def _per_line():
    # 4 in-both (one per concordance bucket) + 1 crispr-only + 1 rnai-only
    return [
        {"model_id": "ACH-001", "chronos": -1.2, "demeter2": -0.8, "concordance_label": "agree_dependent"},
        {"model_id": "ACH-002", "chronos": 0.1, "demeter2": 0.05, "concordance_label": "agree_non_dependent"},
        {"model_id": "ACH-003", "chronos": -0.9, "demeter2": 0.0, "concordance_label": "disagree_crispr_dependent"},
        {"model_id": "ACH-004", "chronos": 0.0, "demeter2": -0.4, "concordance_label": "disagree_rnai_dependent"},
        {"model_id": "ACH-005", "chronos": -0.7, "demeter2": None, "concordance_label": "crispr_only_dependent"},
        {"model_id": "ACH-006", "chronos": None, "demeter2": -0.6, "concordance_label": "rnai_only_dependent"},
    ]


def test_emits_valid_scatter_spec():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        written = cli.emit_plotly_specs(_per_line(), "KRAS", out, CONTRACTS)
        assert {w["id"] for w in written} == {"concordance_scatter"}
        obj = json.loads((out / "figure_concordance_scatter.plotly.json").read_text())
        assert obj["data"] and obj["data"][0]["mode"] == "markers"
        assert written[0]["type"] == "plotly"


def test_no_drift_only_in_both_points_plotted():
    """Only lines assayed in BOTH appear (4 of the 6) — the crispr-only + rnai-only lines are
    excluded, exactly as the SVG does."""
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        cli.emit_plotly_specs(_per_line(), "KRAS", out, CONTRACTS)
        sc = json.loads((out / "figure_concordance_scatter.plotly.json").read_text())
        xs = _decode(sc["data"][0]["x"])
        ys = _decode(sc["data"][0]["y"])
        assert len(xs) == 4 and len(ys) == 4
        assert sorted(xs) == sorted([-1.2, 0.1, -0.9, 0.0])
        assert sorted(ys) == sorted([-0.8, 0.05, 0.0, -0.4])


def test_quadrant_thresholds_present():
    """The -0.5 CRISPR (vline) + -0.25 RNAi (hline) quadrant thresholds mirror the SVG."""
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        cli.emit_plotly_specs(_per_line(), "KRAS", out, CONTRACTS)
        sc = json.loads((out / "figure_concordance_scatter.plotly.json").read_text())
        shapes = sc["layout"].get("shapes", [])
        xvals = {round(s.get("x0", -99), 2) for s in shapes if s.get("x0") == s.get("x1")}
        yvals = {round(s.get("y0", -99), 2) for s in shapes if s.get("y0") == s.get("y1")}
        assert -0.5 in xvals, f"missing CRISPR vline; got {xvals}"
        assert -0.25 in yvals, f"missing RNAi hline; got {yvals}"
