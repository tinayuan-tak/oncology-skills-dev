"""emit_plotly_specs (dynamic-dashboard Phase A) for depmap_chronos_distribution.

The interactive Plotly specs are SIBLINGS to the matplotlib SVGs, built from the SAME in-memory
chronos_by_model — so they cannot drift from the static figure or plot_data.parquet. These tests
(no S3 — synthetic input) pin: valid Plotly specs are written, and their series equal the input
(the no-drift guarantee). Plotly is optional at emit time; if unavailable the method still emits SVGs.
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
CLI = REPO / "onc_methods" / "depmap_chronos_distribution" / "cli.py"
# Portable sibling root: was hardcoded to the author's /home/sagemaker-user checkout, so the
# guard below reported "not available" on every CI runner -- even though the workflow checks
# this sibling out and exports its root. `or` rather than a .get() default, so an EMPTY value
# falls back too instead of yielding Path("") == the CWD, which reads as a plausible wrong root.
CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT") or REPO.parent / "rnd-computational-biology-oncology-target-contracts"
)

pytest.importorskip("plotly", reason="plotly not installed in this env")


def _load():
    spec = importlib.util.spec_from_file_location("chr_cli", CLI)
    m = importlib.util.module_from_spec(spec)
    sys.modules["chr_cli"] = m
    spec.loader.exec_module(m)
    return m


cli = _load()


def _decode(v):
    """Plotly to_json() encodes numpy arrays as {'dtype','bdata'} base64. Decode either form to a
    plain float list so the no-drift check compares values, not serialization form."""
    if isinstance(v, dict) and "bdata" in v:
        import numpy as np

        return np.frombuffer(base64.b64decode(v["bdata"]), dtype={"f8": "<f8", "f4": "<f4"}[v["dtype"]]).tolist()
    return list(v)


def _fixture():
    chronos = {f"ACH-{i:03d}": (-2.5 + i * 0.05) for i in range(60)}
    meta = {
        f"ACH-{i:03d}": {"CellLineName": f"CL{i}", "OncotreeLineage": ["Bowel", "Lung", "Pancreas", "Skin"][i % 4]}
        for i in range(60)
    }
    summary = {
        "n_cell_lines_evaluated": 60,
        "median_chronos_panel": -0.4,
        "chronos_iqr": 0.8,
        "fraction_strongly_dependent": 0.15,
        "distribution_shape": "bimodal",
    }
    return chronos, meta, summary


def test_emits_two_valid_plotly_specs():
    chronos, meta, summary = _fixture()
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        written = cli.emit_plotly_specs(chronos, meta, "KRAS", summary, out, CONTRACTS)
        ids = {w["id"] for w in written}
        assert ids == {"waterfall", "histogram_kde"}
        for w in written:
            obj = json.loads((out / w["path"]).read_text())
            assert "data" in obj and "layout" in obj and obj["data"], f"{w['id']} not a Plotly spec"
            assert w["type"] == "plotly"


def test_no_drift_waterfall_and_histogram_series_match_input():
    """The chart series must equal the input chronos values — the interactive figure can't diverge
    from the data (or the SVG / plot_data.parquet drawn from the same source)."""
    chronos, meta, summary = _fixture()
    expect = sorted(chronos.values())
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        cli.emit_plotly_specs(chronos, meta, "KRAS", summary, out, CONTRACTS)
        wf = json.loads((out / "figure_waterfall.plotly.json").read_text())
        assert _decode(wf["data"][0]["y"]) == expect  # bars sorted ascending
        hist = json.loads((out / "figure_histogram_kde.plotly.json").read_text())
        assert sorted(_decode(hist["data"][0]["x"])) == expect  # raw scores, any order


def test_reference_lines_present_at_dependency_thresholds():
    """The 0 / -0.5 / -1.0 Chronos reference lines mirror the SVG (shape lines in the layout)."""
    chronos, meta, summary = _fixture()
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        cli.emit_plotly_specs(chronos, meta, "KRAS", summary, out, CONTRACTS)
        wf = json.loads((out / "figure_waterfall.plotly.json").read_text())
        yvals = {round(s.get("y0", -99), 2) for s in wf["layout"].get("shapes", [])}
        assert {0.0, -0.5, -1.0} <= yvals, f"missing dependency reflines; got {yvals}"
