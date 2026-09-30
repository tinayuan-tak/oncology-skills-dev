"""Figure Stage 6 (normal-tissue-liability-gtex): the atlas persists on the verdict read, and
render_liability_from_plot_data draws the per-tissue liability bar OFFLINE from it — no S3, no second
live read (read_all_normal_tissues monkeypatched to RAISE)."""

from __future__ import annotations

from pathlib import Path

from onc_methods.tcga_gtex_expression_distribution import cli as c
from onc_methods.tcga_gtex_expression_distribution import figures as f
from onc_methods.tcga_gtex_expression_distribution import read as r

_ATLAS = {"Liver": [5.5, 6.0, 5.8], "Brain": [0.5, 0.7, 0.6], "Colon": [3.0, 3.2, 2.9], "Lung": [1.2, 1.5, 1.1]}


def _write_atlas(d: Path) -> Path:
    import pandas as pd

    d.mkdir(parents=True, exist_ok=True)
    rows = [{"tissue": t, "log2_tpm": float(v)} for t, vals in _ATLAS.items() for v in vals]
    out = d / "plot_data_normal_tissue_atlas.parquet"
    pd.DataFrame(rows, columns=["tissue", "log2_tpm"]).to_parquet(out, index=False)
    return out


def _svg_ok(p: Path) -> bool:
    return p.exists() and p.stat().st_size > 0 and "<svg" in p.read_text()[:2000]


def test_atlas_persisted_on_read(tmp_path, monkeypatch):
    monkeypatch.setattr(r, "read_all_normal_tissues", lambda target: dict(_ATLAS))
    summary = r.read_normal_tissue_liability("MYGENE", plot_data_out=tmp_path)
    assert summary.get("liability_class")
    assert (tmp_path / "plot_data_normal_tissue_atlas.parquet").exists()


def test_renders_offline_from_persisted_parquet(tmp_path, monkeypatch):
    pd_path = _write_atlas(tmp_path / "src")
    monkeypatch.setattr(
        c._read,
        "read_all_normal_tissues",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("live read in offline render")),
    )
    out = tmp_path / "out"
    descs = f.render_liability_from_plot_data(pd_path, {}, out, "MYGENE")
    assert _svg_ok(out / "figure_normal_tissue_liability.svg")
    assert {d["id"] for d in descs if not d.get("dynamic")} == {"normal_tissue_liability_atlas"}
    assert descs[0]["primary"] is True
    assert all(d.get("dynamic") for d in descs if d.get("type") == "plotly")


def test_missing_columns_raises(tmp_path):
    import pandas as pd

    df = pd.DataFrame({"tissue": ["Liver"]})  # no log2_tpm
    try:
        f.render_liability_from_plot_data(df, {}, tmp_path / "out", "MYGENE")
    except ValueError as e:
        assert "log2_tpm" in str(e)
    else:
        raise AssertionError("expected ValueError on missing required column")
