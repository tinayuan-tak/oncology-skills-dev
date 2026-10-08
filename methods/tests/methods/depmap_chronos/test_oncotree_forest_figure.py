"""The per-OncotreeCode forest FIGURE wiring (2026-10-08).

`emit_oncotree_forest_plot` existed in cli.py but was orphaned — never called by the live tier emitter,
never by the offline render seam, and the plot_data parquet dropped `OncotreeCode` so the offline path
recomputed empty per-code stats. These tests pin the full wiring with mutation teeth:
  - live emitter writes the SVG when per-code stats exist, returns None when empty;
  - emit_plot_data PERSISTS `oncotree_code` (teeth: fails if the column is dropped);
  - render_from_plot_data RESTORES it and emits the oncotree forest + descriptor (offline teeth);
  - an older parquet lacking the column degrades gracefully (no file, no crash, lineage forest intact).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("matplotlib")

from onc_methods.depmap_chronos import cli, figures

CONTRACTS = cli.DEFAULT_TARGET_CONTRACTS
ONC_SVG = "figure_oncotree_forest_plot.svg"


def _panel(code_rows: dict):
    """{ (lineage, code): [scores] } → (chronos_by_model, model_metadata w/ OncotreeCode)."""
    chronos, meta, i = {}, {}, 0
    for (lineage, code), scores in code_rows.items():
        for s in scores:
            mid = f"ACH-{i:05d}"
            chronos[mid] = float(s)
            meta[mid] = {"ModelID": mid, "OncotreeLineage": lineage, "OncotreeCode": code}
            i += 1
    return chronos, meta


_PANEL = {
    ("Lung", "LUAD"): [-0.8] * 8,
    ("Lung", "SCLC"): [-1.3] * 8,
    ("Bowel", "COAD"): [-0.2] * 8,
}


def test_live_emitter_writes_svg_and_handles_empty():
    chronos, meta = _panel(_PANEL)
    pcs = cli.compute_lineage_summary(chronos, meta, min_n_lineage=5)["per_oncotree_code_stats"]
    assert pcs, "fixture should produce non-empty per_oncotree_code_stats"
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        p = cli.emit_oncotree_forest_plot(pcs, "Lung", "GENEX", "NSCLC", out, CONTRACTS)
        assert p is not None and p.exists() and p.name == ONC_SVG
    # empty stats → no figure, graceful None (not a crash)
    with tempfile.TemporaryDirectory() as d:
        assert cli.emit_oncotree_forest_plot([], "Lung", "GENEX", "NSCLC", Path(d), CONTRACTS) is None


def test_offline_roundtrip_emits_oncotree_forest():
    chronos, meta = _panel(_PANEL)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        cli.emit_plot_data(chronos, meta, "Lung", -1.0, out)
        df = pd.read_parquet(out / "plot_data.parquet")
        # TEETH 1: the persisted artifact must carry the sublineage code (fails pre-fix).
        assert "oncotree_code" in df.columns
        descs = figures.render_from_plot_data(out / "plot_data.parquet", {}, out, "GENEX", "NSCLC")
        # TEETH 2: offline render must restore OncotreeCode and emit the forest (fails pre-fix).
        assert (out / ONC_SVG).exists()
        assert any(x["id"] == "oncotree_forest_plot" for x in descs)


def test_old_parquet_without_oncotree_code_degrades_gracefully():
    chronos, meta = _panel(_PANEL)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        cli.emit_plot_data(chronos, meta, "Lung", -1.0, out)
        # simulate a pre-fix parquet: drop the new column, rewrite
        pd.read_parquet(out / "plot_data.parquet").drop(columns=["oncotree_code"]).to_parquet(
            out / "plot_data.parquet", index=False
        )
        descs = figures.render_from_plot_data(out / "plot_data.parquet", {}, out, "GENEX", "NSCLC")
        assert not (out / ONC_SVG).exists()  # omitted, not crashed
        assert (out / "figure_forest_plot.svg").exists()  # lineage forest still rendered
        assert not any(x["id"] == "oncotree_forest_plot" for x in descs)
