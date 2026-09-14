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
import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CLI = REPO / "methods" / "depmap_expression_distribution" / "cli.py"
# Portable sibling root: was hardcoded to the author's /home/sagemaker-user checkout, so the
# guard below reported "not available" on every CI runner -- even though the workflow checks
# this sibling out and exports its root. `or` rather than a .get() default, so an EMPTY value
# falls back too instead of yielding Path("") == the CWD, which reads as a plausible wrong root.
CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT") or REPO.parent / "rnd-computational-biology-oncology-target-contracts"
)

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

        return np.frombuffer(base64.b64decode(v["bdata"]), dtype={"f8": "<f8", "f4": "<f4"}[v["dtype"]]).tolist()
    return list(v)


def _fixture():
    # log2(TPM+1) values spanning below-expressed, expressed, and highly-expressed bands.
    tpm = {f"ACH-{i:03d}": (i * 0.12) for i in range(60)}
    meta = {
        f"ACH-{i:03d}": {"CCLEName": f"CL{i}_TISSUE", "OncotreeLineage": ["Bowel", "Lung", "Pancreas", "Skin"][i % 4]}
        for i in range(60)
    }
    summary = {"n_cell_lines_evaluated": 60, "expression_class": "broadly_expressed"}
    return tpm, meta, summary


def test_emits_two_valid_plotly_specs():
    """density + lineage (waterfall retired 2026-09-03 — redundant with the annotated density)."""
    tpm, meta, summary = _fixture()
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        written = cli.emit_plotly_specs(tpm, meta, "KRAS", summary, out, CONTRACTS)
        ids = {w["id"] for w in written}
        assert ids == {"density_expression", "lineage_expression"}
        for w in written:
            obj = json.loads((out / w["path"]).read_text())
            assert "data" in obj and "layout" in obj and obj["data"], f"{w['id']} not a Plotly spec"
            assert w["type"] == "plotly"


def test_density_shades_three_expression_buckets():
    """Item 2: the density plot shades not-expressed / expressed / highly-expressed regions
    (vrects) behind the histogram — 3 rect shapes."""
    tpm, meta, summary = _fixture()
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        cli.emit_plotly_specs(tpm, meta, "KRAS", summary, out, CONTRACTS)
        dens = json.loads((out / "figure_density_expression.plotly.json").read_text())
        rects = [s for s in dens["layout"].get("shapes", []) if s.get("type") == "rect"]
        assert len(rects) >= 2, f"expected >=2 bucket rects, got {len(rects)}"


def test_lineage_plot_highlights_indication_lineage():
    """The lineage box highlights the indication's DepMap lineage (COADREAD→Bowel) in red."""
    tpm, meta, summary = _fixture()
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        cli.emit_plotly_specs(tpm, meta, "KRAS", summary, out, CONTRACTS, indication="COADREAD")
        ln = json.loads((out / "figure_lineage_expression.plotly.json").read_text())
        names = [t.get("name") for t in ln["data"]]
        assert "Bowel" in names
        reds = [t.get("name") for t in ln["data"] if (t.get("line") or {}).get("color") == "#cf2828"]
        assert reds == ["Bowel"], f"expected Bowel highlighted, got {reds}"


def test_no_drift_density_series_matches_input():
    """The chart series must equal the input tpm values — the interactive figure can't diverge from
    the data (or the SVG / plot_data_expression.parquet drawn from the same source)."""
    tpm, meta, summary = _fixture()
    expect = sorted(tpm.values())
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        cli.emit_plotly_specs(tpm, meta, "KRAS", summary, out, CONTRACTS)
        dens = json.loads((out / "figure_density_expression.plotly.json").read_text())
        assert sorted(_decode(dens["data"][0]["x"])) == expect  # raw scores, any order


def test_reference_lines_present_at_expression_thresholds():
    """The 1.0 (expressed) / 5.0 (highly-expressed) log2(TPM+1) reference lines mirror the SVG —
    the density draws them as vertical shapes."""
    tpm, meta, summary = _fixture()
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        cli.emit_plotly_specs(tpm, meta, "KRAS", summary, out, CONTRACTS)
        dens = json.loads((out / "figure_density_expression.plotly.json").read_text())
        xvals = {round(s.get("x0", -99), 2) for s in dens["layout"].get("shapes", [])}
        assert {1.0, 5.0} <= xvals, f"missing expression reflines on density; got {xvals}"
