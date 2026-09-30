"""Figure Stage 6 (tumor-rna-distribution): plot_data persists on the verdict read, and
render_from_plot_data draws the per-sample tumor-vs-normal figure OFFLINE from it — no recount3/S3,
no second live read (sample readers monkeypatched to RAISE). The expression/selectivity family's
draws are vector-driven (cli.emit_svg presampled=), unlike the DepMap dict-arg family.
"""

from __future__ import annotations

from pathlib import Path

from onc_methods.tcga_gtex_expression_distribution import cli as c
from onc_methods.tcga_gtex_expression_distribution import figures as f
from onc_methods.tcga_gtex_expression_distribution import read as r

_TUMOR = [6.0, 6.3, 5.8, 6.5, 5.6, 6.1, 5.9, 6.2]
_NORMAL = [1.2, 1.5, 0.9, 1.1, 1.3, 1.0]
_SUMMARY = {
    "normal_p95_log2tpm": 1.5,
    "fraction_tumor_above_normal_p95": 0.9,
    "tumor_expression_class": "broadly_high",
    "distribution_pattern": "unimodal_high",
}


def _write_plot_data(d: Path) -> Path:
    import pandas as pd

    d.mkdir(parents=True, exist_ok=True)
    rows = [{"group": "tumor", "source": "TCGA", "log2_tpm": v} for v in _TUMOR] + [
        {"group": "normal", "source": "GTEx:Colon", "log2_tpm": v} for v in _NORMAL
    ]
    out = d / "plot_data_expression_distribution.parquet"
    pd.DataFrame(rows, columns=["group", "source", "log2_tpm"]).to_parquet(out, index=False)
    return out


def _svg_ok(p: Path) -> bool:
    return p.exists() and p.stat().st_size > 0 and "<svg" in p.read_text()[:2000]


def test_plot_data_persisted_on_read(tmp_path, monkeypatch):
    monkeypatch.setattr(r, "read_tumor_samples", lambda target, indication: list(_TUMOR))
    monkeypatch.setattr(r, "read_normal_samples", lambda target, indication: (list(_NORMAL), "Colon"))
    summary = r.read_tumor_expression_distribution("MYGENE", "COADREAD", plot_data_out=tmp_path)
    assert summary.get("tumor_expression_class")
    assert (tmp_path / "plot_data_expression_distribution.parquet").exists()


def test_renders_offline_from_persisted_parquet(tmp_path, monkeypatch):
    pd_path = _write_plot_data(tmp_path / "src")

    # prove OFFLINE: the live sample readers must NOT be exercised
    monkeypatch.setattr(
        c._read,
        "read_tumor_samples",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("live read in offline render")),
    )
    monkeypatch.setattr(
        c._read,
        "read_normal_samples",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("live read in offline render")),
    )
    out = tmp_path / "out"
    descs = f.render_from_plot_data(pd_path, _SUMMARY, out, "MYGENE", "COADREAD")
    assert _svg_ok(out / "figure_expression_distribution.svg")
    assert {d["id"] for d in descs if not d.get("dynamic")} == {"expression_distribution_per_sample"}
    assert [d for d in descs if d.get("primary")][0]["id"] == "expression_distribution_per_sample"
    assert all(d.get("dynamic") for d in descs if d.get("type") == "plotly")


def test_missing_columns_raises(tmp_path):
    import pandas as pd

    df = pd.DataFrame({"group": ["tumor"]})  # no log2_tpm
    try:
        f.render_from_plot_data(df, {}, tmp_path / "out", "MYGENE", "COADREAD")
    except ValueError as e:
        assert "log2_tpm" in str(e)
    else:
        raise AssertionError("expected ValueError on missing required column")
