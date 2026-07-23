"""Smoke tests for subgroup_assigner_directly_tagged CLI.

test_dry_run_on_coadread_tcga: dry-run path parses catalog cleanly.
test_real_execution_synthetic_tcga: real (non-dry) execution against a
    synthetic TCGA-marker-paper CSV to verify the rule-evaluator +
    parquet-emitter + manifest-emitter end-to-end.
test_rule_parser_supported_forms: unit-level tests of the CEL-subset parser.
test_fusion_evaluator_tri_value: unit test of the fusion-consensus evaluator's
    true/false/null tri-value logic + caller_count threshold.
test_fusion_real_execution_synthetic: real CLI run against a synthetic NSCLC
    catalog + staged consensus/coverage parquet fixtures.
"""

import os
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
    # Fabricate a 10-row TCGA-marker-paper CSV under a TMP cache root
    # (FRAMEWORK_CACHE_ROOT), never the real ~/.cache — a subprocess writing the
    # real path would clobber real cached data (and, with no Guinney CMS files in
    # the tmp root, the CMS outer-join self-skips, keeping the fixture hermetic).
    cache_root = tmp_path / ".cache"
    cache = cache_root / "framework-tcga-marker-paper" / "coadread"
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
        env={**os.environ, "FRAMEWORK_CACHE_ROOT": str(cache_root)},
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

    # MSI_H tri-value on the synthetic fixture (hermetic: no Guinney CMS join in
    # the tmp cache root, so counts are exactly the 10-row fixture). 2 MSI-H, 6
    # MSS non-members, 2 null-MSI_status insufficient.
    msi_h = assignments[assignments["stratum_id"] == "MSI_H"]
    assert (msi_h["is_member"] == True).sum() == 2
    assert (msi_h["is_member"] == False).sum() == 6
    assert msi_h["is_member"].isna().sum() == 2

    # Manifest is the schema-valid subgroup_assignment_product shape.
    manifest = yaml.safe_load(manifest_path.read_text())
    assert manifest["manifest_kind"] == "subgroup_assignment_product"
    assert manifest["indication"] == "COADREAD"
    assert manifest["data_source"] == "tcga"
    assert manifest["assignment_product_id"] == "subgroup-assignments-coadread-tcga-2026-q2"
    # strata_summary carries per-stratum member counts — exact on the hermetic fixture.
    strata = {s["subgroup_id"]: s for s in manifest["strata_summary"]}
    assert strata["MSI_H"]["n_samples"] == 2
    assert manifest["n_samples_total"] == 10
    # content-pin (sha256) + provenance present
    assert len(manifest["subgroup_catalog_content_pin"]) == 64
    assert manifest["generated_by"].startswith("methods/subgroup_assigner_directly_tagged@")


# ---------- Fusion-consensus path -----------------------------------------

def _synthetic_consensus_df():
    """4 lung samples: S1 has ALK (3-caller), S2 has ALK (1-caller), S3 has ROS1
    (2-caller), S4 has no fusion (assayed, will come from coverage only)."""
    return pd.DataFrame({
        "sample_key":  ["TCGA-AA-0001-01", "TCGA-AA-0002-01", "TCGA-AA-0003-01"],
        "gene_symbol": ["ALK",             "ALK",             "ROS1"],
        "tissue":      ["LUAD",            "LUSC",            "LUAD"],
        "caller_count":[3,                 1,                 2],
        "callers_supporting": [["tumorfusions", "gao_2018", "cbioportal"],
                               ["tumorfusions"],
                               ["tumorfusions", "cbioportal"]],
    })


def _synthetic_coverage_df():
    """5 assayed lung samples (S1-S4 lung + one BRCA that must be excluded by
    the tissue filter). S4 is assayed but carries no fusion → true negative."""
    return pd.DataFrame({
        "sample_key": ["TCGA-AA-0001-01", "TCGA-AA-0002-01", "TCGA-AA-0003-01",
                       "TCGA-AA-0004-01", "TCGA-BB-9999-01"],
        "tissue":     ["LUAD", "LUSC", "LUAD", "LUAD", "BRCA"],
        "caller":     ["tumorfusions"] * 5,
    })


