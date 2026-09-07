"""Figure Stage 1+2 (protein abundance): plot_data persists during load_and_classify, and
render_from_plot_data draws the cellline-protein-abundance figures OFFLINE from it — no S3/cbg, no
second live read. Fifth/final distribution-family member.
"""

from __future__ import annotations

import sys
from pathlib import Path

METHODS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(METHODS_ROOT))

from methods.depmap_protein_abundance import cli as c
from methods.depmap_protein_abundance import figures as f


def _panel() -> tuple[dict, dict]:
    ab, lin = {}, {}
    i = 1
    for lineage, vals in {"Lung": [6.0, 6.4, 5.8], "Breast": [5.2, 5.0, 4.9], "Bowel": [3.1, 2.8, 3.4]}.items():
        for v in vals:
            mid = f"ACH-{i:06d}"
            ab[mid] = float(v)
            lin[mid] = lineage
            i += 1
    return ab, lin


def _svg_ok(p: Path) -> bool:
    return p.exists() and p.stat().st_size > 0 and "<svg" in p.read_text()[:2000]


def _patch_loaders(monkeypatch, ab, lin):
    monkeypatch.setattr(c, "resolve_accession", lambda target, sidecar_path=None: "ACC1")
    monkeypatch.setattr(c, "load_abundance_column", lambda acc, matrix_path=None: (ab, len(ab) + 5))
    monkeypatch.setattr(c, "load_model_lineage", lambda model_path=None: lin)
    monkeypatch.setattr(c, "_all_protein_median_null", lambda matrix_path=None: [3.0, 4.0, 5.0, 6.0])


def test_plot_data_persisted_on_load_and_classify(tmp_path, monkeypatch):
    ab, lin = _panel()
    _patch_loaders(monkeypatch, ab, lin)
    summary = c.load_and_classify("MYGENE", plot_data_out=tmp_path)
    assert summary.get("protein_expression_class")
    assert (tmp_path / "plot_data_protein_abundance.parquet").exists()

    # verdict-inert: summary byte-identical with/without plot_data_out
    s_without = c.load_and_classify("MYGENE")
    assert s_without == c.load_and_classify("MYGENE", plot_data_out=tmp_path / "again")


def test_renders_offline_from_persisted_parquet(tmp_path, monkeypatch):
    ab, lin = _panel()
    src = tmp_path / "src"
    src.mkdir()
    c.emit_plot_data_protein(ab, lin, src)
    assert (src / "plot_data_protein_abundance.parquet").exists()

    # NO live read on the offline render path
    monkeypatch.setattr(
        c, "load_abundance_column", lambda *a, **k: (_ for _ in ()).throw(AssertionError("live read in offline render"))
    )
    out = tmp_path / "out"
    descs = f.render_from_plot_data(src / "plot_data_protein_abundance.parquet", {}, out, "MYGENE")

    assert _svg_ok(out / "figure_density_protein_abundance.svg")
    assert _svg_ok(out / "figure_lineage_strip_protein.svg")
    assert {d["id"] for d in descs if not d.get("dynamic")} == {"density_protein_abundance", "lineage_strip_protein"}
    assert [d for d in descs if d.get("primary")][0]["id"] == "density_protein_abundance"
    assert all(d.get("dynamic") for d in descs if d.get("type") == "plotly")


def test_missing_columns_raises(tmp_path):
    import pandas as pd

    df = pd.DataFrame({"model_id": ["ACH-1"]})  # no log2_abundance
    try:
        f.render_from_plot_data(df, {}, tmp_path / "out", "MYGENE")
    except ValueError as e:
        assert "log2_abundance" in str(e)
    else:
        raise AssertionError("expected ValueError on missing required column")


def test_returns_plotly_descriptors_with_dynamic_flag(tmp_path, monkeypatch):
    """Stage-3 parity: render_from_plot_data RETURNS the plotly-twin descriptors (dynamic:True), not
    just the SVGs — so it is an exact drop-in for the registry emitter (which appends them today)."""
    ab, lin = _panel()
    src = tmp_path / "src"
    src.mkdir()
    c.emit_plot_data_protein(ab, lin, src)

    monkeypatch.setattr(
        c,
        "emit_plotly_specs",
        lambda *a, **k: [
            {
                "id": "density_protein_abundance",
                "path": "figure_density_protein_abundance.plotly.json",
                "type": "plotly",
            }
        ],
    )
    descs = f.render_from_plot_data(src / "plot_data_protein_abundance.parquet", {}, tmp_path / "out", "MYGENE")
    dyn = [d for d in descs if d.get("dynamic")]
    assert dyn and dyn[0]["path"].endswith(".plotly.json") and dyn[0]["dynamic"] is True
