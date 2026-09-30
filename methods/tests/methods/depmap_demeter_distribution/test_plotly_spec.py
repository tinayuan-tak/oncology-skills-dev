"""emit_plotly_specs (Gate-C plotly debt, 2026-07-21) for depmap_demeter_distribution.

RNAi twin of the depmap_chronos_distribution plotly test. Interactive Plotly specs are SIBLINGS
to the matplotlib SVGs, built from the SAME in-memory demeter_by_model — so they can't drift from
the static figure or plot_data.parquet. DEMETER2 scale: reflines at -0.25 / -0.5 (not the Chronos
0 / -0.5 / -1.0). No S3 — synthetic input. Plotly optional at emit time.
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
CLI = REPO / "onc_methods" / "depmap_demeter_distribution" / "cli.py"
# Portable sibling root: was hardcoded to the author's /home/sagemaker-user checkout, so the
# guard below reported "not available" on every CI runner -- even though the workflow checks
# this sibling out and exports its root. `or` rather than a .get() default, so an EMPTY value
# falls back too instead of yielding Path("") == the CWD, which reads as a plausible wrong root.
CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT") or REPO.parent / "rnd-computational-biology-oncology-target-contracts"
)

pytest.importorskip("plotly", reason="plotly not installed in this env")


def _load():
    spec = importlib.util.spec_from_file_location("dem_cli", CLI)
    m = importlib.util.module_from_spec(spec)
    sys.modules["dem_cli"] = m
    spec.loader.exec_module(m)
    return m


cli = _load()


def _decode(v):
    if isinstance(v, dict) and "bdata" in v:
        import numpy as np

        return np.frombuffer(base64.b64decode(v["bdata"]), dtype={"f8": "<f8", "f4": "<f4"}[v["dtype"]]).tolist()
    return list(v)


def _fixture():
    demeter = {f"ACH-{i:03d}": (-1.5 + i * 0.03) for i in range(60)}
    meta = {
        f"ACH-{i:03d}": {"CellLineName": f"CL{i}", "OncotreeLineage": ["Bowel", "Lung", "Pancreas", "Skin"][i % 4]}
        for i in range(60)
    }
    summary = {
        "rnai_n_cell_lines_evaluated": 60,
        "rnai_median_dep_score": -0.3,
        "rnai_distribution_shape": "bimodal_selective",
        "rnai_fraction_strongly_dependent": 0.2,
    }
    return demeter, meta, summary


def test_emits_two_valid_plotly_specs():
    demeter, meta, summary = _fixture()
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        written = cli.emit_plotly_specs(demeter, meta, "KRAS", summary, out, CONTRACTS)
        ids = {w["id"] for w in written}
        assert ids == {"waterfall_rnai", "histogram_kde_rnai"}
        for w in written:
            obj = json.loads((out / w["path"]).read_text())
            assert "data" in obj and "layout" in obj and obj["data"], f"{w['id']} not a Plotly spec"
            assert w["type"] == "plotly"


def test_no_drift_series_match_input():
    demeter, meta, summary = _fixture()
    expect = sorted(demeter.values())
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        cli.emit_plotly_specs(demeter, meta, "KRAS", summary, out, CONTRACTS)
        wf = json.loads((out / "figure_waterfall_rnai.plotly.json").read_text())
        assert _decode(wf["data"][0]["y"]) == expect
        hist = json.loads((out / "figure_histogram_kde_rnai.plotly.json").read_text())
        assert sorted(_decode(hist["data"][0]["x"])) == expect


def test_reference_lines_at_demeter2_thresholds():
    """DEMETER2 reflines -0.25 / -0.5 mirror the SVG (NOT the Chronos 0/-0.5/-1.0)."""
    demeter, meta, summary = _fixture()
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        cli.emit_plotly_specs(demeter, meta, "KRAS", summary, out, CONTRACTS)
        wf = json.loads((out / "figure_waterfall_rnai.plotly.json").read_text())
        yvals = {round(s.get("y0", -99), 2) for s in wf["layout"].get("shapes", [])}
        assert {-0.25, -0.5} <= yvals, f"missing DEMETER2 reflines; got {yvals}"
