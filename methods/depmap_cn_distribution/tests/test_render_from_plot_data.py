"""Figure Stage 1+2 (copy-number): plot_data persists on the verdict read, and render_from_plot_data
draws the copy-number-distribution figures OFFLINE from it — no S3/cbg, no second live read (loader
monkeypatched to RAISE). Parallel to the expression/chronos/rnai proof cards.
"""

from __future__ import annotations

import sys
from pathlib import Path

METHODS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(METHODS_ROOT))

from methods.depmap_cn_distribution import cli as c
from methods.depmap_cn_distribution import figures as f
from methods.depmap_cn_distribution import read as r


def _panel() -> tuple[dict, dict]:
    cn, meta = {}, {}
    i = 1
    for lin, vals in {"Breast": [3.2, 2.8, 3.5, 2.9, 3.0],   # amplified
                      "Lung": [1.0, 1.1, 0.95, 1.05, 1.0],   # neutral
                      "Bowel": [0.4, 0.35, 0.5, 0.42, 0.38]}.items():  # deleted
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
    monkeypatch.setattr(r._cli, "load_cn_files",
                        lambda release_pin, target_symbol: (cn, meta, "wes", []))
    summary = r.read_cn_distribution("MYGENE", plot_data_out=tmp_path)
    assert summary.get("copy_number_class")
    assert (tmp_path / "plot_data_cn.parquet").exists()

    s_without = r.read_cn_distribution("MYGENE")
    assert s_without == r.read_cn_distribution("MYGENE", plot_data_out=tmp_path / "again")


def test_renders_offline_from_persisted_parquet(tmp_path, monkeypatch):
    cn, meta = _panel()
    summary = c.compute_summary_stats(cn, meta, assay_used="wes")
    src = tmp_path / "src"; src.mkdir()
    c.emit_plot_data(cn, meta, src)
    assert (src / "plot_data_cn.parquet").exists()

    monkeypatch.setattr(c, "load_cn_files",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("live read in offline render")))
    out = tmp_path / "out"
    descs = f.render_from_plot_data(src / "plot_data_cn.parquet", summary, out, "MYGENE")

    assert _svg_ok(out / "figure_density_cn.svg")
    assert _svg_ok(out / "figure_waterfall_cn.svg")
    assert _svg_ok(out / "figure_lineage_strip_cn.svg")
    assert {d["id"] for d in descs} == {"density_cn", "waterfall_cn", "lineage_strip_cn"}
    assert [d for d in descs if d["primary"]][0]["id"] == "density_cn"


def test_missing_columns_raises(tmp_path):
    import pandas as pd
    df = pd.DataFrame({"model_id": ["ACH-1"]})  # no relative_cn
    try:
        f.render_from_plot_data(df, {}, tmp_path / "out", "MYGENE")
    except ValueError as e:
        assert "relative_cn" in str(e)
    else:
        raise AssertionError("expected ValueError on missing required column")
