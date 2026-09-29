"""Synthetic-data test of depmap-chronos-distribution analysis logic.

Builds a synthetic CRISPRGeneEffect.csv + Model.csv with known shape (KRAS bimodal-
selective in colorectal lineage), runs the method, validates that:
  - summary.json contains expected fields with values in expected ranges
  - figure_waterfall.svg + figure_histogram_kde.svg are emitted
  - plot_data.parquet has one row per cell line with required columns
  - manifest.yaml contains provenance

This test does NOT require S3 access. Once S3 is reachable, a separate integration
test (test_live_depmap_kras.py — gated on AWS creds) validates against real data.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import yaml

# Portable repo root: was hardcoded to the author's /home/sagemaker-user checkout, so every
# path guard below read as "data missing" on a CI runner or in a worktree.
METHODS_REPO = Path(__file__).resolve().parents[3]
# Portable sibling root: was hardcoded to the author's /home/sagemaker-user checkout, so the
# guard below reported "not available" on every CI runner -- even though the workflow checks
# this sibling out and exports its root. `or` rather than a .get() default, so an EMPTY value
# falls back too instead of yielding Path("") == the CWD, which reads as a plausible wrong root.
CONTRACTS_ROOT = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT")
    or METHODS_REPO.parent / "rnd-computational-biology-oncology-target-contracts"
)


def _build_synthetic_depmap_dir(target_dir: Path, n_cell_lines: int = 100) -> None:
    """Build a synthetic DepMap dir with CRISPRGeneEffect.csv + Model.csv.

    KRAS dependency designed as bimodal-selective:
      - ~25% of cells (colorectal-lineage subset) → Chronos in [-2.0, -1.0] (strong dep)
      - ~75% of cells → Chronos in [-0.4, 0.3] (non-essential to mild)
    """
    import numpy as np

    rng = np.random.default_rng(seed=42)

    # Cell line IDs (ACH-XXXXXX format)
    cell_line_ids = [f"ACH-{i:06d}" for i in range(n_cell_lines)]

    # Assign lineages: 25% colorectal, 25% lung_nsclc, 20% pancreas, 15% breast, rest skin
    n_colorectal = int(0.25 * n_cell_lines)
    n_lung = int(0.25 * n_cell_lines)
    n_pancreas = int(0.20 * n_cell_lines)
    n_breast = int(0.15 * n_cell_lines)
    n_skin = n_cell_lines - (n_colorectal + n_lung + n_pancreas + n_breast)
    lineage_pool = (
        ["colorectal"] * n_colorectal
        + ["lung_nsclc"] * n_lung
        + ["pancreas"] * n_pancreas
        + ["breast"] * n_breast
        + ["skin"] * n_skin
    )
    assert len(lineage_pool) == n_cell_lines, f"lineage_pool length mismatch: {len(lineage_pool)} != {n_cell_lines}"
    rng.shuffle(lineage_pool)

    # KRAS Chronos: colorectal + pancreas lines get strong dependency; rest don't
    kras_chronos = []
    for lineage in lineage_pool:
        if lineage in ("colorectal", "pancreas"):
            # Strong dep: tight cluster around -1.4
            kras_chronos.append(float(rng.normal(loc=-1.4, scale=0.25)))
        else:
            # Non-essential: cluster around -0.1
            kras_chronos.append(float(rng.normal(loc=-0.1, scale=0.2)))

    # Build CRISPRGeneEffect.csv (one row per cell line, one column per gene)
    # Include KRAS column + a few decoys for realism
    crispr_df = pd.DataFrame(
        {
            "ModelID": cell_line_ids,
            "KRAS (3845)": kras_chronos,
            "EGFR (1956)": rng.normal(loc=-0.3, scale=0.4, size=n_cell_lines).tolist(),
            "TP53 (7157)": rng.normal(loc=-0.1, scale=0.3, size=n_cell_lines).tolist(),
        }
    )
    crispr_df.to_csv(target_dir / "CRISPRGeneEffect.csv", index=False)

    # Build Model.csv
    model_df = pd.DataFrame(
        {
            "ModelID": cell_line_ids,
            "CellLineName": [f"CL{i}" for i in range(n_cell_lines)],
            "OncotreeLineage": lineage_pool,
            "OncotreeSubtype": ["adenocarcinoma"] * n_cell_lines,
            "PrimaryDisease": [
                "Colon/Colorectal Cancer"
                if lg == "colorectal"
                else "Non-Small Cell Lung Cancer"
                if lg == "lung_nsclc"
                else "Pancreatic Cancer"
                if lg == "pancreas"
                else "Breast Cancer"
                if lg == "breast"
                else "Other"
                for lg in lineage_pool
            ],
        }
    )
    model_df.to_csv(target_dir / "Model.csv", index=False)


def test_synthetic_kras_distribution(tmp_path, monkeypatch):
    """End-to-end synthetic test: build synthetic DepMap → run method → validate outputs."""
    # Stage synthetic DepMap data
    fake_depmap = tmp_path / "depmap-26q1"
    fake_depmap.mkdir()
    _build_synthetic_depmap_dir(fake_depmap, n_cell_lines=200)

    # Patch the method's fallback dirs to include our synthetic dir
    import sys

    sys.path.insert(0, str(METHODS_REPO))
    import methods.depmap_chronos_distribution.cli as cli_mod

    monkeypatch.setattr(cli_mod, "DEPMAP_LOCAL_FALLBACK_DIRS", [fake_depmap])

    # Run the method's load + analysis logic directly
    chronos_by_model, model_metadata, load_errors = cli_mod.load_depmap_files(release_pin="26q1", target_symbol="KRAS")
    assert load_errors == [], f"expected clean load; got: {load_errors}"
    assert len(chronos_by_model) == 200

    summary = cli_mod.compute_summary_stats(
        chronos_by_model,
        model_metadata,
        strong_threshold=-1.0,
        moderate_threshold=-0.5,
    )

    # === Validate summary scalars ===
    assert summary["n_cell_lines_evaluated"] == 200
    assert -1.0 < summary["median_chronos_panel"] < 0.5, (
        f"median should sit near 0 for bimodal; got {summary['median_chronos_panel']}"
    )
    # ~45% of cells are colorectal+pancreas → all strongly dependent
    assert 0.30 < summary["fraction_strongly_dependent"] < 0.55, (
        f"frac_strong should be ~45% for bimodal; got {summary['fraction_strongly_dependent']}"
    )
    # Bimodal-selective is the expected shape classification
    assert summary["distribution_shape"] in ("bimodal_selective", "shifted_dependent"), (
        f"expected bimodal/shifted shape; got {summary['distribution_shape']}"
    )

    # === dependency_class (Tier-2 categorical) — must be one of the declared vocabulary ===
    assert "dependency_class" in summary, (
        "method must emit dependency_class (declared in card_spec summary_fields_vocabulary)"
    )
    assert summary["dependency_class"] in (
        "common_essential",
        "strongly_selective",
        "broadly_dependent",
        "non_dependent",
        "data_unavailable",
    ), f"dependency_class outside vocabulary: {summary['dependency_class']!r}"
    # Synthetic KRAS is bimodal-selective by design → expect strongly_selective or broadly_dependent
    assert summary["dependency_class"] in ("strongly_selective", "broadly_dependent"), (
        f"synthetic KRAS should be strongly_selective or broadly_dependent; got {summary['dependency_class']!r}"
    )

    # === Lineage tail enrichment: colorectal + pancreas should dominate dependent tail ===
    top_lineages = summary["top_dependent_lineages"]
    top_lineage_names = [l["lineage"] for l in top_lineages]
    assert "colorectal" in top_lineage_names
    assert "pancreas" in top_lineage_names

    # === Now run the full CLI path including figure emission ===
    out = tmp_path / "card_output"
    out.mkdir()
    cli_mod.emit_waterfall_plot(chronos_by_model, model_metadata, "KRAS", summary, out, CONTRACTS_ROOT)
    cli_mod.emit_histogram_kde_plot(chronos_by_model, "KRAS", summary, out, CONTRACTS_ROOT)
    cli_mod.emit_plot_data(chronos_by_model, model_metadata, -1.0, out)
    cli_mod.emit_manifest("KRAS", "26q1", summary, chronos_by_model, out, [])

    # === Validate emitted artifacts ===
    waterfall = out / "figure_waterfall.svg"
    histogram = out / "figure_histogram_kde.svg"
    plot_data = out / "plot_data.parquet"
    manifest = out / "manifest.yaml"

    assert waterfall.exists() and waterfall.stat().st_size > 1000, "waterfall SVG missing or too small"
    assert histogram.exists() and histogram.stat().st_size > 1000, "histogram SVG missing or too small"
    assert plot_data.exists(), "plot_data.parquet missing"
    assert manifest.exists(), "manifest.yaml missing"

    # === Validate plot_data.parquet content ===
    pdf = pd.read_parquet(plot_data)
    assert len(pdf) == 200
    expected_cols = {
        "cell_line_id",
        "cell_line_name",
        "chronos_score",
        "lineage",
        "is_strongly_dependent",
        "rank_in_panel",
        "quartile",
    }
    assert expected_cols.issubset(set(pdf.columns)), f"missing: {expected_cols - set(pdf.columns)}"
    assert pdf["chronos_score"].is_monotonic_increasing, "plot_data should be sorted ascending"

    # === Validate manifest.yaml content ===
    with manifest.open() as f:
        mani = yaml.safe_load(f)
    assert mani["method"] == "depmap-chronos-distribution"
    assert mani["target"] == "KRAS"
    assert mani["release_pin"] == "26q1"
    assert mani["cell_lines_total_count"] == 200
    assert mani["input_files_consumed"] == ["CRISPRGeneEffect.csv", "Model.csv"]


def test_synthetic_kras_full_cli_invocation(tmp_path, monkeypatch):
    """Run the full CLI as a subprocess against synthetic data."""
    import sys

    # Stage synthetic DepMap data
    fake_depmap = tmp_path / "depmap-26q1"
    fake_depmap.mkdir()
    _build_synthetic_depmap_dir(fake_depmap, n_cell_lines=150)

    # Set env so the CLI picks up the synthetic dir
    # We do this by monkeypatching the module then invoking main() directly,
    # because the CLI doesn't accept an explicit local-cache arg yet.
    sys.path.insert(0, str(METHODS_REPO))
    import methods.depmap_chronos_distribution.cli as cli_mod

    monkeypatch.setattr(cli_mod, "DEPMAP_LOCAL_FALLBACK_DIRS", [fake_depmap])

    out = tmp_path / "out"
    # Invoke main() via Click testing
    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.main,
        [
            "--target",
            "KRAS",
            "--release-pin",
            "26q1",
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, f"CLI failed: {result.output}\n{result.exception}"

    summary_path = out / "summary.json"
    assert summary_path.exists()
    with summary_path.open() as f:
        summary = json.load(f)
    assert summary["n_cell_lines_evaluated"] == 150
    assert "distribution_shape" in summary


# ===========================================================================
# DepMap-power admissibility guard (2026-07-17) — the EGFR/FLT3/IDH1 case.
# A dependency concentrated in ONE small lineage, diluted below the 5% pooled
# floor, must classify as `non_dependent_underpowered` (→ insufficient), NOT
# `non_dependent` (→ false-negative veto).
# ===========================================================================


def _build_underpowered_depmap_dir(target_dir, n_cell_lines=300):
    """One small lineage (9 lines, 3% of a 300-line panel) is STRONGLY dependent on
    the target; all other lineages non-dependent. Pooled fraction_strongly_dependent
    = 9/300 = 3% — BELOW the 5% selective_min floor, so the pooled call is
    `non_dependent` (would VETO) — but the lung lineage (n=9 >= 5) is clearly
    concentrated-dependent (100% strong). This is the exact EGFR-mut-lung / FLT3-mut-AML
    under-sampling case the guard must catch: below-floor pooled negative contradicted
    by a well-sampled concentrated lineage → non_dependent_underpowered, not a veto."""
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(seed=7)
    cell_line_ids = [f"ACH-{i:06d}" for i in range(n_cell_lines)]

    n_lung = 9  # the dependent lineage: >=5 (admissible) but only 3% of the panel
    lineage_pool = ["lung_nsclc"] * n_lung + ["other"] * (n_cell_lines - n_lung)
    rng.shuffle(lineage_pool)

    chronos = []
    for lg in lineage_pool:
        if lg == "lung_nsclc":
            chronos.append(float(rng.normal(loc=-1.5, scale=0.15)))  # strong dep
        else:
            chronos.append(float(rng.normal(loc=-0.05, scale=0.15)))  # non-essential
    crispr_df = pd.DataFrame({"ModelID": cell_line_ids, "EGFR (1956)": chronos})
    crispr_df.to_csv(target_dir / "CRISPRGeneEffect.csv", index=False)
    model_df = pd.DataFrame(
        {
            "ModelID": cell_line_ids,
            "CellLineName": [f"CL{i}" for i in range(n_cell_lines)],
            "OncotreeLineage": lineage_pool,
            "OncotreeSubtype": ["adenocarcinoma"] * n_cell_lines,
            "PrimaryDisease": ["Non-Small Cell Lung Cancer" if lg == "lung_nsclc" else "Other" for lg in lineage_pool],
        }
    )
    model_df.to_csv(target_dir / "Model.csv", index=False)


def test_underpowered_lineage_not_false_negative(tmp_path, monkeypatch):
    """The guard: a lineage-concentrated dependency diluted below the pooled floor
    classifies as non_dependent_underpowered, NOT non_dependent."""
    import sys

    fake = tmp_path / "depmap-26q1"
    fake.mkdir()
    _build_underpowered_depmap_dir(fake, n_cell_lines=300)
    sys.path.insert(0, str(METHODS_REPO))
    import methods.depmap_chronos_distribution.cli as cli_mod

    monkeypatch.setattr(cli_mod, "DEPMAP_LOCAL_FALLBACK_DIRS", [fake])

    chronos_by_model, meta, errs = cli_mod.load_depmap_files(release_pin="26q1", target_symbol="EGFR")
    assert errs == []
    summary = cli_mod.compute_summary_stats(chronos_by_model, meta, strong_threshold=-1.0, moderate_threshold=-0.5)

    # Pooled fraction is BELOW the 5% floor (9/300 = 3%) — pooled call is non_dependent...
    assert summary["fraction_strongly_dependent"] < 0.05, (
        f"test fixture must dilute below the floor; got {summary['fraction_strongly_dependent']:.3f}"
    )
    # ...but lung (n=9) is concentrated-dependent, so the guard must fire:
    assert summary["dependency_class"] == "non_dependent_underpowered", (
        f"expected underpowered guard to fire (lung concentrated-dependent, pooled diluted); "
        f"got {summary['dependency_class']!r} @ frac={summary['fraction_strongly_dependent']:.3f}"
    )


def test_genuine_non_dependent_still_classifies_non_dependent(tmp_path, monkeypatch):
    """CONTROL: a target non-dependent EVERYWHERE (no concentrated lineage) must
    still classify non_dependent — the guard must not fire spuriously."""
    import sys

    import numpy as np
    import pandas as pd

    fake = tmp_path / "depmap-26q1"
    fake.mkdir()
    rng = np.random.default_rng(seed=11)
    n = 200
    ids = [f"ACH-{i:06d}" for i in range(n)]
    # everyone non-essential; lineages present but NONE concentrated-dependent
    lineages = ["lung_nsclc"] * 40 + ["colorectal"] * 40 + ["breast"] * 40 + ["skin"] * 40 + ["pancreas"] * 40
    rng.shuffle(lineages)
    chronos = rng.normal(loc=-0.05, scale=0.15, size=n).tolist()
    pd.DataFrame({"ModelID": ids, "FOOBAR (999)": chronos}).to_csv(fake / "CRISPRGeneEffect.csv", index=False)
    pd.DataFrame(
        {
            "ModelID": ids,
            "CellLineName": [f"CL{i}" for i in range(n)],
            "OncotreeLineage": lineages,
            "OncotreeSubtype": ["x"] * n,
            "PrimaryDisease": ["Other"] * n,
        }
    ).to_csv(fake / "Model.csv", index=False)
    sys.path.insert(0, str(METHODS_REPO))
    import methods.depmap_chronos_distribution.cli as cli_mod

    monkeypatch.setattr(cli_mod, "DEPMAP_LOCAL_FALLBACK_DIRS", [fake])
    chronos_by_model, meta, errs = cli_mod.load_depmap_files(release_pin="26q1", target_symbol="FOOBAR")
    summary = cli_mod.compute_summary_stats(chronos_by_model, meta, strong_threshold=-1.0, moderate_threshold=-0.5)
    assert summary["dependency_class"] == "non_dependent", (
        f"genuine non-dependent must NOT trip the guard; got {summary['dependency_class']!r}"
    )
