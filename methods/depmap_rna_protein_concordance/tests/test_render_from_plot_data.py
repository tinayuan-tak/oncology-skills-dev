"""Figure Stage 6 (rna-protein cellline + tumor arms): scatter points persist on the verdict read,
and render_*_from_plot_data draw the scatters OFFLINE from them — no S3, no second live read (scatter
readers monkeypatched to RAISE)."""

from __future__ import annotations

import sys
from pathlib import Path

METHODS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(METHODS_ROOT))

from methods.depmap_rna_protein_concordance import cli as c
from methods.depmap_rna_protein_concordance import figures as f
from methods.depmap_rna_protein_concordance import read as r

_PTS = [{"rna": 1.0 + i * 0.2, "protein": 0.8 + i * 0.18} for i in range(25)]  # >= floors
_SUMMARY = {"rna_protein_r": 0.6, "rna_as_biomarker": "partial_proxy",
            "n_paired_models": 25, "n_paired_tumors": 25}


def _write(d: Path, name: str) -> Path:
    import pandas as pd
    d.mkdir(parents=True, exist_ok=True)
    out = d / name
    pd.DataFrame(_PTS).to_parquet(out, index=False)
    return out


def _svg_ok(p: Path) -> bool:
    return p.exists() and p.stat().st_size > 0 and "<svg" in p.read_text()[:2000]


def test_cellline_persist_and_render(tmp_path, monkeypatch):
    monkeypatch.setattr(r, "read_rna_protein_scatter",
                        lambda target, release_pin="26q1": {"available": True, "points": _PTS})
    monkeypatch.setattr(r, "_paired_rna_protein", lambda target, release_pin="26q1": ({}, {}, "stub"))
    r.read_rna_protein_concordance("MYGENE", plot_data_out=tmp_path)
    assert (tmp_path / "plot_data_rna_protein.parquet").exists()

    pd_path = _write(tmp_path / "src", "plot_data_rna_protein.parquet")
    monkeypatch.setattr(c._read, "read_rna_protein_scatter",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("live read in offline render")))
    descs = f.render_from_plot_data(pd_path, _SUMMARY, tmp_path / "out", "MYGENE", None)
    assert _svg_ok(tmp_path / "out" / "figure_rna_protein_concordance.svg")
    assert {d["id"] for d in descs if not d.get("dynamic")} == {"rna_protein_concordance_scatter"}


def test_tumor_render(tmp_path, monkeypatch):
    pd_path = _write(tmp_path / "src", "plot_data_rna_protein_tumor.parquet")
    monkeypatch.setattr(c._read, "read_tumor_rna_protein_scatter",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("live read in offline render")))
    descs = f.render_tumor_from_plot_data(pd_path, _SUMMARY, tmp_path / "out", "MYGENE", "COADREAD")
    assert _svg_ok(tmp_path / "out" / "figure_rna_protein_concordance_tumor.svg")
    assert {d["id"] for d in descs if not d.get("dynamic")} == {"rna_protein_concordance_tumor_scatter"}


def test_missing_columns_raises(tmp_path):
    import pandas as pd
    df = pd.DataFrame({"rna": [1.0]})  # no protein
    try:
        f.render_from_plot_data(df, {}, tmp_path / "out", "MYGENE", None)
    except ValueError as e:
        assert "protein" in str(e)
    else:
        raise AssertionError("expected ValueError on missing required column")
