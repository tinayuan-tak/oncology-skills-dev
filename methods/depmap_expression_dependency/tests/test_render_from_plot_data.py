"""Figure Stage 6 (card4 expression-dependency-correlation): plot_data persists on the verdict read,
and render_from_plot_data draws the scatter + lineage-stratified figures OFFLINE from it — no S3, no
second live read (loader monkeypatched to RAISE)."""

from __future__ import annotations

import sys
from pathlib import Path

METHODS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(METHODS_ROOT))

from methods.depmap_expression_dependency import cli as c
from methods.depmap_expression_dependency import figures as f
from methods.depmap_expression_dependency import read as r


def _panel() -> tuple[dict, dict, dict]:
    chronos, tpm, meta = {}, {}, {}
    i = 1
    for lin, rows in {"Bowel": [(-1.3, 6.0), (-1.1, 5.6), (-0.9, 5.0), (-1.2, 6.2), (-0.8, 4.8)],
                      "Lung": [(-0.4, 2.1), (-0.2, 1.8), (-0.5, 2.4), (-0.1, 1.2), (-0.3, 2.0)],
                      "Breast": [(0.05, 0.4), (-0.05, 0.6), (0.1, 0.3), (0.0, 0.5), (-0.02, 0.45)]}.items():
        for chr_v, tpm_v in rows:
            mid = f"ACH-{i:06d}"
            chronos[mid] = float(chr_v)
            tpm[mid] = float(tpm_v)
            meta[mid] = {"ModelID": mid, "OncotreeLineage": lin, "CellLineName": f"CL{i}_{lin}"}
            i += 1
    return chronos, tpm, meta


def _svg_ok(p: Path) -> bool:
    return p.exists() and p.stat().st_size > 0 and "<svg" in p.read_text()[:2000]


def test_plot_data_persisted_on_read(tmp_path, monkeypatch):
    chronos, tpm, meta = _panel()
    monkeypatch.setattr(r._cli, "load_depmap_files_for_card4",
                        lambda release_pin, target_symbol: (chronos, tpm, meta, []))
    summary = r.read_expression_dependency("MYGENE", "COADREAD", plot_data_out=tmp_path)
    assert summary.get("correlation_class")
    assert (tmp_path / "plot_data.parquet").exists()
    assert r.read_expression_dependency("MYGENE", "COADREAD") == \
        r.read_expression_dependency("MYGENE", "COADREAD", plot_data_out=tmp_path / "again")


def test_renders_offline_from_persisted_parquet(tmp_path, monkeypatch):
    chronos, tpm, meta = _panel()
    summary = c.compute_correlation_summary(chronos, tpm, meta, indication="COADREAD")
    merged = c.build_merged_data(chronos, tpm, meta, "Bowel")
    src = tmp_path / "src"; src.mkdir()
    c.emit_plot_data(merged, src)
    assert (src / "plot_data.parquet").exists()

    monkeypatch.setattr(c, "load_depmap_files_for_card4",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("live read in offline render")))
    out = tmp_path / "out"
    descs = f.render_from_plot_data(src / "plot_data.parquet", summary, out, "MYGENE", "COADREAD")
    assert _svg_ok(out / "figure_scatter_with_regression.svg")
    assert _svg_ok(out / "figure_lineage_stratified_scatter.svg")
    assert {d["id"] for d in descs} == {"scatter_with_regression", "lineage_stratified_scatter"}
    assert [d for d in descs if d.get("primary")][0]["id"] == "scatter_with_regression"


def test_missing_columns_raises(tmp_path):
    import pandas as pd
    df = pd.DataFrame({"chronos": [0.1]})  # no tpm_logp1
    try:
        f.render_from_plot_data(df, {}, tmp_path / "out", "MYGENE", "COADREAD")
    except ValueError as e:
        assert "tpm_logp1" in str(e)
    else:
        raise AssertionError("expected ValueError on missing required column")
