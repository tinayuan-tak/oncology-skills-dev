"""Figure Stage 6 (cis-feature-expression-coherence): plot_data persists on the verdict read, and
render_from_plot_data draws the cn_expression_scatter OFFLINE from it — no S3, no second live read
(loaders monkeypatched to RAISE)."""

from __future__ import annotations

import sys
from pathlib import Path

METHODS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(METHODS_ROOT))

from methods.depmap_cis_dosage import cli as c
from methods.depmap_cis_dosage import figures as f
from methods.depmap_cis_dosage import read as r


def _panels() -> tuple[dict, dict, dict]:
    cn, tpm, meta = {}, {}, {}
    i = 1
    for lin, rows in {
        "Bowel": [(2.8, 5.6), (3.2, 6.0), (1.0, 3.1), (0.5, 2.0), (1.5, 4.2)],
        "Lung": [(1.0, 3.0), (1.1, 3.2), (0.9, 2.8), (2.0, 4.8), (1.2, 3.4)],
    }.items():
        for cn_v, tpm_v in rows:
            mid = f"ACH-{i:06d}"
            cn[mid] = float(cn_v)
            tpm[mid] = float(tpm_v)
            meta[mid] = {"OncotreeLineage": lin, "CellLineName": f"CL{i}"}
            i += 1
    return cn, tpm, meta


def _svg_ok(p: Path) -> bool:
    return p.exists() and p.stat().st_size > 0 and "<svg" in p.read_text()[:2000]


def test_plot_data_persisted_on_read(tmp_path, monkeypatch):
    cn, tpm, meta = _panels()
    monkeypatch.setattr(
        "methods.depmap_cn_distribution.cli.load_cn_files", lambda release_pin, target_symbol: (cn, meta, "wes", [])
    )
    monkeypatch.setattr(
        "methods.depmap_expression_distribution.cli.load_expression_files",
        lambda release_pin, target_symbol: (tpm, meta, []),
    )
    summary = r.read_cis_dosage("MYGENE", "COADREAD", plot_data_out=tmp_path)
    assert summary.get("cis_dosage_class")
    assert (tmp_path / "plot_data.parquet").exists()


def test_renders_offline_from_persisted_parquet(tmp_path, monkeypatch):
    cn, tpm, meta = _panels()
    summary = c.compute_cis_dosage(cn, tpm)
    merged = f.build_merged_data(cn, tpm, meta)
    src = tmp_path / "src"
    src.mkdir()
    f.emit_plot_data(merged, src)
    assert (src / "plot_data.parquet").exists()

    monkeypatch.setattr(
        "methods.depmap_cn_distribution.cli.load_cn_files",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("live read in offline render")),
    )
    out = tmp_path / "out"
    descs = f.render_from_plot_data(src / "plot_data.parquet", summary, out, "MYGENE", "COADREAD")
    assert _svg_ok(out / "figure_cn_expression_scatter.svg")
    assert {d["id"] for d in descs} == {"cn_vs_expression_scatter"}
    assert descs[0]["primary"] is True


def test_missing_columns_raises(tmp_path):
    import pandas as pd

    df = pd.DataFrame({"relative_cn": [1.0]})  # no tpm_logp1
    try:
        f.render_from_plot_data(df, {}, tmp_path / "out", "MYGENE", "COADREAD")
    except ValueError as e:
        assert "tpm_logp1" in str(e)
    else:
        raise AssertionError("expected ValueError on missing required column")
