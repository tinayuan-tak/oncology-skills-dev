"""Tests for subgroup_common.iteration.subgroup_iterable decorator (Phase 3)."""

from pathlib import Path

import pandas as pd
import pytest

from methods.subgroup_common import iteration, loaders


@pytest.fixture(autouse=True)
def clear_caches():
    loaders.clear_all_caches()
    yield
    loaders.clear_all_caches()


def _seed_assignments(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr(loaders, "CACHE_ASSIGNMENTS", tmp_path / "cache" / "assignments")
    fake_catalog = tmp_path / "data-catalog"
    manifest_dir = fake_catalog / "manifests" / "derived"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "tcga-subgroup-assignments-coadread-v1.yaml").write_text(
        "manifest_kind: subgroup_assignment\nschema_version: 1\n"
        "id: tcga-subgroup-assignments-coadread-v1\nindication: COADREAD\n"
    )
    parquet_dir = tmp_path / "cache" / "assignments" / "tcga-subgroup-assignments-coadread-v1"
    parquet_dir.mkdir(parents=True)
    df = pd.DataFrame(
        {
            "sample_id": ["S1", "S2", "S3", "S4", "S1", "S2", "S3", "S4"],
            "stratum_id": ["MSI_H"] * 4 + ["MSS"] * 4,
            "is_member": [True, True, False, False, False, False, True, True],
        }
    )
    df.to_parquet(parquet_dir / "assignments.parquet", index=False)
    return fake_catalog


def test_backward_compat_no_subgroups(tmp_path, monkeypatch):
    """When subgroups=None, decorator returns scalar (existing behavior)."""

    @iteration.subgroup_iterable
    def my_method(target: str, _sample_id_filter=None) -> dict:
        return {"target": target, "n_samples": 4}

    result = my_method(target="KRAS")
    assert isinstance(result, dict)
    assert result["target"] == "KRAS"
    # No _sample_id_filter was passed (backward-compat path)


def test_subgroup_fanout_returns_dict(tmp_path, monkeypatch):
    """When subgroups=[MSI_H, MSS], returns {subgroup: result}."""
    fake_catalog = _seed_assignments(tmp_path, monkeypatch)
    call_log = []

    @iteration.subgroup_iterable
    def my_method(target: str, _sample_id_filter=None) -> dict:
        call_log.append(_sample_id_filter)
        return {"target": target, "n_samples": len(_sample_id_filter) if _sample_id_filter else 0}

    result = my_method(
        target="KRAS",
        subgroups=["MSI_H", "MSS"],
        subgroup_assignments_manifest="tcga-subgroup-assignments-coadread-v1",
        subgroup_catalog_repo=fake_catalog,
    )
    assert set(result.keys()) == {"MSI_H", "MSS"}
    assert result["MSI_H"]["n_samples"] == 2  # S1 + S2
    assert result["MSS"]["n_samples"] == 2  # S3 + S4
    # Two calls to my_method, each with different filter sets
    assert len(call_log) == 2
    assert call_log[0] == {"S1", "S2"}
    assert call_log[1] == {"S3", "S4"}


def test_error_when_subgroups_without_manifest(tmp_path):
    """`subgroups=[...]` without `subgroup_assignments_manifest` raises ValueError."""

    @iteration.subgroup_iterable
    def my_method(target: str, _sample_id_filter=None):
        return None

    with pytest.raises(ValueError, match="subgroup_assignments_manifest"):
        my_method(target="KRAS", subgroups=["MSI_H"])


def test_empty_subgroups_list_is_backward_compat(tmp_path):
    """`subgroups=[]` (empty list) treated as no fan-out (backward-compat)."""

    @iteration.subgroup_iterable
    def my_method(target: str, _sample_id_filter=None) -> dict:
        return {"target": target}

    result = my_method(target="KRAS", subgroups=[])
    assert isinstance(result, dict)
    assert result["target"] == "KRAS"


def test_introspection_marker():
    """Decorated function carries the _subgroup_iterable marker."""

    @iteration.subgroup_iterable
    def foo(x):
        return x

    assert getattr(foo, "_subgroup_iterable", False) is True


def test_functools_wraps_preserves_name():
    """@functools.wraps preserves __name__ and __doc__."""

    @iteration.subgroup_iterable
    def descriptive_method_name(x):
        """Docstring."""
        return x

    assert descriptive_method_name.__name__ == "descriptive_method_name"
    assert descriptive_method_name.__doc__ == "Docstring."


# ── Fan-out join-coverage guard (subtyping review Tier-1b) ────────────────────────────────────


def test_coverage_guard_warns_on_id_convention_mismatch(tmp_path, monkeypatch):
    """A reader that reports a NEAR-ZERO matched subgroup_n against a non-empty resolved member set
    (the sample-id-convention-mismatch signature) triggers a UserWarning — the gap the two
    @subgroup_iterable readers previously had (they bypassed compute_join_coverage)."""
    fake_catalog = _seed_assignments(tmp_path, monkeypatch)

    @iteration.subgroup_iterable
    def mismatched_reader(target: str, _sample_id_filter=None) -> dict:
        # Simulates a reader whose OWN data ids never match the resolved members (e.g. barcode vs
        # ModelID) → matched 0 of a 2-member stratum.
        return {"target": target, "subgroup_n": 0}

    with pytest.warns(UserWarning, match="sample-id-convention mismatch"):
        mismatched_reader(
            target="KRAS",
            subgroups=["MSI_H"],
            subgroup_assignments_manifest="tcga-subgroup-assignments-coadread-v1",
            subgroup_catalog_repo=fake_catalog,
        )


def test_coverage_guard_silent_on_healthy_match(tmp_path, monkeypatch, recwarn):
    """A reader that matches its full resolved member set emits NO coverage warning."""
    fake_catalog = _seed_assignments(tmp_path, monkeypatch)

    @iteration.subgroup_iterable
    def healthy_reader(target: str, _sample_id_filter=None) -> dict:
        return {"target": target, "subgroup_n": len(_sample_id_filter or [])}

    healthy_reader(
        target="KRAS",
        subgroups=["MSI_H"],
        subgroup_assignments_manifest="tcga-subgroup-assignments-coadread-v1",
        subgroup_catalog_repo=fake_catalog,
    )
    assert not [w for w in recwarn if "sample-id-convention" in str(w.message)]


def test_coverage_guard_no_false_alarm_without_subgroup_n(tmp_path, monkeypatch, recwarn):
    """A reader that does NOT report subgroup_n is skipped by the guard (no false positive)."""
    fake_catalog = _seed_assignments(tmp_path, monkeypatch)

    @iteration.subgroup_iterable
    def no_count_reader(target: str, _sample_id_filter=None) -> dict:
        return {"target": target, "some_other_field": 1}

    no_count_reader(
        target="KRAS",
        subgroups=["MSI_H"],
        subgroup_assignments_manifest="tcga-subgroup-assignments-coadread-v1",
        subgroup_catalog_repo=fake_catalog,
    )
    assert not [w for w in recwarn if "sample-id-convention" in str(w.message)]
