"""Figure Stage 6 (card1c crispr-rnai-dependency-concordance): plot_data persists on the verdict read,
and render_from_plot_data draws the overlay-density + partition-bar + scatter figures OFFLINE from it —
no S3, no second live read (loader monkeypatched to RAISE)."""

from __future__ import annotations

import sys
from pathlib import Path

METHODS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(METHODS_ROOT))

from methods.depmap_crispr_rnai_concordance import cli as c
from methods.depmap_crispr_rnai_concordance import figures as f
from methods.depmap_crispr_rnai_concordance import read as r


def _panels() -> tuple[dict, dict, dict]:
    # mix of in-both, CRISPR-only, RNAi-only lines (the None/NaN round-trip case)
    chronos = {"ACH-1": -1.2, "ACH-2": -0.9, "ACH-3": -0.3, "ACH-4": 0.1, "ACH-5": -1.0,
               "ACH-6": -0.6, "ACH-7": 0.05}                       # ACH-8/9 CRISPR-absent
    demeter = {"ACH-1": -0.7, "ACH-2": -0.5, "ACH-3": -0.1, "ACH-4": 0.0, "ACH-5": -0.55,
               "ACH-8": -0.4, "ACH-9": 0.0}                        # ACH-6/7 RNAi-absent
    meta = {f"ACH-{i}": {"CCLEName": f"CL{i}", "OncotreeLineage": lin}
            for i, lin in zip(range(1, 10), ["Bowel", "Bowel", "Lung", "Lung", "Breast",
                                             "Breast", "Skin", "Skin", "Lung"])}
    return chronos, demeter, meta


def _svg_ok(p: Path) -> bool:
    return p.exists() and p.stat().st_size > 0 and "<svg" in p.read_text()[:2000]


def test_plot_data_persisted_on_read(tmp_path, monkeypatch):
    chronos, demeter, meta = _panels()
    monkeypatch.setattr(r._cli, "load_concordance_inputs",
                        lambda target, release_pin="26q1": (chronos, demeter, meta, []))
    summary = r.read_crispr_rnai_concordance("MYGENE", "COADREAD", plot_data_out=tmp_path)
    assert summary.get("concordance_class")
    assert (tmp_path / "plot_data_concordance.parquet").exists()
    assert r.read_crispr_rnai_concordance("MYGENE") == \
        r.read_crispr_rnai_concordance("MYGENE", plot_data_out=tmp_path / "again")


def test_renders_offline_from_persisted_parquet(tmp_path, monkeypatch):
    chronos, demeter, meta = _panels()
    summary = c.compute_concordance(chronos, demeter, meta)
    src = tmp_path / "src"; src.mkdir()
    c.emit_plot_data(summary["per_line_concordance"], src)
    assert (src / "plot_data_concordance.parquet").exists()

    monkeypatch.setattr(c, "load_concordance_inputs",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("live read in offline render")))
    out = tmp_path / "out"
    descs = f.render_from_plot_data(src / "plot_data_concordance.parquet", summary, out, "MYGENE", "COADREAD")
    assert _svg_ok(out / "figure_concordance_overlay_density.svg")
    assert _svg_ok(out / "figure_concordance_scatter.svg")
    assert _svg_ok(out / "figure_concordance_partition_bar.svg")
    assert {d["id"] for d in descs if not d.get("dynamic")} == \
        {"concordance_overlay_density", "concordance_partition_bar", "concordance_scatter"}
    assert [d for d in descs if d.get("primary")][0]["id"] == "concordance_overlay_density"
    assert all(d.get("dynamic") for d in descs if d.get("type") == "plotly")


def test_missing_columns_raises(tmp_path):
    import pandas as pd
    df = pd.DataFrame({"chronos": [0.1]})  # no demeter2
    try:
        f.render_from_plot_data(df, {}, tmp_path / "out", "MYGENE", "COADREAD")
    except ValueError as e:
        assert "demeter2" in str(e)
    else:
        raise AssertionError("expected ValueError on missing required column")
