"""Figure Stage 1+2 (RNAi/demeter): plot_data persists on the verdict read, and render_from_plot_data
draws the pan-cancer-rnai-dependency-distribution figures OFFLINE from it — no S3/cbg, no second
live read (loader monkeypatched to RAISE). Parallel to the chronos/expression proof cards.
"""

from __future__ import annotations

import sys
from pathlib import Path

METHODS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(METHODS_ROOT))

from methods.depmap_demeter_distribution import cli as c
from methods.depmap_demeter_distribution import figures as f
from methods.depmap_demeter_distribution import read as r


def _panel() -> tuple[dict, dict]:
    demeter, meta = {}, {}
    i = 1
    for lin, vals in {"Bowel": [-0.9, -1.0, -0.7, -0.8, -0.85],
                      "Lung": [-0.3, -0.35, -0.28, -0.4, -0.32],
                      "Breast": [0.02, -0.05, 0.05, 0.0, -0.02]}.items():
        for v in vals:
            mid = f"ACH-{i:06d}"
            demeter[mid] = float(v)
            meta[mid] = {"ModelID": mid, "OncotreeLineage": lin, "CCLEName": f"CL{i}_{lin}"}
            i += 1
    return demeter, meta


def _svg_ok(p: Path) -> bool:
    return p.exists() and p.stat().st_size > 0 and "<svg" in p.read_text()[:2000]


def test_plot_data_persisted_on_read(tmp_path, monkeypatch):
    demeter, meta = _panel()
    monkeypatch.setattr(r._cli, "load_rnai_files",
                        lambda release_pin, target_symbol: (demeter, meta, [], None))
    summary = r.read_pan_cancer_rnai_distribution("MYGENE", plot_data_out=tmp_path)
    assert summary.get("rnai_dependency_class") or summary.get("dependency_class")
    assert (tmp_path / "plot_data_rnai.parquet").exists()

    # verdict-inert: summary byte-identical with/without plot_data_out
    s_without = r.read_pan_cancer_rnai_distribution("MYGENE")
    assert s_without == r.read_pan_cancer_rnai_distribution("MYGENE", plot_data_out=tmp_path / "again")


def test_renders_offline_from_persisted_parquet(tmp_path, monkeypatch):
    demeter, meta = _panel()
    summary = c.compute_summary_stats(demeter, meta)
    src = tmp_path / "src"; src.mkdir()
    c.emit_plot_data(demeter, meta, -0.5, src)
    assert (src / "plot_data_rnai.parquet").exists()

    monkeypatch.setattr(c, "load_rnai_files",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("live read in offline render")))
    out = tmp_path / "out"
    descs = f.render_from_plot_data(src / "plot_data_rnai.parquet", summary, out, "MYGENE")

    assert _svg_ok(out / "figure_waterfall_rnai.svg")
    assert _svg_ok(out / "figure_histogram_kde_rnai.svg")
    assert {d["id"] for d in descs if not d.get("dynamic")} == {"waterfall_rnai", "histogram_kde_rnai"}
    assert [d for d in descs if d.get("primary")][0]["id"] == "waterfall_rnai"
    assert all(d.get("dynamic") for d in descs if d.get("type") == "plotly")


def test_missing_columns_raises(tmp_path):
    import pandas as pd
    df = pd.DataFrame({"model_id": ["ACH-1"]})  # no demeter2_score
    try:
        f.render_from_plot_data(df, {}, tmp_path / "out", "MYGENE")
    except ValueError as e:
        assert "demeter2_score" in str(e)
    else:
        raise AssertionError("expected ValueError on missing required column")


def test_returns_plotly_descriptors_with_dynamic_flag(tmp_path, monkeypatch):
    """Stage-3 parity: render_from_plot_data RETURNS the plotly-twin descriptors (dynamic:True), not
    just the SVGs — so it is an exact drop-in for the registry emitter (which appends them today)."""
    demeter, meta = _panel()
    summary = c.compute_summary_stats(demeter, meta)
    src = tmp_path / "src"; src.mkdir()
    c.emit_plot_data(demeter, meta, -0.5, src)

    monkeypatch.setattr(c, "emit_plotly_specs",
                        lambda *a, **k: [{"id": "waterfall_rnai",
                                          "path": "figure_waterfall_rnai.plotly.json", "type": "plotly"}])
    descs = f.render_from_plot_data(src / "plot_data_rnai.parquet", summary, tmp_path / "out", "MYGENE")
    dyn = [d for d in descs if d.get("dynamic")]
    assert dyn and dyn[0]["path"].endswith(".plotly.json") and dyn[0]["dynamic"] is True
