"""emit_plotly_specs (dynamic-dashboard Phase A) for depmap_expression_distribution.

Sibling of the depmap_chronos_distribution Plotly test (PR #49). The interactive Plotly specs are
built from the SAME in-memory tpm_by_model the matplotlib SVGs + plot_data_expression.parquet use —
so they cannot drift from the static figure or the parquet. These tests (no S3 — synthetic input)
pin: valid Plotly specs are written, their series equal the input (the no-drift guarantee), and the
expression reflines (1.0 expressed / 5.0 highly-expressed) mirror the SVGs. Plotly is optional at
emit time; if unavailable the method still emits SVGs.
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
CLI = REPO / "methods" / "depmap_expression_distribution" / "cli.py"
CONTRACTS = Path("/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")

pytest.importorskip("plotly", reason="plotly not installed in this env")


def _load():
    spec = importlib.util.spec_from_file_location("expr_cli", CLI)
    m = importlib.util.module_from_spec(spec)
    sys.modules["expr_cli"] = m
    spec.loader.exec_module(m)
    return m


cli = _load()


def _decode(v):
    """Plotly to_json() encodes numpy arrays as {'dtype','bdata'} base64. Decode either form to a
    plain float list so the no-drift check compares values, not serialization form."""
    if isinstance(v, dict) and "bdata" in v:
        import numpy as np
        return np.frombuffer(base64.b64decode(v["bdata"]),
                             dtype={"f8": "<f8", "f4": "<f4"}[v["dtype"]]).tolist()
    return list(v)


def _fixture():
    # log2(TPM+1) values spanning below-expressed, expressed, and highly-expressed bands.
    tpm = {f"ACH-{i:03d}": (i * 0.12) for i in range(60)}
    meta = {f"ACH-{i:03d}": {"CCLEName": f"CL{i}_TISSUE",
                             "OncotreeLineage": ["Bowel", "Lung", "Pancreas", "Skin"][i % 4]}
            for i in range(60)}
    summary = {"n_cell_lines_evaluated": 60, "expression_class": "broadly_expressed"}
    return tpm, meta, summary


def test_emits_two_valid_plotly_specs():
    tpm, meta, summary = _fixture()
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        written = cli.emit_plotly_specs(tpm, meta, "KRAS", summary, out, CONTRACTS)
        ids = {w["id"] for w in written}
        assert ids == {"density_expression", "waterfall_expression"}
        for w in written:
            obj = json.loads((out / w["path"]).read_text())
            assert "data" in obj and "layout" in obj and obj["data"], f"{w['id']} not a Plotly spec"
            assert w["type"] == "plotly"


def test_no_drift_density_and_waterfall_series_match_input():
    """The chart series must equal the input tpm values — the interactive figure can't diverge from
    the data (or the SVG / plot_data_expression.parquet drawn from the same source)."""
    tpm, meta, summary = _fixture()
    expect = sorted(tpm.values())
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        cli.emit_plotly_specs(tpm, meta, "KRAS", summary, out, CONTRACTS)
        dens = json.loads((out / "figure_density_expression.plotly.json").read_text())
        assert sorted(_decode(dens["data"][0]["x"])) == expect     # raw scores, any order
        wf = json.loads((out / "figure_waterfall_expression.plotly.json").read_text())
        assert _decode(wf["data"][0]["y"]) == expect               # bars sorted ascending


def test_reference_lines_present_at_expression_thresholds():
    """The 1.0 (expressed) / 5.0 (highly-expressed) log2(TPM+1) reference lines mirror the SVGs —
    density draws them as vertical shapes, waterfall as horizontal shapes."""
    tpm, meta, summary = _fixture()
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        cli.emit_plotly_specs(tpm, meta, "KRAS", summary, out, CONTRACTS)
        dens = json.loads((out / "figure_density_expression.plotly.json").read_text())
        xvals = {round(s.get("x0", -99), 2) for s in dens["layout"].get("shapes", [])}
        assert {1.0, 5.0} <= xvals, f"missing expression reflines on density; got {xvals}"
        wf = json.loads((out / "figure_waterfall_expression.plotly.json").read_text())
        yvals = {round(s.get("y0", -99), 2) for s in wf["layout"].get("shapes", [])}
        assert {1.0, 5.0} <= yvals, f"missing expression reflines on waterfall; got {yvals}"
