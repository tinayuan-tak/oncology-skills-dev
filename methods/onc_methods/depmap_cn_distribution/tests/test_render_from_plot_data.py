"""Figure Stage 1+2 (copy-number): plot_data persists on the verdict read, and render_from_plot_data
draws the copy-number-distribution figures OFFLINE from it — no S3/cbg, no second live read (loader
monkeypatched to RAISE). Parallel to the expression/chronos/rnai proof cards.
"""

from __future__ import annotations

from pathlib import Path

from onc_methods.depmap_cn_distribution import cli as c
from onc_methods.depmap_cn_distribution import figures as f
from onc_methods.depmap_cn_distribution import read as r


def _panel() -> tuple[dict, dict]:
    cn, meta = {}, {}
    i = 1
    for lin, vals in {
        "Breast": [3.2, 2.8, 3.5, 2.9, 3.0],  # amplified
        "Lung": [1.0, 1.1, 0.95, 1.05, 1.0],  # neutral
        "Bowel": [0.4, 0.35, 0.5, 0.42, 0.38],
    }.items():  # deleted
        for v in vals:
            mid = f"ACH-{i:06d}"
            cn[mid] = float(v)
            meta[mid] = {"ModelID": mid, "OncotreeLineage": lin, "CCLEName": f"CL{i}_{lin}"}
            i += 1
    return cn, meta


def _svg_ok(p: Path) -> bool:
    return p.exists() and p.stat().st_size > 0 and "<svg" in p.read_text()[:2000]


def test_plot_data_persisted_on_read(tmp_path, monkeypatch):
    cn, meta = _panel()
    monkeypatch.setattr(r._cli, "load_cn_files", lambda release_pin, target_symbol: (cn, meta, "wes", []))
    summary = r.read_cn_distribution("MYGENE", plot_data_out=tmp_path)
    assert summary.get("copy_number_class")
    assert (tmp_path / "plot_data_cn.parquet").exists()

    s_without = r.read_cn_distribution("MYGENE")
    assert s_without == r.read_cn_distribution("MYGENE", plot_data_out=tmp_path / "again")


def test_renders_offline_from_persisted_parquet(tmp_path, monkeypatch):
    cn, meta = _panel()
    summary = c.compute_summary_stats(cn, meta, assay_used="wes")
    src = tmp_path / "src"
    src.mkdir()
    c.emit_plot_data(cn, meta, src)
    assert (src / "plot_data_cn.parquet").exists()

    monkeypatch.setattr(
        c, "load_cn_files", lambda *a, **k: (_ for _ in ()).throw(AssertionError("live read in offline render"))
    )
    out = tmp_path / "out"
    descs = f.render_from_plot_data(src / "plot_data_cn.parquet", summary, out, "MYGENE")

    assert _svg_ok(out / "figure_density_cn.svg")
    assert _svg_ok(out / "figure_waterfall_cn.svg")
    assert _svg_ok(out / "figure_lineage_strip_cn.svg")
    assert {d["id"] for d in descs if not d.get("dynamic")} == {"density_cn", "waterfall_cn", "lineage_strip_cn"}
    assert [d for d in descs if d.get("primary")][0]["id"] == "density_cn"
    assert all(d.get("dynamic") for d in descs if d.get("type") == "plotly")


def test_missing_columns_raises(tmp_path):
    import pandas as pd

    df = pd.DataFrame({"model_id": ["ACH-1"]})  # no relative_cn
    try:
        f.render_from_plot_data(df, {}, tmp_path / "out", "MYGENE")
    except ValueError as e:
        assert "relative_cn" in str(e)
    else:
        raise AssertionError("expected ValueError on missing required column")


def test_returns_plotly_descriptors_with_dynamic_flag(tmp_path, monkeypatch):
    """Stage-3 parity + copy-number plotly-twin backfill: render_from_plot_data RETURNS the plotly-twin
    descriptors (dynamic:True), not just the SVGs — the copy-number twin landed with this migration
    (was the FIGURE_CATALOG parity gap). Env-independent via a deterministic plotly stub."""
    cn, meta = _panel()
    summary = c.compute_summary_stats(cn, meta, assay_used="wes")
    src = tmp_path / "src"
    src.mkdir()
    c.emit_plot_data(cn, meta, src)

    monkeypatch.setattr(
        c,
        "emit_plotly_specs",
        lambda *a, **k: [{"id": "density_cn", "path": "figure_density_cn.plotly.json", "type": "plotly"}],
    )
    descs = f.render_from_plot_data(src / "plot_data_cn.parquet", summary, tmp_path / "out", "MYGENE")
    dyn = [d for d in descs if d.get("dynamic")]
    assert dyn and dyn[0]["path"].endswith(".plotly.json") and dyn[0]["dynamic"] is True


def test_cn_plotly_twin_writes_json(tmp_path):
    """The new copy-number plotly twin actually renders three .plotly.json specs from the in-memory
    frame (density / waterfall / per-lineage box). Skipped where plotly is unavailable."""
    import importlib.util

    if importlib.util.find_spec("plotly") is None:
        import pytest

        pytest.skip("plotly not installed")
    cn, meta = _panel()
    summary = c.compute_summary_stats(cn, meta, assay_used="wes")
    out = tmp_path / "out"
    out.mkdir()
    from onc_methods.depmap_cn_distribution.cli import DEFAULT_TARGET_CONTRACTS

    written = c.emit_plotly_specs(cn, meta, "MYGENE", summary, out, DEFAULT_TARGET_CONTRACTS)
    ids = {w["id"] for w in written}
    assert ids == {"density_cn", "waterfall_cn", "lineage_strip_cn"}
    for w in written:
        assert (out / w["path"]).exists() and (out / w["path"]).stat().st_size > 0
