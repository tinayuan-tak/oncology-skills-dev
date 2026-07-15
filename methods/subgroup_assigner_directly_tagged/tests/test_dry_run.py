"""Smoke tests for subgroup_assigner_directly_tagged CLI.

test_dry_run_on_coadread_tcga: dry-run path parses catalog cleanly.
test_real_execution_synthetic_tcga: real (non-dry) execution against a
    synthetic TCGA-marker-paper CSV to verify the rule-evaluator +
    parquet-emitter + manifest-emitter end-to-end.
test_rule_parser_supported_forms: unit-level tests of the CEL-subset parser.
"""

import subprocess
from pathlib import Path

import pandas as pd
import pytest
import yaml

METHODS_REPO = Path("/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods")
CATALOG_REPO = Path("/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog")


def test_dry_run_on_coadread_tcga():
    """Dry-run against COADREAD catalog with tcga data source emits the plan without error."""
    catalog_path = CATALOG_REPO / "subgroup-catalogs" / "COADREAD" / "2026-Q2.yaml"
    result = subprocess.run(
        [
            "python", "-m", "methods.subgroup_assigner_directly_tagged.cli",
            "--subgroup-catalog", str(catalog_path),
            "--data-source", "tcga",
            "--release-pin", "2026-Q2",
            "--catalog-repo", str(CATALOG_REPO),
            "--out", "/tmp/sat_dryrun",
            "--dry-run",
        ],
        cwd=METHODS_REPO, capture_output=True, text=True,
    )
    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    assert "subgroup_assigner_directly_tagged" in result.stdout
    assert "MSI_H" in result.stdout
    assert "MSS" in result.stdout
    assert "skipped strata" in result.stdout
    assert "KRAS_mut" in result.stdout


def test_rule_parser_supported_forms():
    """Unit tests for the CEL-subset rule parser."""
    from methods.subgroup_assigner_directly_tagged.cli import parse_rule
    # Simple equals
    lhs, op, values = parse_rule("clinical.MSI_status == 'MSI-H'")
    assert lhs == "clinical.MSI_status"
    assert op == "eq"
    assert values == ["MSI-H"]
    # in-list
    lhs, op, values = parse_rule("clinical.primary_site in ['cecum', 'ascending_colon']")
    assert lhs == "clinical.primary_site"
    assert op == "in"
    assert values == ["cecum", "ascending_colon"]
    # Unsupported form (MAF predicate) → ValueError
    with pytest.raises(ValueError, match="Unsupported rule form"):
        parse_rule("gene_symbol == 'KRAS' && protein_change == 'p.G12C'")


def test_real_execution_synthetic_tcga(tmp_path):
    """End-to-end test with a synthetic TCGA-marker-paper CSV in the cache location.

    Places a fabricated marker-paper CSV in the loader's fallback location, runs
    the CLI real-mode, and asserts:
      - assignments.parquet exists with expected columns
      - manifest.yaml validates against subgroup_assignment.schema.json shape
      - MSI_H stratum recovers the synthetic MSI-H patients
      - is_member=null rows correctly represent source-value missing
    """
    # Fabricate a 10-row TCGA-marker-paper CSV in the loader's fallback path
    cache = Path.home() / ".cache" / "framework-tcga-marker-paper" / "coadread"
    cache.mkdir(parents=True, exist_ok=True)
    csv_path = cache / "subtypes.csv"

    df = pd.DataFrame({
        "sample_id":        [f"TCGA-XX-000{i}-01" for i in range(10)],
        "patient_id":       [f"TCGA-XX-000{i}"     for i in range(10)],
        "source_native_id": [f"TCGA-XX-000{i}-01A" for i in range(10)],
        "MSI_status":       ["MSI-H", "MSI-H", "MSS", "MSS", "MSS", "MSS", "MSS", None, None, "MSS"],
        "primary_site":     ["cecum", "sigmoid_colon", "cecum", "descending_colon", "rectum",
                              "ascending_colon", "hepatic_flexure", "cecum", "rectum", "transverse_colon"],
    })
    df.to_csv(csv_path, index=False)

    catalog_path = CATALOG_REPO / "subgroup-catalogs" / "COADREAD" / "2026-Q2.yaml"
    out_dir = tmp_path / "sat_out"
    result = subprocess.run(
        [
            "python", "-m", "methods.subgroup_assigner_directly_tagged.cli",
            "--subgroup-catalog", str(catalog_path),
            "--data-source", "tcga",
            "--release-pin", "2026-Q2",
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
    expected_cols = {"sample_id", "patient_id", "source_native_id",
                     "stratum_id", "is_member", "derivation_source",
                     "derivation_value", "evaluated_at_release"}
    assert expected_cols.issubset(set(assignments.columns))

    # Assert MSI_H stratum: 2 samples with MSI-H should be_member=true,
    # 6 samples with MSS should be_member=false, 2 with null MSI_status
    # should be_member=null (tri-value → insufficient).
    msi_h = assignments[assignments["stratum_id"] == "MSI_H"]
    assert (msi_h["is_member"] == True).sum() == 2
    assert (msi_h["is_member"] == False).sum() == 6
    assert msi_h["is_member"].isna().sum() == 2

    # Manifest validates schema shape
    manifest = yaml.safe_load(manifest_path.read_text())
    assert manifest["manifest_kind"] == "subgroup_assignment"
    assert manifest["indication"] == "COADREAD"
    assert manifest["data_source"] == "tcga"
    assert "MSI_H" in manifest["strata_evaluated"]
    assert manifest["assignments_parquet"]["n_samples"] == 10
    assert len(manifest["assignments_parquet"]["md5"]) == 32
