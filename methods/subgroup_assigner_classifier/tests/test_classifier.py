"""Tests for subgroup_assigner_classifier CLI (Modality C / Phase 2a.3).

test_napy_classifier_argmax: unit test — 4-sample NAPY assignment works.
test_single_gene_threshold: unit test — DLL3-high threshold correctly classifies.
test_e2e_napy_synthetic_depmap: E2E with synthetic DepMap expression + SCLC catalog.
"""

import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

METHODS_REPO = Path("/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods")
CATALOG_REPO = Path("/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog")


def test_napy_classifier_argmax():
    """4 samples, each expressing 1 marker gene high — should assign to the matching stratum."""
    from methods.subgroup_assigner_classifier.cli import _run_napy_classifier
    # 4 samples: A-dominant, N-dominant, P-dominant, Y-dominant
    expression = pd.DataFrame(
        {
            "ASCL1":   [10, 1, 1, 1],
            "NEUROD1": [1, 10, 1, 1],
            "POU2F3":  [1, 1, 10, 1],
            "YAP1":    [1, 1, 1, 10],
        },
        index=["Sample_A", "Sample_N", "Sample_P", "Sample_Y"],
    )
    config = {
        "classifier_method": "napy_zscore_classifier",
        "marker_genes": {
            "SCLC_A": "ASCL1",
            "SCLC_N": "NEUROD1",
            "SCLC_P": "POU2F3",
            "SCLC_Y": "YAP1",
        },
        "min_zscore": 0.0,
    }
    out = _run_napy_classifier(expression, config)
    # Sample_A → is_member True only for SCLC_A
    sample_A_rows = out[out["sample_id"] == "Sample_A"]
    assert (sample_A_rows[sample_A_rows["stratum_id"] == "SCLC_A"]["is_member"] == True).all()
    assert (sample_A_rows[sample_A_rows["stratum_id"] != "SCLC_A"]["is_member"] == False).all()
    # Sample_Y → is_member True only for SCLC_Y
    sample_Y_rows = out[out["sample_id"] == "Sample_Y"]
    assert (sample_Y_rows[sample_Y_rows["stratum_id"] == "SCLC_Y"]["is_member"] == True).all()


def test_single_gene_threshold():
    """DLL3-high threshold: sample with z-score >= threshold is member."""
    from methods.subgroup_assigner_classifier.cli import _run_single_gene_threshold
    expression = pd.DataFrame(
        {"DLL3": [10, 5, 3, 1, 0]},  # z-scores will span roughly -1 to +1.5
        index=[f"Sample_{i}" for i in range(5)],
    )
    config = {
        "classifier_method": "single_gene_zscore_threshold",
        "marker_gene": "DLL3",
        "zscore_threshold": 1.0,
        "label_when_high": "DLL3_high",
    }
    out = _run_single_gene_threshold(expression, config)
    # Sample_0 (z=10) should exceed threshold
    assert out[out["sample_id"] == "Sample_0"]["is_member"].iloc[0] == True
    # Sample_4 (lowest DLL3) should not
    assert out[out["sample_id"] == "Sample_4"]["is_member"].iloc[0] == False


def test_e2e_napy_synthetic_depmap(tmp_path):
    """End-to-end: synthetic DepMap expression + SCLC catalog + NAPY config."""
    # Fabricate a DepMap-shaped expression matrix
    cache = Path.home() / ".cache" / "framework-depmap-26q1"
    cache.mkdir(parents=True, exist_ok=True)
    exp_path = cache / "OmicsExpressionProteinCodingGenesTPMLogp1.csv"

    # 8 cell lines: 2 each dominant in A/N/P/Y
    rng = np.random.default_rng(42)
    n = 8
    exp_df = pd.DataFrame(
        {
            "ASCL1":   [10, 10, 1, 1, 1, 1, 1, 1],
            "NEUROD1": [1, 1, 10, 10, 1, 1, 1, 1],
            "POU2F3":  [1, 1, 1, 1, 10, 10, 1, 1],
            "YAP1":    [1, 1, 1, 1, 1, 1, 10, 10],
            "DLL3":    [8, 8, 8, 8, 1, 1, 1, 1],  # NE-high (A/N) have high DLL3
        },
        index=[f"ACH-{i:06d}" for i in range(n)],
    )
    exp_df.index.name = "ModelID"
    exp_df.to_csv(exp_path)

    catalog_path = CATALOG_REPO / "subgroup-catalogs" / "SCLC" / "2026-Q3.yaml"
    if not catalog_path.exists():
        pytest.skip(f"SCLC catalog not landed on this branch/main: {catalog_path}")

    config_path = METHODS_REPO / "methods" / "subgroup_assigner_classifier" / "example-configs" / "sclc-napy-2026-q3.yaml"

    out_dir = tmp_path / "sac_out"
    result = subprocess.run(
        [
            "python", "-m", "methods.subgroup_assigner_classifier.cli",
            "--subgroup-catalog", str(catalog_path),
            "--classifier-config", str(config_path),
            "--data-source", "depmap",
            "--release-pin", "2026-Q3",
            "--catalog-repo", str(CATALOG_REPO),
            "--out", str(out_dir),
        ],
        cwd=METHODS_REPO, capture_output=True, text=True,
    )
    assert result.returncode == 0, f"CLI failed: {result.stderr}\nstdout:\n{result.stdout}"

    parquet_path = out_dir / "assignments.parquet"
    manifest_path = out_dir / "manifest.yaml"
    assert parquet_path.exists()
    assert manifest_path.exists()

    assignments = pd.read_parquet(parquet_path)
    expected_cols = {"sample_id", "patient_id", "source_native_id", "stratum_id",
                     "is_member", "derivation_source", "derivation_value",
                     "evaluated_at_release"}
    assert expected_cols.issubset(set(assignments.columns))

    # SCLC_A should have 2 members (ACH-000000, ACH-000001)
    sclc_a = assignments[assignments["stratum_id"] == "SCLC_A"]
    assert (sclc_a["is_member"] == True).sum() == 2
    # Same for N, P, Y (all get 2 each in this synthetic setup)
    sclc_n = assignments[assignments["stratum_id"] == "SCLC_N"]
    assert (sclc_n["is_member"] == True).sum() == 2
    sclc_p = assignments[assignments["stratum_id"] == "SCLC_P"]
    assert (sclc_p["is_member"] == True).sum() == 2
    sclc_y = assignments[assignments["stratum_id"] == "SCLC_Y"]
    assert (sclc_y["is_member"] == True).sum() == 2

    # Manifest shape
    manifest = yaml.safe_load(manifest_path.read_text())
    assert manifest["manifest_kind"] == "subgroup_assignment"
    assert manifest["indication"] == "SCLC"
    assert manifest["classifier_config_ref"]["classifier_method"] == "napy_zscore_classifier"
    assert set(manifest["strata_evaluated"]) >= {"SCLC_A", "SCLC_N", "SCLC_P", "SCLC_Y"}
