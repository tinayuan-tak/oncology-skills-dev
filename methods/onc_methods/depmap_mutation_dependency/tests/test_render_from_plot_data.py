"""Figure Stage 6 (card3 mutation-stratified-dependency): plot_data persists on the verdict read, and
render_from_plot_data draws the mut-vs-WT strip + per-hotspot strip OFFLINE from it — no S3, no second
live read (loaders monkeypatched to RAISE)."""

from __future__ import annotations

from pathlib import Path

from onc_methods.depmap_mutation_dependency import cli as c
from onc_methods.depmap_mutation_dependency import figures as f
from onc_methods.depmap_mutation_dependency import read as r


def _panels() -> tuple[dict, dict, dict]:
    chronos, hot, dam, meta = {}, {}, {}, {}
    i = 1
    # mutant lines strongly dependent; WT lines not — a clear stratification signal
    for lin, (muts, wts) in {
        "Bowel": ([-1.4, -1.2, -1.3], [-0.2, -0.1]),
        "Lung": ([-1.1, -1.3], [-0.3, 0.0, -0.1]),
        "Breast": ([-1.2], [0.0, -0.05, 0.1]),
    }.items():
        for v in muts:
            mid = f"ACH-{i:06d}"
            chronos[mid] = float(v)
            hot[mid] = True
            dam[mid] = False
            meta[mid] = {"OncotreeLineage": lin, "CellLineName": f"CL{i}"}
            i += 1
        for v in wts:
            mid = f"ACH-{i:06d}"
            chronos[mid] = float(v)
            hot[mid] = False
            dam[mid] = False
            meta[mid] = {"OncotreeLineage": lin, "CellLineName": f"CL{i}"}
            i += 1
    return chronos, hot, dam, meta


def _svg_ok(p: Path) -> bool:
    return p.exists() and p.stat().st_size > 0 and "<svg" in p.read_text()[:2000]


def test_plot_data_persisted_on_read(tmp_path, monkeypatch):
    chronos, hot, dam, meta = _panels()
    monkeypatch.setattr(
        "onc_methods.depmap_chronos_distribution.cli.load_depmap_files",
        lambda release_pin, target_symbol: (chronos, meta, []),
    )
    monkeypatch.setattr(r._cli, "load_mutation_data", lambda release_pin, target_symbol: (hot, dam, []))
    summary = r.read_mutation_stratified_dependency("MYGENE", "COADREAD", plot_data_out=tmp_path)
    assert summary.get("mutation_stratification_class")
    assert (tmp_path / "plot_data.parquet").exists()


def test_renders_offline_from_persisted_parquet(tmp_path, monkeypatch):
    chronos, hot, dam, meta = _panels()
    summary = c.compute_mutation_stratification(chronos, hot, dam)
    src = tmp_path / "src"
    src.mkdir()
    c.emit_plot_data(chronos, hot, dam, meta, src)
    assert (src / "plot_data.parquet").exists()

    monkeypatch.setattr(
        c, "load_mutation_data", lambda *a, **k: (_ for _ in ()).throw(AssertionError("live read in offline render"))
    )
    out = tmp_path / "out"
    descs = f.render_from_plot_data(src / "plot_data.parquet", summary, out, "MYGENE", "COADREAD")
    assert _svg_ok(out / "figure_mut_vs_wt_strip.svg")
    assert _svg_ok(out / "figure_per_hotspot_chronos.svg")
    assert {d["id"] for d in descs if not d.get("dynamic")} == {"mut_vs_wt_strip", "per_hotspot_chronos"}
    assert [d for d in descs if d.get("primary")][0]["id"] == "mut_vs_wt_strip"
    assert all(d.get("dynamic") for d in descs if d.get("type") == "plotly")


def test_missing_columns_raises(tmp_path):
    import pandas as pd

    df = pd.DataFrame({"cell_line_id": ["ACH-1"], "chronos_score": [-1.0]})  # no is_hotspot_mutant
    try:
        f.render_from_plot_data(df, {}, tmp_path / "out", "MYGENE", "COADREAD")
    except ValueError as e:
        assert "is_hotspot_mutant" in str(e)
    else:
        raise AssertionError("expected ValueError on missing required column")
