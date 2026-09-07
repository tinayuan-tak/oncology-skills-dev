"""Tests for subgroup_assigner_classifier CLI (Modality C / Phase 2a.3).

test_napy_classifier_argmax: unit test — 4-sample NAPY assignment works.
test_single_gene_threshold: unit test — DLL3-high threshold correctly classifies.
test_e2e_napy_synthetic_depmap: E2E with synthetic DepMap expression + SCLC catalog.
"""

import os
import subprocess
from pathlib import Path

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
            "ASCL1": [10, 1, 1, 1],
            "NEUROD1": [1, 10, 1, 1],
            "POU2F3": [1, 1, 10, 1],
            "YAP1": [1, 1, 1, 10],
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


def _napy_config(min_margin=0.0, min_zscore=0.0):
    return {
        "classifier_method": "napy_zscore_classifier",
        "marker_genes": {"SCLC_A": "ASCL1", "SCLC_N": "NEUROD1", "SCLC_P": "POU2F3", "SCLC_Y": "YAP1"},
        "min_zscore": min_zscore,
        "min_margin": min_margin,
    }


def test_min_margin_default_zero_is_backward_compatible():
    """min_margin=0.0 (default) → pure argmax, byte-identical to the prior behaviour."""
    from methods.subgroup_assigner_classifier.cli import _run_napy_classifier

    expr = pd.DataFrame(
        {"ASCL1": [10, 1, 1, 1], "NEUROD1": [1, 10, 1, 1], "POU2F3": [1, 1, 10, 1], "YAP1": [1, 1, 1, 10]},
        index=["S_A", "S_N", "S_P", "S_Y"],
    )
    out = _run_napy_classifier(expr, _napy_config(min_margin=0.0))
    a = out[(out["sample_id"] == "S_A") & (out["stratum_id"] == "SCLC_A")]
    assert (a["is_member"] == True).all()  # clean argmax still assigns


def test_min_margin_leaves_co_expressing_sample_unclassifiable():
    """A sample high in BOTH ASCL1 and NEUROD1 (co-expressed, tiny margin) → unclassifiable under a
    margin requirement, instead of being force-assigned to the marginally-higher marker."""
    from methods.subgroup_assigner_classifier.cli import _run_napy_classifier

    # S_mix: ASCL1 and NEUROD1 nearly tied (both high); clean singles for the others to set the z-scale.
    expr = pd.DataFrame(
        {
            "ASCL1": [10, 1, 1, 1, 9.6],
            "NEUROD1": [1, 10, 1, 1, 9.5],
            "POU2F3": [1, 1, 10, 1, 1],
            "YAP1": [1, 1, 1, 10, 1],
        },
        index=["S_A", "S_N", "S_P", "S_Y", "S_mix"],
    )
    out = _run_napy_classifier(expr, _napy_config(min_margin=1.0))
    mix = out[out["sample_id"] == "S_mix"]
    # no stratum is a member (unclassifiable) — the two lineage-TFs are co-expressed within the margin
    assert (mix["is_member"] == False).all()
    # the would-be-winner row carries a visible unclassifiable reason
    flagged = mix[mix["derivation_value"].str.startswith("unclassifiable:")]
    assert len(flagged) == 1 and "below_margin" in flagged.iloc[0]["derivation_value"]
    # a CLEAN single-marker sample is still committed under the same margin
    a = out[(out["sample_id"] == "S_A") & (out["stratum_id"] == "SCLC_A")]
    assert (a["is_member"] == True).all()


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
    # Stage fixture under tmp_path/.cache (not the real ~/.cache) via FRAMEWORK_CACHE_ROOT.
    cache = tmp_path / ".cache" / "framework-depmap-26q1"
    cache.mkdir(parents=True, exist_ok=True)
    exp_path = cache / "OmicsExpressionProteinCodingGenesTPMLogp1.csv"

    # 8 cell lines: 2 each dominant in A/N/P/Y.
    # Column format mirrors the real DepMap 26Q1 file: 'SYMBOL (EntrezID)', plus
    # ModelID + IsDefaultEntryForModel metadata columns.
    n = 8
    model_ids = [f"ACH-{i:06d}" for i in range(n)]
    exp_df = pd.DataFrame(
        {
            "ModelID": model_ids,
            "IsDefaultEntryForModel": ["Yes"] * n,
            "ASCL1 (429)": [10, 10, 1, 1, 1, 1, 1, 1],
            "NEUROD1 (4760)": [1, 1, 10, 10, 1, 1, 1, 1],
            "POU2F3 (25833)": [1, 1, 1, 1, 10, 10, 1, 1],
            "YAP1 (10413)": [1, 1, 1, 1, 1, 1, 10, 10],
            "DLL3 (10683)": [8, 8, 8, 8, 1, 1, 1, 1],
        },
    )
    exp_df.to_csv(exp_path, index=False)

    catalog_path = CATALOG_REPO / "subgroup-catalogs" / "SCLC" / "2026-Q3.yaml"
    if not catalog_path.exists():
        pytest.skip(f"SCLC catalog not landed on this branch/main: {catalog_path}")

    config_path = (
        METHODS_REPO / "methods" / "subgroup_assigner_classifier" / "example-configs" / "sclc-napy-2026-q3.yaml"
    )

    out_dir = tmp_path / "sac_out"
    result = subprocess.run(
        [
            "python",
            "-m",
            "methods.subgroup_assigner_classifier.cli",
            "--subgroup-catalog",
            str(catalog_path),
            "--classifier-config",
            str(config_path),
            "--data-source",
            "depmap",
            "--release-pin",
            "2026-Q3",
            "--catalog-repo",
            str(CATALOG_REPO),
            "--out",
            str(out_dir),
        ],
        cwd=METHODS_REPO,
        capture_output=True,
        text=True,
        env={**os.environ, "FRAMEWORK_CACHE_ROOT": str(tmp_path / ".cache")},
    )
    assert result.returncode == 0, f"CLI failed: {result.stderr}\nstdout:\n{result.stdout}"

    parquet_path = out_dir / "assignments.parquet"
    manifest_path = out_dir / "manifest.yaml"
    assert parquet_path.exists()
    assert manifest_path.exists()

    assignments = pd.read_parquet(parquet_path)
    expected_cols = {
        "sample_id",
        "patient_id",
        "source_native_id",
        "stratum_id",
        "is_member",
        "derivation_source",
        "derivation_value",
        "evaluated_at_release",
    }
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

    # Manifest is the schema-valid subgroup_assignment_product shape (variant=classifier)
    manifest = yaml.safe_load(manifest_path.read_text())
    assert manifest["manifest_kind"] == "subgroup_assignment_product"
    assert manifest["indication"] == "SCLC"
    # bare 'subgroup_assigner_classifier' maps to the schema enum '_classifier_run'
    assert manifest["assigner_method"] == "subgroup_assigner_classifier_run"
    # NB: classifier_config_ref is intentionally NOT on the manifest (schema has
    # unevaluatedProperties:false + no such field). Config lineage → input_manifest_ids.
    assert "classifier_config_ref" not in manifest
    # NAPY config covers SCLC_A/N/P/Y only (DLL3_high is single_gene_zscore_threshold,
    # skipped by method filter — requires a separate dll3-high config invocation)
    strata = {s["subgroup_id"] for s in manifest["strata_summary"]}
    assert strata >= {"SCLC_A", "SCLC_N", "SCLC_P", "SCLC_Y"}
    assert "DLL3_high" not in strata
