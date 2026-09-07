"""Figure emitters for cellline-protein-abundance (Gygi TMT MS) — Slice 7 (protein viz).

The card declared density + lineage-strip figures + a per_cell_line_protein_abundance_with_lineage_tags
plot_data but the method emitted none (FIGURE_DEBT). This adds them, mirroring
depmap_expression_distribution. Tests (no S3 — synthetic abundance dict) pin: SVGs + plot_data +
valid Plotly specs are written, and the Plotly series equal the input (no-drift). Plotly/scipy are
optional at emit time; the SVG path degrades gracefully.
"""

from __future__ import annotations

import base64
import importlib
import json
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

cli = importlib.import_module("methods.depmap_protein_abundance.cli")
CONTRACTS = Path("/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")


def _decode(v):
    if isinstance(v, dict) and "bdata" in v:
        import numpy as np

        return np.frombuffer(base64.b64decode(v["bdata"]), dtype={"f8": "<f8", "f4": "<f4"}[v["dtype"]]).tolist()
    return list(v)


def _fixture():
    abund = {f"ACH-{i:04d}": 2.0 + i * 0.03 for i in range(80)}
    lin = {f"ACH-{i:04d}": ["Bowel", "Lung", "Skin", "Pancreas"][i % 4] for i in range(80)}
    summary = cli.compute_summary("EGFR", abund, lin, n_panel=200)
    return abund, lin, summary


def test_svg_and_plot_data_emitted():
    abund, lin, summary = _fixture()
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        cli.emit_density_protein(abund, "EGFR", summary, out, CONTRACTS)
        cli.emit_lineage_strip_protein(abund, lin, "EGFR", summary, out, CONTRACTS)
        pd_path = cli.emit_plot_data_protein(abund, lin, out)
        names = {p.name for p in out.iterdir()}
        assert "figure_density_protein_abundance.svg" in names
        assert "figure_lineage_strip_protein.svg" in names
        assert pd_path.name == "plot_data_protein_abundance.parquet"
        import pandas as pd

        df = pd.read_parquet(pd_path)
        assert set(df.columns) == {"model_id", "lineage", "log2_abundance"}
        assert len(df) == len(abund)


def test_plotly_specs_valid_and_no_drift():
    pytest.importorskip("plotly")
    abund, lin, summary = _fixture()
    expect = sorted(abund.values())
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        written = cli.emit_plotly_specs(abund, lin, "EGFR", summary, out, CONTRACTS, indication="COADREAD")
        # item #2: added the per-lineage box (mirrors the RNA lineage plot)
        assert {w["id"] for w in written} == {
            "density_protein_abundance",
            "waterfall_protein_abundance",
            "lineage_protein_abundance",
        }
        for w in written:
            obj = json.loads((out / w["path"]).read_text())
            assert obj["data"] and "layout" in obj and w["type"] == "plotly"
        # no-drift: waterfall bars are the sorted abundance; density x is the raw values
        wf = json.loads((out / "figure_waterfall_protein_abundance.plotly.json").read_text())
        assert _decode(wf["data"][0]["y"]) == expect
        dens = json.loads((out / "figure_density_protein_abundance.plotly.json").read_text())
        assert sorted(_decode(dens["data"][0]["x"])) == expect
        # per-lineage box: one Box trace per n>=5 lineage; the indication lineage (Bowel) is highlighted red
        lin_fig = json.loads((out / "figure_lineage_protein_abundance.plotly.json").read_text())
        assert lin_fig["data"] and all(t.get("type") == "box" for t in lin_fig["data"])
        assert "Bowel highlighted" in lin_fig["layout"]["title"]["text"]
        bowel = [t for t in lin_fig["data"] if t.get("name") == "Bowel"]
        assert bowel and bowel[0]["line"]["color"] == "#cf2828"  # highlighted red


def test_empty_abundance_degrades_gracefully():
    """A target not quantified in the MS panel → placeholder SVG (no crash) + [] plotly, no parquet rows."""
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        p = cli.emit_density_protein({}, "GHOST", {"n_cell_lines_evaluated": 0}, out, CONTRACTS)
        assert p.exists()  # placeholder written, no exception
        assert cli.emit_plotly_specs({}, {}, "GHOST", {}, out, CONTRACTS) == []


def test_substrate_reads_are_cached(tmp_path):
    """Retrieval-opt #3: the large target-independent substrates (Gygi matrix, Model.csv, sidecar)
    are read ONCE per process. A second _read_csv/_read_parquet for the same path is a cache HIT,
    so the summary pass + figure pass don't each do a full read."""
    import pandas as pd

    cli._cached_csv.cache_clear()
    cli._read_parquet.cache_clear()

    csv_p = tmp_path / "matrix.csv"
    pd.DataFrame({"ModelID": ["ACH-1", "ACH-2"], "Q1": [1.0, 2.0]}).to_csv(csv_p, index=False)
    a = cli._read_csv(str(csv_p), cli.S3_BUCKET, cli.MATRIX_KEY)  # no kwargs → cached path
    b = cli._read_csv(str(csv_p), cli.S3_BUCKET, cli.MATRIX_KEY)
    ci = cli._cached_csv.cache_info()
    assert ci.hits >= 1, f"second identical CSV read should be a cache hit; got {ci}"
    assert a is b, "cached read must return the SAME object (read-only contract)"

    pq_p = tmp_path / "sidecar.parquet"
    pd.DataFrame({"hgnc_primary_symbol_at_resolution": ["EGFR"], "native_row_key": ["P00533"]}).to_parquet(
        pq_p, index=False
    )
    cli._read_parquet(str(pq_p), cli.S3_BUCKET, cli.SIDECAR_KEY)
    cli._read_parquet(str(pq_p), cli.S3_BUCKET, cli.SIDECAR_KEY)
    assert cli._read_parquet.cache_info().hits >= 1


def test_read_csv_with_kwargs_bypasses_cache(tmp_path):
    """The kwargs path (usecols/dtype) must NOT route through the no-arg cache (unhashable kwargs
    + column-projected reads are a different result)."""
    import pandas as pd

    p = tmp_path / "m.csv"
    pd.DataFrame({"a": [1], "b": [2]}).to_csv(p, index=False)
    df = cli._read_csv(str(p), cli.S3_BUCKET, cli.MODEL_KEY, usecols=["a"])
    assert list(df.columns) == ["a"]
