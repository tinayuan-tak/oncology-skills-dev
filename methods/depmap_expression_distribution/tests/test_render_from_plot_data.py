"""Figure Stage 2: render_from_plot_data draws the cellline-rna-distribution figures OFFLINE from
persisted plot_data — deterministic, no S3/cbg, no second live read.

The proof of the render-from-plot_data architecture: feed a synthetic plot_data frame (the exact
long-frame cli.emit_plot_data persists) + summary, and the SAME draw functions produce valid SVGs
without touching load_expression_files. A monkeypatched loader that RAISES proves no live read occurs.
"""

from __future__ import annotations

import sys
from pathlib import Path

METHODS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(METHODS_ROOT))

from methods.depmap_expression_distribution import cli as c
from methods.depmap_expression_distribution import figures as f


def _panel() -> tuple[dict, dict]:
    tpm, meta = {}, {}
    i = 1
    for lin, vals in {
        "Lung": [6.0, 6.4, 5.8, 6.1, 6.7],
        "Breast": [5.5, 5.1, 4.9, 5.3, 5.0],
        "Bowel": [0.2, 0.4, 0.1, 0.3, 0.5],
    }.items():
        for v in vals:
            mid = f"ACH-{i:06d}"
            tpm[mid] = float(v)
            meta[mid] = {"ModelID": mid, "OncotreeLineage": lin, "CCLEName": f"CL{i}_{lin}"}
            i += 1
    return tpm, meta


def _svg_ok(p: Path) -> bool:
    return p.exists() and p.stat().st_size > 0 and "<svg" in p.read_text()[:2000]


def test_renders_three_svgs_from_persisted_parquet(tmp_path, monkeypatch):
    tpm, meta = _panel()
    summary = c.compute_summary_stats(tpm, meta)

    # 1) persist plot_data exactly as card resolution (Stage 1) does
    src = tmp_path / "src"
    src.mkdir()
    c.emit_plot_data(tpm, meta, 1.0, src)
    parquet = src / "plot_data_expression.parquet"
    assert parquet.exists()

    # 2) NO live read allowed — any call to the S3 loader is a bug in the offline path
    monkeypatch.setattr(
        c, "load_expression_files", lambda *a, **k: (_ for _ in ()).throw(AssertionError("live read in offline render"))
    )

    # 3) render offline from the persisted parquet
    out = tmp_path / "out"
    descs = f.render_from_plot_data(parquet, summary, out, "MYGENE")

    assert _svg_ok(out / "figure_density_expression.svg")
    assert _svg_ok(out / "figure_lineage_strip_expression.svg")

    static_ids = {d["id"] for d in descs if not d.get("dynamic")}
    assert static_ids == {"density_expression", "lineage_strip_expression"}  # waterfall retired 2026-09-03
    primary = [d for d in descs if d.get("primary")]
    assert len(primary) == 1 and primary[0]["id"] == "density_expression"
    # any plotly descriptors returned are flagged dynamic (mirrors the skills _plotly_from wrapping)
    assert all(d.get("dynamic") for d in descs if d.get("type") == "plotly")


def test_returns_plotly_descriptors_with_dynamic_flag(tmp_path, monkeypatch):
    """Stage-3 parity: render_from_plot_data RETURNS the plotly-twin descriptors (dynamic:True), not
    just the SVGs — so it is an exact drop-in for the registry emitter (which appends them today)."""
    tpm, meta = _panel()
    summary = c.compute_summary_stats(tpm, meta)
    src = tmp_path / "src"
    src.mkdir()
    c.emit_plot_data(tpm, meta, 1.0, src)

    # deterministic plotly stub so the assertion is env-independent (real plotly may be absent)
    monkeypatch.setattr(
        c,
        "emit_plotly_specs",
        lambda *a, **k: [
            {"id": "density_expression", "path": "figure_density_expression.plotly.json", "type": "plotly"}
        ],
    )
    descs = f.render_from_plot_data(src / "plot_data_expression.parquet", summary, tmp_path / "out", "MYGENE")
    dyn = [d for d in descs if d.get("dynamic")]
    assert dyn and dyn[0]["path"].endswith(".plotly.json") and dyn[0]["dynamic"] is True


def test_accepts_dataframe_directly(tmp_path, monkeypatch):
    import pandas as pd

    tpm, meta = _panel()
    summary = c.compute_summary_stats(tpm, meta)
    src = tmp_path / "src"
    src.mkdir()
    c.emit_plot_data(tpm, meta, 1.0, src)
    df = pd.read_parquet(src / "plot_data_expression.parquet")

    monkeypatch.setattr(c, "load_expression_files", lambda *a, **k: (_ for _ in ()).throw(AssertionError("live read")))
    out = tmp_path / "out"
    f.render_from_plot_data(df, summary, out, "MYGENE")
    assert _svg_ok(out / "figure_density_expression.svg")


def test_missing_columns_raises(tmp_path):
    import pandas as pd

    df = pd.DataFrame({"model_id": ["ACH-1"]})  # no log2tpm
    try:
        f.render_from_plot_data(df, {}, tmp_path / "out", "MYGENE")
    except ValueError as e:
        assert "log2tpm" in str(e)
    else:
        raise AssertionError("expected ValueError on missing required column")
