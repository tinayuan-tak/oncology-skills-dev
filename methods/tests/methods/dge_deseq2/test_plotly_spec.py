"""emit_plotly_specs (dynamic-dashboard Phase A) for dge_deseq2.

Sibling of the depmap_chronos / depmap_expression Plotly tests (PRs #49/#50). Unlike those two
(pan-cancer distributions), dge_deseq2's figures are tumor-vs-normal: a box+strip across the
present sample GROUPS (tumor / adjacent / GTEx) + a forest of the log2FC CONTRASTS. Both Plotly
specs are built from the SAME in-memory per_sample_data + contrasts the matplotlib SVGs use — so
they cannot drift from the static figure. No S3, no R — synthetic per_sample_data. Plotly is
optional at emit time; if unavailable the method still emits SVGs.
"""

from __future__ import annotations

import base64
import importlib
import json
import os
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("plotly", reason="plotly not installed in this env")

emit = importlib.import_module("onc_methods.dge_deseq2.emit")
# Portable sibling root: was hardcoded to the author's /home/sagemaker-user checkout, so the
# guard below reported "not available" on every CI runner -- even though the workflow checks
# this sibling out and exports its root. `or` rather than a .get() default, so an EMPTY value
# falls back too instead of yielding Path("") == the CWD, which reads as a plausible wrong root.
CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT")
    or Path(__file__).resolve().parents[3].parent / "rnd-computational-biology-oncology-target-contracts"
)


def _decode(v):
    """Plotly to_json() encodes numpy arrays as {'dtype','bdata'} base64. Decode either form to a
    plain float list so the no-drift check compares values, not serialization form."""
    if isinstance(v, dict) and "bdata" in v:
        import numpy as np

        return np.frombuffer(base64.b64decode(v["bdata"]), dtype={"f8": "<f8", "f4": "<f4"}[v["dtype"]]).tolist()
    return list(v)


def _fixture():
    per_sample = {
        "tumor_samples": [{"sample_id": f"T{i}", "log2_cpm": 6.0 + i * 0.1} for i in range(40)],
        "adjacent_samples": [{"sample_id": f"A{i}", "log2_cpm": 3.0 + i * 0.1} for i in range(20)],
        "gtex_samples": [{"sample_id": f"G{i}", "log2_cpm": 2.5 + i * 0.05} for i in range(30)],
        "gene_ensembl_id": "ENSG00000133703",
        "gtex_tissue": "Colon",
    }
    contrasts = [
        {"label": "tumor\nvs adj-normal", "log2_fc": 1.8, "q_value": 1e-12},
        {"label": "tumor\nvs GTEx-normal", "log2_fc": 2.4, "q_value": 3e-6},
    ]
    return per_sample, contrasts


def test_emits_two_valid_plotly_specs():
    per_sample, contrasts = _fixture()
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        written = emit.emit_plotly_specs(per_sample, contrasts, "KRAS", "COADREAD", out, CONTRACTS)
        ids = {w["id"] for w in written}
        assert ids == {"tumor_vs_normal_groups", "tumor_vs_normal_contrasts"}
        for w in written:
            obj = json.loads((out / w["path"]).read_text())
            assert "data" in obj and "layout" in obj and obj["data"], f"{w['id']} not a Plotly spec"
            assert w["type"] == "plotly"


def test_no_drift_group_boxes_and_contrasts_match_input():
    """The box traces must carry the exact per-sample log2_cpm arrays, and the forest bars the exact
    contrast log2FCs — the interactive figure can't diverge from the data the SVG draws."""
    per_sample, contrasts = _fixture()
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        emit.emit_plotly_specs(per_sample, contrasts, "KRAS", "COADREAD", out, CONTRACTS)
        groups = json.loads((out / "figure_tumor_vs_normal_groups.plotly.json").read_text())
        # one box trace per present group, in _GROUP_STYLE order (tumor, adjacent, gtex)
        assert len(groups["data"]) == 3
        assert _decode(groups["data"][0]["y"]) == [s["log2_cpm"] for s in per_sample["tumor_samples"]]
        assert _decode(groups["data"][2]["y"]) == [s["log2_cpm"] for s in per_sample["gtex_samples"]]
        forest = json.loads((out / "figure_tumor_vs_normal_contrasts.plotly.json").read_text())
        assert _decode(forest["data"][0]["x"]) == [c["log2_fc"] for c in contrasts]


def test_contrast_reference_lines_present():
    """The forest's 0 / ±0.5 log2FC reference lines mirror the SVG forest (vertical shapes)."""
    per_sample, contrasts = _fixture()
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        emit.emit_plotly_specs(per_sample, contrasts, "KRAS", "COADREAD", out, CONTRACTS)
        forest = json.loads((out / "figure_tumor_vs_normal_contrasts.plotly.json").read_text())
        xvals = {round(s.get("x0", -99), 2) for s in forest["layout"].get("shapes", [])}
        assert {0.0, 0.5, -0.5} <= xvals, f"missing contrast reflines; got {xvals}"


def test_degrades_when_no_samples_or_plotly_absent():
    """No per_sample_data (or an empty group set) → [] and no files (the SVG placeholder path owns
    the empty case; the Plotly emitter simply produces nothing)."""
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        assert emit.emit_plotly_specs(None, [], "KRAS", "COADREAD", out, CONTRACTS) == []
        empty = {"tumor_samples": [], "adjacent_samples": [], "gtex_samples": []}
        assert emit.emit_plotly_specs(empty, [], "KRAS", "COADREAD", out, CONTRACTS) == []
        assert not list(out.iterdir())


def test_basename_keys_the_output_so_call_sites_dont_collide():
    """The tumor-vs-adjacent card (basename='tumor_vs_adjacent') writes distinct files from the
    3-group selectivity card (default basename), so both can emit into the same package dir."""
    per_sample, contrasts = _fixture()
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        written = emit.emit_plotly_specs(
            per_sample, contrasts[:1], "KRAS", "COADREAD", out, CONTRACTS, basename="tumor_vs_adjacent"
        )
        assert {w["path"] for w in written} == {
            "figure_tumor_vs_adjacent_groups.plotly.json",
            "figure_tumor_vs_adjacent_contrasts.plotly.json",
        }
