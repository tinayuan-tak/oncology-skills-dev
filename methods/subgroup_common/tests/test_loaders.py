"""Tests for subgroup_common.loaders (Phase 2a.4).

test_cache_dir_layout: session-cache paths under CACHE_ROOT are constructed correctly.
test_marker_paper_session_cache_hit: session-cache placement takes precedence over legacy.
test_marker_paper_legacy_fallback: legacy cache path (Phase 2a.1) still works.
test_assignments_load_synthetic: load_assignments() reads a parquet via manifest.
test_lru_cache_amortization: repeat calls hit the cache — Path-B I/O check.
"""

from pathlib import Path

import pandas as pd
import pytest

from methods.subgroup_common import loaders


@pytest.fixture(autouse=True)
def clear_caches():
    """Reset lru_caches between tests."""
    loaders.clear_all_caches()
    yield
    loaders.clear_all_caches()


def test_cache_dir_layout():
    """Session-cache paths under CACHE_ROOT are constructed correctly."""
    assert loaders.CACHE_ROOT == Path.home() / ".cache" / "framework-subgroup-pipeline"
    assert loaders.CACHE_TCGA_MARKER == loaders.CACHE_ROOT / "tcga-marker-paper"
    assert loaders.CACHE_DEPMAP == loaders.CACHE_ROOT / "depmap-26q1"
    assert loaders.CACHE_ASSIGNMENTS == loaders.CACHE_ROOT / "subgroup-assignments"


def test_marker_paper_session_cache_hit(tmp_path, monkeypatch):
    """Session-cache placement is preferred; legacy is only fallback."""
    # Redirect cache paths to tmp for isolation
    monkeypatch.setattr(loaders, "CACHE_TCGA_MARKER", tmp_path / "session" / "tcga-marker-paper")
    monkeypatch.setattr(loaders, "LEGACY_TCGA_MARKER", tmp_path / "legacy" / "framework-tcga-marker-paper")

    # Populate session cache
    session_path = tmp_path / "session" / "tcga-marker-paper" / "coadread" / "subtypes.csv"
    session_path.parent.mkdir(parents=True)
    session_df = pd.DataFrame({
        "sample_id": ["TCGA-A"],
        "patient_id": ["TCGA-A"],
        "source_native_id": ["TCGA-A-01"],
        "MSI_status": ["MSI-H"],
    })
    session_df.to_csv(session_path, index=False)

    loaders.load_tcga_marker_paper_subtypes.cache_clear()
    df = loaders.load_tcga_marker_paper_subtypes("COADREAD")
    assert len(df) == 1
    assert df["MSI_status"].iloc[0] == "MSI-H"


def test_marker_paper_legacy_fallback(tmp_path, monkeypatch):
    """When session cache misses, legacy cache from Phase 2a.1 protocol takes over."""
    monkeypatch.setattr(loaders, "CACHE_TCGA_MARKER", tmp_path / "session" / "tcga-marker-paper")
    monkeypatch.setattr(loaders, "LEGACY_TCGA_MARKER", tmp_path / "legacy" / "framework-tcga-marker-paper")

    legacy_path = tmp_path / "legacy" / "framework-tcga-marker-paper" / "coadread" / "subtypes.csv"
    legacy_path.parent.mkdir(parents=True)
    pd.DataFrame({"sample_id": ["X"], "MSI_status": ["MSS"]}).to_csv(legacy_path, index=False)

    loaders.load_tcga_marker_paper_subtypes.cache_clear()
    df = loaders.load_tcga_marker_paper_subtypes("COADREAD")
    assert df["MSI_status"].iloc[0] == "MSS"


def test_marker_paper_not_found_raises(tmp_path, monkeypatch):
    """When neither cache has the file, raise a clear error naming both paths."""
    monkeypatch.setattr(loaders, "CACHE_TCGA_MARKER", tmp_path / "session")
    monkeypatch.setattr(loaders, "LEGACY_TCGA_MARKER", tmp_path / "legacy")
    loaders.load_tcga_marker_paper_subtypes.cache_clear()
    with pytest.raises(FileNotFoundError, match="not in either cache path"):
        loaders.load_tcga_marker_paper_subtypes("NSCLC")


def test_assignments_load_synthetic(tmp_path, monkeypatch):
    """load_assignments() reads a synthetic assignments.parquet via manifest yaml."""
    monkeypatch.setattr(loaders, "CACHE_ASSIGNMENTS", tmp_path / "cache" / "assignments")

    # Fake data-catalog repo with a derived manifest yaml
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

    # Session-cache the assignments parquet
    parquet_dir = tmp_path / "cache" / "assignments" / "tcga-subgroup-assignments-coadread-v1"
    parquet_dir.mkdir(parents=True)
    df = pd.DataFrame({
        "sample_id": ["S1", "S2", "S1", "S2"],
        "stratum_id": ["MSI_H", "MSI_H", "MSS", "MSS"],
        "is_member": [True, False, False, True],
    })
    df.to_parquet(parquet_dir / "assignments.parquet", index=False)

    loaders.load_assignments.cache_clear()
    got = loaders.load_assignments("tcga-subgroup-assignments-coadread-v1", data_catalog_repo=fake_catalog)
    assert len(got) == 4
    assert set(got["stratum_id"]) == {"MSI_H", "MSS"}


def test_lru_cache_amortization(tmp_path, monkeypatch):
    """Path-B I/O check — repeat calls to load_assignments hit the lru_cache."""
    monkeypatch.setattr(loaders, "CACHE_ASSIGNMENTS", tmp_path / "cache" / "assignments")

    fake_catalog = tmp_path / "data-catalog"
    (fake_catalog / "manifests" / "derived").mkdir(parents=True)
    (fake_catalog / "manifests" / "derived" / "test-manifest.yaml").write_text(
        "manifest_kind: subgroup_assignment\nschema_version: 1\nid: test-manifest\n"
    )

    parquet_dir = tmp_path / "cache" / "assignments" / "test-manifest"
    parquet_dir.mkdir(parents=True)
    pd.DataFrame({"sample_id": ["X"], "stratum_id": ["Y"], "is_member": [True]}).to_parquet(
        parquet_dir / "assignments.parquet", index=False
    )

    loaders.load_assignments.cache_clear()
    r1 = loaders.load_assignments("test-manifest", data_catalog_repo=fake_catalog)
    r2 = loaders.load_assignments("test-manifest", data_catalog_repo=fake_catalog)

    # Both call return the same DataFrame from lru_cache
    assert r1 is r2  # same object identity → cache hit
    info = loaders.load_assignments.cache_info()
    assert info.hits >= 1  # second call was a cache hit