def test_fusion_evaluator_tri_value():
    """Unit test: _evaluate_fusion_stratum tri-value + caller_count threshold."""
    from methods.subgroup_assigner_directly_tagged.cli import _evaluate_fusion_stratum

    fusion_df = _synthetic_consensus_df()
    coverage_df = _synthetic_coverage_df()
    tissue_filter = ["LUAD", "LUSC"]

    # ALK, min_caller_count=1 (union): S1 + S2 are members; S3 assayed-no-ALK →
    # false; S4 assayed-no-fusion → false; BRCA excluded by tissue filter.
    alk = {"id": "ALK_fusion", "rule": "fusion_gene == 'ALK'",
           "derivation_source": "directly_tagged_source_provided",
           "data_source": {"min_caller_count": 1}}
    out = _evaluate_fusion_stratum(alk, fusion_df, coverage_df, tissue_filter)
    members = set(out[out["is_member"] == True]["sample_id"])
    assert members == {"TCGA-AA-0001-01", "TCGA-AA-0002-01"}
    # False = assayed lung samples without a qualifying ALK fusion (S3, S4).
    assert (out["is_member"] == False).sum() == 2
    # BRCA sample excluded entirely by the tissue filter.
    assert "TCGA-BB-9999-01" not in set(out["sample_id"])
    # No nulls: every lung sample is in coverage.
    assert out["is_member"].isna().sum() == 0
    # patient_id is the participant-level barcode.
    s1 = out[out["sample_id"] == "TCGA-AA-0001-01"].iloc[0]
    assert s1["patient_id"] == "TCGA-AA-0001"
    assert s1["derivation_value"] == "ALK"

    # ALK, min_caller_count=2: only S1 (3-caller) qualifies; S2 (1-caller) drops
    # to false.
    alk2 = {**alk, "data_source": {"min_caller_count": 2}}
    out2 = _evaluate_fusion_stratum(alk2, fusion_df, coverage_df, tissue_filter)
    assert set(out2[out2["is_member"] == True]["sample_id"]) == {"TCGA-AA-0001-01"}


def test_fusion_evaluator_null_without_coverage():
    """Without coverage, non-members degrade to null (can't prove assayed-negative)."""
    from methods.subgroup_assigner_directly_tagged.cli import _evaluate_fusion_stratum
    fusion_df = _synthetic_consensus_df()
    alk = {"id": "ALK_fusion", "rule": "fusion_gene == 'ALK'",
           "derivation_source": "directly_tagged_source_provided",
           "data_source": {"min_caller_count": 1}}
    out = _evaluate_fusion_stratum(alk, fusion_df, coverage_df=None,
                                   tissue_filter=["LUAD", "LUSC"])
    # Members still resolve; the ROS1-only sample (no ALK) becomes null, not false.
    assert set(out[out["is_member"] == True]["sample_id"]) == {"TCGA-AA-0001-01", "TCGA-AA-0002-01"}
    assert (out["is_member"] == False).sum() == 0
    ros1_only = out[out["sample_id"] == "TCGA-AA-0003-01"].iloc[0]
    assert ros1_only["is_member"] is None or pd.isna(ros1_only["is_member"])


