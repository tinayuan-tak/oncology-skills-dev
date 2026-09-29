"""Synthetic-data test of depmap-expression-dependency (Card 4).

Builds synthetic CRISPRGeneEffect.csv + OmicsExpressionTPMLogp1HumanProteinCodingGenes.csv
+ Model.csv with a designed-in negative correlation (high expression → strong dependency).
Runs the method, validates that:
  - compute_correlation_summary returns Card 4 spec fields with expected values
  - figure_scatter_with_regression.svg + figure_lineage_stratified_scatter.svg emit
  - plot_data.parquet has one row per cell line with required columns
  - manifest.yaml contains provenance + exclusion tracking
  - Full CLI invocation via Click testing also works end-to-end

Mirrors the Card 1+2 synthetic-test pattern. No S3 required.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from methods.roots import contracts_root

# Portable repo root: was hardcoded to the author's /home/sagemaker-user checkout, so every
# path guard below read as "data missing" on a CI runner or in a worktree.
METHODS_REPO = Path(__file__).resolve().parents[3]
# Portable sibling root: was hardcoded to the author's /home/sagemaker-user checkout, so the
# guard below reported "not available" on every CI runner -- even though the workflow checks
# this sibling out and exports its root. `or` rather than a .get() default, so an EMPTY value
# falls back too instead of yielding Path("") == the CWD, which reads as a plausible wrong root.
CONTRACTS_ROOT = contracts_root()


def _build_synthetic_depmap_dir(target_dir: Path, n_cell_lines: int = 200, designed_r: float = -0.6) -> None:
    """Build a synthetic DepMap dir matching the real schema for Cards 1+2+4.

    Designed-in negative correlation `designed_r` so Card 4's compute path
    returns a non-trivial Pearson r.
    """
    import numpy as np

    rng = np.random.default_rng(seed=42)

    cell_line_ids = [f"ACH-{i:06d}" for i in range(n_cell_lines)]

    n_bowel = int(0.25 * n_cell_lines)
    n_lung = int(0.25 * n_cell_lines)
    n_pancreas = int(0.20 * n_cell_lines)
    n_breast = int(0.15 * n_cell_lines)
    n_stomach = n_cell_lines - (n_bowel + n_lung + n_pancreas + n_breast)
    lineage_pool = (
        ["Bowel"] * n_bowel
        + ["Lung"] * n_lung
        + ["Pancreas"] * n_pancreas
        + ["Breast"] * n_breast
        + ["Stomach"] * n_stomach
    )
    rng.shuffle(lineage_pool)

    # KRAS Chronos: Bowel/Pancreas strongly dependent; others not.
    kras_chronos = []
    base_tpm = []
    for lineage in lineage_pool:
        if lineage == "Bowel":
            kras_chronos.append(float(rng.normal(loc=-1.5, scale=0.2)))
            base_tpm.append(float(rng.normal(loc=6.5, scale=0.5)))
        elif lineage == "Pancreas":
            kras_chronos.append(float(rng.normal(loc=-1.3, scale=0.25)))
            base_tpm.append(float(rng.normal(loc=6.0, scale=0.5)))
        else:
            kras_chronos.append(float(rng.normal(loc=-0.1, scale=0.25)))
            base_tpm.append(float(rng.normal(loc=4.5, scale=0.8)))

    crispr_df = pd.DataFrame(
        {
            "ModelID": cell_line_ids,
            "KRAS (3845)": kras_chronos,
            "EGFR (1956)": rng.normal(loc=-0.3, scale=0.4, size=n_cell_lines).tolist(),
        }
    )
    crispr_df.to_csv(target_dir / "CRISPRGeneEffect.csv", index=False)

    # TPM matrix with the 5-metadata-column schema + KRAS gene column.
    # Designed-in negative correlation: tpm = (designed_r) * chronos_z + indep noise.
    chronos_z = (pd.Series(kras_chronos) - pd.Series(kras_chronos).mean()) / pd.Series(kras_chronos).std()
    tpm_correlated = pd.Series(base_tpm) + designed_r * chronos_z * pd.Series(base_tpm).std()
    tpm_correlated = tpm_correlated.clip(lower=0.1)  # log2(TPM+1) must be positive

    tpm_df = pd.DataFrame(
        {
            "SequencingID": [f"SQ-{i:06d}" for i in range(n_cell_lines)],
            "ModelConditionID": [f"MC-{i:06d}" for i in range(n_cell_lines)],
            "ModelID": cell_line_ids,
            "IsDefaultEntryForMC": ["Yes"] * n_cell_lines,
            "IsDefaultEntryForModel": ["Yes"] * n_cell_lines,
            "KRAS (3845)": tpm_correlated.tolist(),
            "EGFR (1956)": rng.normal(loc=5.0, scale=1.0, size=n_cell_lines).tolist(),
        }
    )
    tpm_df.to_csv(target_dir / "OmicsExpressionTPMLogp1HumanProteinCodingGenes.csv", index=False)

    model_df = pd.DataFrame(
        {
            "ModelID": cell_line_ids,
            "CellLineName": [f"CL{i}" for i in range(n_cell_lines)],
            "OncotreeLineage": lineage_pool,
        }
    )
    model_df.to_csv(target_dir / "Model.csv", index=False)


def test_synthetic_kras_correlation_strong(tmp_path, monkeypatch):
    """Build synthetic DepMap with designed-in r ≈ -0.6 → method should return
    strong_negative correlation_class + dominant POSITIVE interpretation."""
    fake_depmap = tmp_path / "depmap-26q1"
    fake_depmap.mkdir()
    _build_synthetic_depmap_dir(fake_depmap, n_cell_lines=200, designed_r=-0.6)

    import sys

    sys.path.insert(0, str(METHODS_REPO))
    import methods.depmap_expression_dependency.cli as cli_mod

    monkeypatch.setattr(cli_mod, "DEPMAP_LOCAL_FALLBACK_DIRS", [fake_depmap])

    chronos_by_model, tpm_by_model, model_metadata, load_errors = cli_mod.load_depmap_files_for_card4(
        release_pin="26q1", target_symbol="KRAS"
    )
    assert load_errors == [], f"expected clean load; got {load_errors}"
    assert len(chronos_by_model) == 200
    assert len(tpm_by_model) == 200

    summary = cli_mod.compute_correlation_summary(chronos_by_model, tpm_by_model, model_metadata, indication="COADREAD")

    # Card 4 spec field assertions
    assert summary["n_cell_lines_evaluated"] == 200
    assert summary["pearson_r"] is not None
    assert summary["pearson_r"] < -0.3, f"Expected strong negative correlation; got r={summary['pearson_r']}"
    assert summary["pearson_p"] < 0.01
    assert summary["correlation_class"] in ("strong_negative", "moderate_negative")
    # Top-quartile high-expressers should be more dependent than bottom-quartile
    assert summary["chronos_at_high_expression"] < summary["chronos_at_low_expression"]

    # Figure emission
    out = tmp_path / "card_output"
    out.mkdir()
    target_lineage = summary.get("_target_lineage", "Bowel")
    merged = cli_mod.build_merged_data(chronos_by_model, tpm_by_model, model_metadata, target_lineage)
    cli_mod.emit_plot_data(merged, out)
    cli_mod.emit_scatter_regression_plot(merged, "KRAS", "COADREAD", summary, out, CONTRACTS_ROOT)
    cli_mod.emit_lineage_stratified_scatter(merged, "KRAS", "COADREAD", summary, out, CONTRACTS_ROOT)
    cli_mod.emit_manifest("KRAS", "COADREAD", "26q1", summary, {}, out, [])

    assert (out / "figure_scatter_with_regression.svg").stat().st_size > 2000
    assert (out / "figure_lineage_stratified_scatter.svg").stat().st_size > 2000
    assert (out / "plot_data.parquet").exists()

    pdf = pd.read_parquet(out / "plot_data.parquet")
    assert len(pdf) == 200
    assert {
        "cell_line_id",
        "chronos_score",
        "tpm_logp1",
        "lineage",
        "is_target_lineage",
        "is_high_expression",
        "is_low_expression",
    }.issubset(pdf.columns)

    with (out / "manifest.yaml").open() as f:
        mani = yaml.safe_load(f)
    assert mani["method"] == "depmap-expression-dependency"
    assert mani["target"] == "KRAS"
    assert mani["correlation_class"] in ("strong_negative", "moderate_negative")


def test_synthetic_kras_full_cli_invocation(tmp_path, monkeypatch):
    """Run the CLI via Click testing against synthetic data."""
    import sys

    fake_depmap = tmp_path / "depmap-26q1"
    fake_depmap.mkdir()
    _build_synthetic_depmap_dir(fake_depmap, n_cell_lines=150, designed_r=-0.5)

    sys.path.insert(0, str(METHODS_REPO))
    import methods.depmap_expression_dependency.cli as cli_mod

    monkeypatch.setattr(cli_mod, "DEPMAP_LOCAL_FALLBACK_DIRS", [fake_depmap])

    out = tmp_path / "out"
    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        [
            "--target",
            "KRAS",
            "--indication",
            "COADREAD",
            "--release-pin",
            "26q1",
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, f"CLI failed: {result.output}\n{result.exception}"

    with (out / "summary.json").open() as f:
        summary = json.load(f)
    assert summary["n_cell_lines_evaluated"] == 150
    assert summary["correlation_class"] in (
        "strong_negative",
        "moderate_negative",
        "weak_negative",
        "no_correlation",
    )
