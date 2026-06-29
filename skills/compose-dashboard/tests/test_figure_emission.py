"""Phase-2 figure-emission tests.

Verifies that when execute_run_plan / compose is called with an `out_path`,
each card whose card_id is registered in `_figure_emitters.CARD_FIGURE_EMITTERS`:
  - has SVG files written under <out_path>/cards/<card_id>/
  - has a `figures` list attached to its card_output entry
  - those figure paths are referenced verbatim in dashboard.md

This is the rendering counterpart to test_live_reader_chain.py — that test
verifies the dispatcher returns a summary; this test verifies that the
*figures alongside* get emitted when phase-2 is asked to.

Synthetic-data path: we monkeypatch the underlying method CLIs'
DEPMAP_LOCAL_FALLBACK_DIRS so the figure emitter loads a synthetic
CRISPRGeneEffect.csv + Model.csv rather than calling S3. This is the same
pattern Cards 1 and 2's unit tests use.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest


METHODS_REPO = Path("/home/sagemaker-user/rnd-computational-biology-oncology-methods")
SKILL_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(METHODS_REPO))


def _build_synthetic_depmap_dir(target_dir: Path, n_cell_lines: int = 200) -> None:
    """Build CRISPRGeneEffect.csv + Model.csv matching DepMap's OncotreeLineage
    categorical (Bowel, Lung, Pancreas, Stomach, Breast) so Card 2's COADREAD →
    Bowel lookup hits real data."""
    import numpy as np
    rng = np.random.default_rng(seed=42)

    cell_line_ids = [f"ACH-{i:06d}" for i in range(n_cell_lines)]
    n_bowel = int(0.25 * n_cell_lines)
    n_lung = int(0.25 * n_cell_lines)
    n_pancreas = int(0.20 * n_cell_lines)
    n_breast = int(0.15 * n_cell_lines)
    n_stomach = n_cell_lines - (n_bowel + n_lung + n_pancreas + n_breast)
    lineage_pool = (
        ["Bowel"] * n_bowel +
        ["Lung"] * n_lung +
        ["Pancreas"] * n_pancreas +
        ["Breast"] * n_breast +
        ["Stomach"] * n_stomach
    )
    rng.shuffle(lineage_pool)

    kras_chronos = []
    for lineage in lineage_pool:
        if lineage == "Bowel":
            kras_chronos.append(float(rng.normal(loc=-1.5, scale=0.2)))
        elif lineage == "Pancreas":
            kras_chronos.append(float(rng.normal(loc=-1.2, scale=0.25)))
        else:
            kras_chronos.append(float(rng.normal(loc=-0.1, scale=0.25)))

    crispr_df = pd.DataFrame({
        "ModelID": cell_line_ids,
        "KRAS (3845)": kras_chronos,
    })
    crispr_df.to_csv(target_dir / "CRISPRGeneEffect.csv", index=False)

    model_df = pd.DataFrame({
        "ModelID": cell_line_ids,
        "CellLineName": [f"CL{i}" for i in range(n_cell_lines)],
        "OncotreeLineage": lineage_pool,
    })
    model_df.to_csv(target_dir / "Model.csv", index=False)


def test_card1_figure_emission(tmp_path, monkeypatch):
    """Directly exercise the figure-emission registry for Card 1."""
    fake_depmap = tmp_path / "depmap-26q1"
    fake_depmap.mkdir()
    _build_synthetic_depmap_dir(fake_depmap, n_cell_lines=150)

    # Point Card 1's CLI loader at the synthetic dir
    import methods.depmap_chronos_distribution.cli as c1cli
    monkeypatch.setattr(c1cli, "DEPMAP_LOCAL_FALLBACK_DIRS", [fake_depmap])

    from _figure_emitters import emit_figures_for_card

    out_root = tmp_path / "compose_out"
    figs = emit_figures_for_card(
        card_id="pan-cancer-dependency-distribution",
        summary={"some_summary_field": 123},
        out_root=out_root,
        target="KRAS",
        indication="COADREAD",
    )

    assert len(figs) >= 1, "Card 1 emitter returned no figures"
    primaries = [f for f in figs if f.get("primary")]
    assert len(primaries) >= 1, "Card 1 emitter returned no primary figure"

    for f in figs:
        full = out_root / f["path"]
        assert full.exists(), f"Figure missing on disk: {full}"
        assert full.stat().st_size > 500, f"Figure too small (likely empty): {full}"
        assert f["path"].startswith("cards/pan-cancer-dependency-distribution/")


def test_card2_figure_emission(tmp_path, monkeypatch):
    """Directly exercise the figure-emission registry for Card 2."""
    fake_depmap = tmp_path / "depmap-26q1"
    fake_depmap.mkdir()
    _build_synthetic_depmap_dir(fake_depmap, n_cell_lines=200)

    import methods.depmap_chronos.cli as c2cli
    monkeypatch.setattr(c2cli, "DEPMAP_LOCAL_FALLBACK_DIRS", [fake_depmap])

    from _figure_emitters import emit_figures_for_card

    out_root = tmp_path / "compose_out"
    figs = emit_figures_for_card(
        card_id="dependency-lineage-selectivity",
        summary={"lineage_label": "Bowel"},
        out_root=out_root,
        target="KRAS",
        indication="COADREAD",
    )

    assert len(figs) >= 1
    for f in figs:
        full = out_root / f["path"]
        assert full.exists()
        assert full.stat().st_size > 500


def test_emitter_no_op_on_live_read_error(tmp_path):
    """If summary contains _live_read_error, emitter must return [] (no crash, no figures)."""
    from _figure_emitters import emit_figures_for_card

    out_root = tmp_path / "compose_out"
    figs = emit_figures_for_card(
        card_id="pan-cancer-dependency-distribution",
        summary={"_live_read_error": "s3_read_failed"},
        out_root=out_root,
        target="KRAS",
        indication="COADREAD",
    )

    assert figs == [], "Emitter should no-op on _live_read_error"
    assert not (out_root / "cards").exists(), \
        "No directory should be created when emitter no-ops"


def test_emitter_no_op_for_unregistered_card(tmp_path):
    """Cards without an emitter return [] without raising."""
    from _figure_emitters import emit_figures_for_card

    figs = emit_figures_for_card(
        card_id="some-card-with-no-emitter",
        summary={"x": 1},
        out_root=tmp_path,
        target="KRAS", indication="COADREAD",
    )
    assert figs == []


def test_dashboard_md_embeds_figure_references(tmp_path):
    """Renderer test: an evidence_package with figures on a card produces ![alt](path) in markdown."""
    sys.path.insert(0, str(SKILL_DIR.parent / "render-evidence-package" / "scripts"))
    from render_markdown import render_evidence_package

    ep = {
        "package_id": "ep-test",
        "framework_version": "2.0.0",
        "generated_at": "2026-06-29T00:00:00Z",
        "generated_by": "test",
        "context": {
            "target": {"symbol": "KRAS", "hgnc_id": 6407},
            "indication": {"oncotree_code": "COADREAD"},
            "scope": "cancer_type",
        },
        "governance": {
            "data_mode": "latest_approved",
            "release_pin": "26q1",
            "lockfile_ref": "lockfile.yaml",
            "validation_summary": {
                "n_cards_attempted": 1, "n_cards_passed": 1,
                "n_cards_passed_with_warnings": 0, "n_cards_failed": 0,
                "n_cards_excluded_by_applies_when": 0,
            },
        },
        "dashboard_spec_ref": "test",
        "cards": [{
            "card_id": "pan-cancer-dependency-distribution",
            "card_version": "1.0.0",
            "validation_state": "pass",
            "summary": {"distribution_shape": "bimodal_selective"},
            "interpretation_call": "selective dependency",
            "caveats": [],
            "provenance": {"method_calls": [], "input_manifest_ids": []},
            "figures": [
                {"id": "waterfall", "path": "cards/pan-cancer-dependency-distribution/figure_waterfall.svg",
                 "type": "waterfall_plot", "primary": True},
                {"id": "histogram_kde", "path": "cards/pan-cancer-dependency-distribution/figure_histogram_kde.svg",
                 "type": "histogram_kde", "primary": False},
            ],
        }],
        "synthesis": {"headline": "test", "caveats_summary": [], "modality_fit_assessment": []},
        "renderings": {"markdown": "renderings/dashboard.md"},
        "schema_version": 1,
    }

    md = render_evidence_package(ep)

    assert "![waterfall_plot](cards/pan-cancer-dependency-distribution/figure_waterfall.svg)" in md, \
        "Primary figure not embedded in markdown"
    assert "![histogram_kde](cards/pan-cancer-dependency-distribution/figure_histogram_kde.svg)" in md, \
        "Alternate figure not embedded in markdown"
    assert "<details><summary>Alternate views</summary>" in md, \
        "Alternate-views collapsible block missing"
