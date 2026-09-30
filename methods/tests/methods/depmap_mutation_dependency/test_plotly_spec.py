"""emit_plotly_specs (Gate-C plotly debt, 2026-07-21) for depmap_mutation_dependency.

Interactive twin of emit_mut_vs_wt_strip_plot: Chronos box+strip grouped by mutation status
(hotspot mut/WT + damaging mut/WT), reflines at 0 / -1.0. Built from the SAME chronos_by_model +
hotspot/damaging membership the SVG + plot_data.parquet use — no drift. No S3 (synthetic). Plotly optional.
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
CLI = REPO / "onc_methods" / "depmap_mutation_dependency" / "cli.py"
# Portable sibling root: was hardcoded to the author's /home/sagemaker-user checkout, so the
# guard below reported "not available" on every CI runner -- even though the workflow checks
# this sibling out and exports its root. `or` rather than a .get() default, so an EMPTY value
# falls back too instead of yielding Path("") == the CWD, which reads as a plausible wrong root.
CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT") or REPO.parent / "rnd-computational-biology-oncology-target-contracts"
)

pytest.importorskip("plotly", reason="plotly not installed in this env")


def _load():
    spec = importlib.util.spec_from_file_location("mut_cli", CLI)
    m = importlib.util.module_from_spec(spec)
    sys.modules["mut_cli"] = m
    spec.loader.exec_module(m)
    return m


cli = _load()


def _decode(v):
    if isinstance(v, dict) and "bdata" in v:
        import numpy as np

        return np.frombuffer(base64.b64decode(v["bdata"]), dtype={"f8": "<f8", "f4": "<f4"}[v["dtype"]]).tolist()
    return list(v)


def _fixture():
    chronos = {f"ACH-{i:03d}": (-1.5 + i * 0.06) for i in range(40)}
    hotspot = {m: (i % 4 == 0) for i, m in enumerate(chronos)}  # 25% hotspot-mutant
    damaging = {m: (i % 5 == 0) for i, m in enumerate(chronos)}  # 20% damaging
    summary = {
        "mutation_stratification_class": "mutant_strongly_dependent",
        "hotspot_mannwhitney_q": 1e-4,
        "damaging_mannwhitney_q": 0.03,
    }
    return chronos, hotspot, damaging, summary


def test_emits_valid_strip_spec():
    chronos, hot, dam, summary = _fixture()
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        written = cli.emit_plotly_specs(chronos, hot, dam, "KRAS", summary, out, CONTRACTS)
        assert {w["id"] for w in written} == {"mut_vs_wt_strip"}
        obj = json.loads((out / "figure_mut_vs_wt_strip.plotly.json").read_text())
        # 4 box traces (hotspot mut/WT + damaging mut/WT)
        assert len(obj["data"]) == 4
        assert all(t["type"] == "box" for t in obj["data"])
        assert written[0]["type"] == "plotly"


def test_no_drift_group_membership_matches_input():
    """The hotspot-mutant box's y-values equal exactly the chronos of hotspot-mutant lines."""
    chronos, hot, dam, summary = _fixture()
    expect_hot_mut = sorted(chronos[m] for m in chronos if hot[m])
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        cli.emit_plotly_specs(chronos, hot, dam, "KRAS", summary, out, CONTRACTS)
        obj = json.loads((out / "figure_mut_vs_wt_strip.plotly.json").read_text())
        hot_mut = next(t for t in obj["data"] if t["name"] == "hotspot mutant")
        assert sorted(_decode(hot_mut["y"])) == expect_hot_mut


def test_reference_lines_at_chronos_thresholds():
    chronos, hot, dam, summary = _fixture()
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        cli.emit_plotly_specs(chronos, hot, dam, "KRAS", summary, out, CONTRACTS)
        obj = json.loads((out / "figure_mut_vs_wt_strip.plotly.json").read_text())
        yvals = {round(s.get("y0", -99), 2) for s in obj["layout"].get("shapes", []) if s.get("y0") == s.get("y1")}
        assert {0.0, -1.0} <= yvals, f"missing reflines; got {yvals}"


def test_empty_no_op():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        assert cli.emit_plotly_specs({}, {}, {}, "KRAS", {}, out, CONTRACTS) == []
