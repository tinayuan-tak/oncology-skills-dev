"""Synthetic-data test of depmap-chronos (Card 2 — lineage selectivity).

Builds a synthetic CRISPRGeneEffect.csv + Model.csv with known shape (KRAS strongly
dependent in Bowel + Pancreas lineages, much weaker elsewhere), runs the method,
validates that:
  - compute_lineage_summary returns Card 2 spec fields with expected values/classes
  - figure_forest_plot.svg + figure_lineage_strip.svg are emitted
  - plot_data.parquet has one row per cell line with required columns
  - manifest.yaml contains provenance
  - The CLI invocation via Click testing also works end-to-end

Mirrors the Card 1 (depmap_chronos_distribution) test pattern. No S3 required.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
import yaml


METHODS_REPO = Path("/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods")
CONTRACTS_ROOT = Path("/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")


def _build_synthetic_depmap_dir(target_dir: Path, n_cell_lines: int = 200) -> None:
    """Build a synthetic DepMap dir with OncotreeLineage values matching DepMap's
    real categorical (Bowel, Pancreas, Lung, Stomach, Breast)."""
    import numpy as np
    rng = np.random.default_rng(seed=42)

    cell_line_ids = [f"ACH-{i:06d}" for i in range(n_cell_lines)]

    # Distribution chosen so Bowel is the most-dependent lineage on KRAS
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
    assert len(lineage_pool) == n_cell_lines
    rng.shuffle(lineage_pool)

    kras_chronos = []
    for lineage in lineage_pool:
        if lineage == "Bowel":
            kras_chronos.append(float(rng.normal(loc=-1.6, scale=0.2)))
        elif lineage == "Pancreas":
            kras_chronos.append(float(rng.normal(loc=-1.3, scale=0.25)))
        elif lineage == "Lung":
            kras_chronos.append(float(rng.normal(loc=-0.4, scale=0.3)))
        else:
            kras_chronos.append(float(rng.normal(loc=-0.05, scale=0.2)))

    crispr_df = pd.DataFrame({
        "ModelID": cell_line_ids,
        "KRAS (3845)": kras_chronos,
        "EGFR (1956)": rng.normal(loc=-0.3, scale=0.4, size=n_cell_lines).tolist(),
    })
    crispr_df.to_csv(target_dir / "CRISPRGeneEffect.csv", index=False)

    model_df = pd.DataFrame({
        "ModelID": cell_line_ids,
        "CellLineName": [f"CL{i}" for i in range(n_cell_lines)],
        "OncotreeLineage": lineage_pool,
    })
    model_df.to_csv(target_dir / "Model.csv", index=False)


def test_synthetic_kras_coadread_lineage(tmp_path, monkeypatch):
    """Build synthetic DepMap → run CLI's compute path → validate Card 2 output."""
    fake_depmap = tmp_path / "depmap-26q1"
    fake_depmap.mkdir()
    _build_synthetic_depmap_dir(fake_depmap, n_cell_lines=200)

    import sys
    sys.path.insert(0, str(METHODS_REPO))
    import methods.depmap_chronos.cli as cli_mod
    monkeypatch.setattr(cli_mod, "DEPMAP_LOCAL_FALLBACK_DIRS", [fake_depmap])

    chronos_by_model, model_metadata, load_errors = cli_mod.load_depmap_files(
        release_pin="26q1", target_symbol="KRAS"
    )
    assert load_errors == [], f"expected clean load; got {load_errors}"
    assert len(chronos_by_model) == 200

    summary = cli_mod.compute_lineage_summary(
        chronos_by_model, model_metadata, indication="COADREAD"
    )

    # Card 2 spec field assertions
    assert summary["lineage_label"] == "Bowel"
    assert summary["n_lineage_cell_lines"] == 50
    assert summary["median_chronos_lineage"] is not None
    assert summary["median_chronos_lineage"] < -1.0, \
        f"Bowel KRAS median should be strong dependency; got {summary['median_chronos_lineage']}"
    assert summary["lineage_vs_panel_delta_chronos"] < -0.3
    # Bowel should rank as most-dependent (rank percentile ≥ 80)
    assert summary["lineage_rank_percentile"] >= 80, \
        f"Bowel rank should be top tier; got {summary['lineage_rank_percentile']}"
    # Selectivity class should be strong (delta < -0.5 + rank >= 80)
    assert summary["selectivity_class"] in ("strong_lineage_selective", "moderate_lineage_selective"), \
        f"got {summary['selectivity_class']}"

    # Figure emission
    out = tmp_path / "card_output"
    out.mkdir()
    merged_data = cli_mod.emit_plot_data(
        chronos_by_model, model_metadata, target_lineage="Bowel",
        strong_threshold=-1.0, out_path=out,
    )
    cli_mod.emit_forest_plot(
        summary.get("_per_lineage_records", []), "Bowel",
        "KRAS", "COADREAD", summary, out, CONTRACTS_ROOT,
    )
    cli_mod.emit_lineage_strip(merged_data, "Bowel", "KRAS", "COADREAD", out, CONTRACTS_ROOT)
    cli_mod.emit_manifest("KRAS", "COADREAD", "26q1", summary, chronos_by_model, out, [])

    assert (out / "figure_forest_plot.svg").stat().st_size > 1000
    assert (out / "figure_lineage_strip.svg").stat().st_size > 1000
    assert (out / "plot_data.parquet").exists()
    assert (out / "manifest.yaml").exists()

    pdf = pd.read_parquet(out / "plot_data.parquet")
    assert len(pdf) == 200
    assert {"cell_line_id", "chronos_score", "lineage", "is_target_lineage"}.issubset(pdf.columns)
    assert pdf["is_target_lineage"].sum() == 50

    with (out / "manifest.yaml").open() as f:
        mani = yaml.safe_load(f)
    assert mani["method"] == "depmap-chronos"
    assert mani["indication"] == "COADREAD"
    assert mani["lineage_label"] == "Bowel"


def test_synthetic_kras_full_cli_invocation(tmp_path, monkeypatch):
    """Run the CLI via Click testing against synthetic data."""
    import sys
    fake_depmap = tmp_path / "depmap-26q1"
    fake_depmap.mkdir()
    _build_synthetic_depmap_dir(fake_depmap, n_cell_lines=150)

    sys.path.insert(0, str(METHODS_REPO))
    import methods.depmap_chronos.cli as cli_mod
    monkeypatch.setattr(cli_mod, "DEPMAP_LOCAL_FALLBACK_DIRS", [fake_depmap])

    out = tmp_path / "out"
    from click.testing import CliRunner
    runner = CliRunner()
    result = runner.invoke(cli_mod.main, [
        "--target", "KRAS",
        "--indication", "COADREAD",
        "--release-pin", "26q1",
        "--out", str(out),
    ])
    assert result.exit_code == 0, f"CLI failed: {result.output}\n{result.exception}"

    with (out / "summary.json").open() as f:
        summary = json.load(f)
    assert summary["lineage_label"] == "Bowel"
    assert summary["selectivity_class"] in (
        "strong_lineage_selective", "moderate_lineage_selective", "broadly_dependent",
    )
