"""Figure Stage 6 (card2 dependency-lineage-selectivity): plot_data persists on the verdict read, and
render_from_plot_data draws the forest_plot + lineage_strip OFFLINE from it — no S3/cbg, no second
live read (loader monkeypatched to RAISE). Parallel to the distribution-family proof cards.
"""

from __future__ import annotations

from pathlib import Path

from onc_methods.depmap_chronos import cli as c
from onc_methods.depmap_chronos import figures as f
from onc_methods.depmap_chronos import read as r


def _panel() -> tuple[dict, dict]:
    chronos, meta = {}, {}
    i = 1
    for lin, vals in {
        "Bowel": [-1.2, -1.4, -0.9, -1.1, -1.3],  # the COADREAD lineage (highlighted)
        "Lung": [-0.6, -0.5, -0.7, -0.4, -0.55],
        "Breast": [0.05, -0.1, 0.1, -0.05, 0.0],
    }.items():
        for v in vals:
            mid = f"ACH-{i:06d}"
            chronos[mid] = float(v)
            meta[mid] = {"ModelID": mid, "OncotreeLineage": lin, "CellLineName": f"CL{i}_{lin}"}
            i += 1
    return chronos, meta


def _svg_ok(p: Path) -> bool:
    return p.exists() and p.stat().st_size > 0 and "<svg" in p.read_text()[:2000]


def test_plot_data_persisted_on_read(tmp_path, monkeypatch):
    chronos, meta = _panel()
    monkeypatch.setattr(r._cli, "load_depmap_files", lambda release_pin, target_symbol: (chronos, meta, []))
    summary = r.read_lineage_selectivity("MYGENE", "COADREAD", plot_data_out=tmp_path)
    assert summary.get("enrichment_class")
    assert (tmp_path / "plot_data.parquet").exists()

    # verdict-inert: the summary is byte-identical with/without plot_data_out
    assert r.read_lineage_selectivity("MYGENE", "COADREAD") == r.read_lineage_selectivity(
        "MYGENE", "COADREAD", plot_data_out=tmp_path / "again"
    )


def test_renders_offline_from_persisted_parquet(tmp_path, monkeypatch):
    chronos, meta = _panel()
    src = tmp_path / "src"
    src.mkdir()
    c.emit_plot_data(chronos, meta, "Bowel", -1.0, src)
    assert (src / "plot_data.parquet").exists()

    monkeypatch.setattr(
        c, "load_depmap_files", lambda *a, **k: (_ for _ in ()).throw(AssertionError("live read in offline render"))
    )
    out = tmp_path / "out"
    descs = f.render_from_plot_data(src / "plot_data.parquet", {}, out, "MYGENE", "COADREAD")

    assert _svg_ok(out / "figure_forest_plot.svg")
    assert _svg_ok(out / "figure_lineage_strip.svg")
    assert {d["id"] for d in descs if not d.get("dynamic")} == {"forest_plot", "lineage_strip"}
    assert [d for d in descs if d.get("primary")][0]["id"] == "forest_plot"
    assert all(d.get("dynamic") for d in descs if d.get("type") == "plotly")


def test_returns_plotly_descriptors_with_dynamic_flag(tmp_path, monkeypatch):
    """Stage-3 parity: render RETURNS the plotly-twin descriptors (dynamic:True), an exact drop-in for
    the registry emitter. Env-independent via a deterministic plotly stub."""
    chronos, meta = _panel()
    src = tmp_path / "src"
    src.mkdir()
    c.emit_plot_data(chronos, meta, "Bowel", -1.0, src)
    monkeypatch.setattr(
        c,
        "emit_plotly_specs",
        lambda *a, **k: [{"id": "lineage_forest", "path": "figure_forest.plotly.json", "type": "plotly"}],
    )
    descs = f.render_from_plot_data(src / "plot_data.parquet", {}, tmp_path / "out", "MYGENE", "COADREAD")
    dyn = [d for d in descs if d.get("dynamic")]
    assert dyn and dyn[0]["path"].endswith(".plotly.json") and dyn[0]["dynamic"] is True


def test_missing_columns_raises(tmp_path):
    import pandas as pd

    df = pd.DataFrame({"cell_line_id": ["ACH-1"]})  # no chronos_score
    try:
        f.render_from_plot_data(df, {}, tmp_path / "out", "MYGENE", "COADREAD")
    except ValueError as e:
        assert "chronos_score" in str(e)
    else:
        raise AssertionError("expected ValueError on missing required column")
