"""Figure Stage 1+2 (chronos): plot_data persists on the verdict read, and render_from_plot_data
draws the pan-cancer-crispr-dependency-distribution figures OFFLINE from it — no S3/cbg, no second
live read (loader monkeypatched to RAISE). Parallel to the expression proof card.
"""

from __future__ import annotations

from pathlib import Path

from onc_methods.depmap_chronos_distribution import cli as c
from onc_methods.depmap_chronos_distribution import figures as f
from onc_methods.depmap_chronos_distribution import read as r


def _panel() -> tuple[dict, dict]:
    chronos, meta = {}, {}
    i = 1
    for lin, vals in {
        "Bowel": [-1.2, -1.4, -0.9, -1.1, -1.3],
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
    summary = r.read_pan_cancer_distribution("MYGENE", plot_data_out=tmp_path)
    assert summary["dependency_class"]  # core summary still produced
    assert (tmp_path / "plot_data.parquet").exists()

    # verdict-inert: summary byte-identical with/without plot_data_out
    s_without = r.read_pan_cancer_distribution("MYGENE")
    assert s_without == r.read_pan_cancer_distribution("MYGENE", plot_data_out=tmp_path / "again")


def test_renders_offline_from_persisted_parquet(tmp_path, monkeypatch):
    chronos, meta = _panel()
    summary = c.compute_summary_stats(chronos, meta)
    src = tmp_path / "src"
    src.mkdir()
    c.emit_plot_data(chronos, meta, -1.0, src)
    assert (src / "plot_data.parquet").exists()

    # NO live read allowed on the offline render path
    monkeypatch.setattr(
        c, "load_depmap_files", lambda *a, **k: (_ for _ in ()).throw(AssertionError("live read in offline render"))
    )
    out = tmp_path / "out"
    descs = f.render_from_plot_data(src / "plot_data.parquet", summary, out, "MYGENE")

    assert _svg_ok(out / "figure_waterfall.svg")
    assert _svg_ok(out / "figure_histogram_kde.svg")
    ids = {d["id"] for d in descs if not d.get("dynamic")}
    assert ids == {"waterfall", "histogram_kde"}
    assert [d for d in descs if d.get("primary")][0]["id"] == "waterfall"
    assert all(d.get("dynamic") for d in descs if d.get("type") == "plotly")


def test_missing_columns_raises(tmp_path):
    import pandas as pd

    df = pd.DataFrame({"cell_line_id": ["ACH-1"]})  # no chronos_score
    try:
        f.render_from_plot_data(df, {}, tmp_path / "out", "MYGENE")
    except ValueError as e:
        assert "chronos_score" in str(e)
    else:
        raise AssertionError("expected ValueError on missing required column")


def test_returns_plotly_descriptors_with_dynamic_flag(tmp_path, monkeypatch):
    """Stage-3 parity: render_from_plot_data RETURNS the plotly-twin descriptors (dynamic:True), not
    just the SVGs — so it is an exact drop-in for the registry emitter (which appends them today)."""
    chronos, meta = _panel()
    summary = c.compute_summary_stats(chronos, meta)
    src = tmp_path / "src"
    src.mkdir()
    c.emit_plot_data(chronos, meta, -1.0, src)

    # deterministic plotly stub so the assertion is env-independent (real plotly may be absent)
    monkeypatch.setattr(
        c,
        "emit_plotly_specs",
        lambda *a, **k: [{"id": "waterfall", "path": "figure_waterfall.plotly.json", "type": "plotly"}],
    )
    descs = f.render_from_plot_data(src / "plot_data.parquet", summary, tmp_path / "out", "MYGENE")
    dyn = [d for d in descs if d.get("dynamic")]
    assert dyn and dyn[0]["path"].endswith(".plotly.json") and dyn[0]["dynamic"] is True
