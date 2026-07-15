"""Tests for subgroup_common.scoping (Phase 3.1) — sample-filtering primitives."""

from pathlib import Path

import pandas as pd
import pytest

from methods.subgroup_common import loaders, scoping


@pytest.fixture(autouse=True)
def clear_caches():
    loaders.clear_all_caches()
    yield
    loaders.clear_all_caches()


def _seed_assignments(tmp_path, monkeypatch) -> Path:
    """Fabricate a data-catalog repo + assignments parquet in tmp cache."""
    monkeypatch.setattr(loaders, "CACHE_ASSIGNMENTS", tmp_path / "cache" / "assignments")

    fake_catalog = tmp_path / "data-catalog"
    manifest_dir = fake_catalog / "manifests" / "derived"
    manifest_dir.mkdir(parents=True)
    manifest_path = manifest_dir / "tcga-subgroup-assignments-coadread-v1.yaml"
    manifest_path.write_text(
        "manifest_kind: subgroup_assignment\n"
        "schema_version: 1\n"
        "id: tcga-subgroup-assignments-coadread-v1\n"
        "indication: COADREAD\n"
    )

    # 4 samples across 2 strata; note null (insufficient) case
    parquet_dir = tmp_path / "cache" / "assignments" / "tcga-subgroup-assignments-coadread-v1"
    parquet_dir.mkdir(parents=True)
    df = pd.DataFrame({
        "sample_id":   ["S1", "S2", "S3", "S4", "S1", "S2", "S3", "S4"],
        "stratum_id":  ["MSI_H"] * 4 + ["MSS"] * 4,
        "is_member":   [True, True, False, None,  False, False, True, True],
    })
    df.to_parquet(parquet_dir / "assignments.parquet", index=False)
    return fake_catalog


def test_filter_samples_by_subgroup_msi_h(tmp_path, monkeypatch):
    """filter_samples_by_subgroup returns only True members (excludes False + null)."""
    fake_catalog = _seed_assignments(tmp_path, monkeypatch)
    source_df = pd.DataFrame({
        "Tumor_Sample_Barcode": ["S1", "S2", "S3", "S4", "S5"],  # S5 not in assignments
        "gene_expression": [1.0, 2.0, 3.0, 4.0, 5.0],
    })
    result = scoping.filter_samples_by_subgroup(
        source_df, sample_id_col="Tumor_Sample_Barcode",
        subgroup_id="MSI_H",
        assignments_manifest_id="tcga-subgroup-assignments-coadread-v1",
        data_catalog_repo=fake_catalog,
    )
    # Only S1 + S2 have is_member=True for MSI_H
    assert set(result["Tumor_Sample_Barcode"]) == {"S1", "S2"}


def test_filter_samples_by_subgroup_mss(tmp_path, monkeypatch):
    """MSS stratum: S3 + S4 are True; S1 + S2 are False; S5 not in assignments."""
    fake_catalog = _seed_assignments(tmp_path, monkeypatch)
    source_df = pd.DataFrame({
        "Tumor_Sample_Barcode": ["S1", "S2", "S3", "S4", "S5"],
        "value": range(5),
    })
    result = scoping.filter_samples_by_subgroup(
        source_df, sample_id_col="Tumor_Sample_Barcode",
        subgroup_id="MSS",
        assignments_manifest_id="tcga-subgroup-assignments-coadread-v1",
        data_catalog_repo=fake_catalog,
    )
    assert set(result["Tumor_Sample_Barcode"]) == {"S3", "S4"}


def test_null_and_missing_samples_excluded(tmp_path, monkeypatch):
    """S4 has is_member=null for MSI_H (insufficient); S5 not in assignments; both excluded."""
    fake_catalog = _seed_assignments(tmp_path, monkeypatch)
    source_df = pd.DataFrame({
        "Tumor_Sample_Barcode": ["S4", "S5"],
        "value": [1.0, 2.0],
    })
    result = scoping.filter_samples_by_subgroup(
        source_df, sample_id_col="Tumor_Sample_Barcode",
        subgroup_id="MSI_H",
        assignments_manifest_id="tcga-subgroup-assignments-coadread-v1",
        data_catalog_repo=fake_catalog,
    )
    # S4 has null → excluded; S5 not in assignments → excluded
    assert len(result) == 0


def test_resolve_subgroup_cohort(tmp_path, monkeypatch):
    """resolve_subgroup_cohort returns set of member sample_ids."""
    fake_catalog = _seed_assignments(tmp_path, monkeypatch)
    cohort = scoping.resolve_subgroup_cohort(
        "tcga-subgroup-assignments-coadread-v1", "MSI_H",
        data_catalog_repo=fake_catalog,
    )
    assert cohort == {"S1", "S2"}


def test_cohort_size(tmp_path, monkeypatch):
    """cohort_size returns integer for subgroup-n-floor discipline."""
    fake_catalog = _seed_assignments(tmp_path, monkeypatch)
    assert scoping.cohort_size(
        "tcga-subgroup-assignments-coadread-v1", "MSI_H",
        data_catalog_repo=fake_catalog,
    ) == 2
    assert scoping.cohort_size(
        "tcga-subgroup-assignments-coadread-v1", "MSS",
        data_catalog_repo=fake_catalog,
    ) == 2


def test_path_b_amortization_across_multiple_subgroups(tmp_path, monkeypatch):
    """PATH-B I/O PROOF at the scoping layer: two calls with different subgroups
    of the same manifest hit the load_assignments lru_cache."""
    fake_catalog = _seed_assignments(tmp_path, monkeypatch)
    source_df = pd.DataFrame({"Tumor_Sample_Barcode": ["S1", "S2", "S3", "S4"]})

    # First call: load_assignments cache miss
    _ = scoping.filter_samples_by_subgroup(
        source_df, "Tumor_Sample_Barcode", "MSI_H",
        "tcga-subgroup-assignments-coadread-v1", data_catalog_repo=fake_catalog,
    )
    info_after_first = loaders.load_assignments.cache_info()

    # Second call: MSS stratum, same manifest → SHOULD hit cache
    _ = scoping.filter_samples_by_subgroup(
        source_df, "Tumor_Sample_Barcode", "MSS",
        "tcga-subgroup-assignments-coadread-v1", data_catalog_repo=fake_catalog,
    )
    info_after_second = loaders.load_assignments.cache_info()

    # Cache hits increased on second call (Path-B amortization proof)
    assert info_after_second.hits > info_after_first.hits