def test_fusion_real_execution_synthetic(tmp_path):
    """End-to-end CLI run against a synthetic NSCLC catalog with a single ALK
    fusion stratum, backed by staged consensus + coverage parquet fixtures."""
    cache_root = tmp_path / ".cache"
    fusion_cache = cache_root / "framework-fusion-consensus" / "test-fusion-consensus-v1"
    fusion_cache.mkdir(parents=True, exist_ok=True)
    _synthetic_consensus_df().to_parquet(
        fusion_cache / "fusion_consensus_per_sample_gene.parquet", index=False)
    _synthetic_coverage_df().to_parquet(
        fusion_cache / "sample_coverage.parquet", index=False)

    # Minimal NSCLC catalog with one fusion stratum.
    catalog = {
        "id": "nsclc-fusion-test",
        "manifest_kind": "subgroup_catalog",
        "indication": "NSCLC",
        "version": "test",
        "schema_version": 1,
        "atomic_strata": [{
            "id": "ALK_fusion",
            "label": "ALK fusion",
            "rule": "fusion_gene == 'ALK'",
            "derivation_source": "directly_tagged_source_provided",
            "data_source": {
                "manifest_id": "test-fusion-consensus-v1",
                "field": "gene_symbol",
                "method": "fusion_partner_match",
                "min_caller_count": 1,
            },
            "applicable_data_sources": ["tcga", "depmap"],
        }],
    }
    catalog_path = tmp_path / "nsclc-fusion-test.yaml"
    catalog_path.write_text(yaml.safe_dump(catalog, sort_keys=False))

    out_dir = tmp_path / "fusion_out"
    result = subprocess.run(
        [
            "python", "-m", "methods.subgroup_assigner_directly_tagged.cli",
            "--subgroup-catalog", str(catalog_path),
            "--data-source", "tcga",
            "--release-pin", "test",
            "--catalog-repo", str(CATALOG_REPO),
            "--out", str(out_dir),
        ],
        cwd=METHODS_REPO, capture_output=True, text=True,
        env={**os.environ, "FRAMEWORK_CACHE_ROOT": str(cache_root)},
    )
    assert result.returncode == 0, f"CLI failed: {result.stderr}\nstdout:\n{result.stdout}"

    assignments = pd.read_parquet(out_dir / "assignments.parquet")
    alk = assignments[assignments["stratum_id"] == "ALK_fusion"]
    # 2 members (S1 3-caller, S2 1-caller), 2 assayed-negative (S3 ROS1, S4 none).
    assert (alk["is_member"] == True).sum() == 2
    assert (alk["is_member"] == False).sum() == 2
    # BRCA coverage row excluded by the NSCLC tissue filter.
    assert "TCGA-BB-9999-01" not in set(alk["sample_id"])

    manifest = yaml.safe_load((out_dir / "manifest.yaml").read_text())
    assert manifest["indication"] == "NSCLC"
    strata = {s["subgroup_id"]: s for s in manifest["strata_summary"]}
    assert strata["ALK_fusion"]["n_samples"] == 2


# ---------- Sample-label (TMB) path ----------------------------------------

def test_sample_label_evaluator_tri_value():
    """_evaluate_sample_label_stratum: member/false/null + tissue restriction."""
    from methods.subgroup_assigner_directly_tagged.cli import _evaluate_sample_label_stratum

    label_df = pd.DataFrame({
        "patient_key": ["TCGA-AA-0001", "TCGA-AA-0002", "TCGA-AA-0003", "TCGA-BB-9999"],
        "tmb_bucket":  ["high",         "low",          "high",         "high"],
    })
    stratum = {"id": "TMB_high", "rule": "tmb_bucket == 'high'",
               "derivation_source": "directly_tagged_source_provided",
               "data_source": {"method": "sample_label_match"}}
    # No tissue filter: 3 high members, 1 low false.
    out = _evaluate_sample_label_stratum(stratum, label_df, tissue_filter_keys=None)
    assert (out["is_member"] == True).sum() == 3
    assert (out["is_member"] == False).sum() == 1
    assert out[out["sample_id"] == "TCGA-AA-0001"].iloc[0]["derivation_value"] == "high"

    # Tissue filter to the AA cohort: BB-9999 drops out entirely (not null — absent).
    out2 = _evaluate_sample_label_stratum(
        stratum, label_df, tissue_filter_keys={"TCGA-AA-0001", "TCGA-AA-0002", "TCGA-AA-0003"})
    assert "TCGA-BB-9999" not in set(out2["sample_id"])
    assert (out2["is_member"] == True).sum() == 2  # AA-0001, AA-0003


def test_sample_label_null_on_missing_value():
    """A NaN label → null (assayed-but-unlabeled), not false."""
    from methods.subgroup_assigner_directly_tagged.cli import _evaluate_sample_label_stratum
    label_df = pd.DataFrame({
        "patient_key": ["TCGA-AA-0001", "TCGA-AA-0002"],
        "tmb_bucket":  ["high",         None],
    })
    stratum = {"id": "TMB_high", "rule": "tmb_bucket == 'high'",
               "derivation_source": "directly_tagged_source_provided",
               "data_source": {"method": "sample_label_match"}}
    out = _evaluate_sample_label_stratum(stratum, label_df, tissue_filter_keys=None)
    n2 = out[out["sample_id"] == "TCGA-AA-0002"].iloc[0]
    assert n2["is_member"] is None or pd.isna(n2["is_member"])
