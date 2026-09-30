"""Tests for subgroup_common.iteration.subgroup_iterable decorator (Phase 3)."""

from pathlib import Path

import pandas as pd
import pytest

from onc_methods.subgroup_common import iteration, loaders


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


# ── Stratum-evaluability opt-in (absent-vs-unevaluable plumbing) ───────────────────────────────


def _seed_assignments_with_abstentions(tmp_path, monkeypatch) -> Path:
    """Shard with THREE strata, the third of which is the point.

    MSI_H / MSS each have classified members. `CIMP_High` has rows but its `is_member` column is
    ALL NULL — the assigner reached no verdict for anybody. That is the ONLY shape that makes
    `evaluated is False` reachable, and it is the shape of the live DepMap STAD/PAAD shards, where
    the axis exists in the catalog but nothing was ever assigned. Without such a stratum every
    evaluability assertion below would pass vacuously on a shard that cannot express abstention.
    """
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
            "sample_id": ["S1", "S2", "S3", "S4"] * 3,
            "stratum_id": ["MSI_H"] * 4 + ["MSS"] * 4 + ["CIMP_High"] * 4,
            "is_member": [True, True, False, False] + [False, False, True, True] + [None] * 4,
        }
    )
    df.to_parquet(parquet_dir / "assignments.parquet", index=False)
    return fake_catalog


def test_evaluability_flag_injected_only_when_reader_declares_it(tmp_path, monkeypatch):
    """The flag is OPT-IN by signature probe.

    A reader that declares `_stratum_evaluated` receives it; one that does not is called exactly as
    before and must NOT raise TypeError. This is the whole reason the injection is probed rather
    than unconditional: four other @subgroup_iterable readers feed cards that still declare the
    narrow {measured, underpowered, absent} enum, and an unconditional inject would break them.
    """
    fake_catalog = _seed_assignments_with_abstentions(tmp_path, monkeypatch)
    seen: dict = {}

    @iteration.subgroup_iterable
    def opted_in(target: str, _sample_id_filter=None, _stratum_evaluated=None) -> dict:
        seen["flag"] = _stratum_evaluated
        return {"target": target, "subgroup_n": len(_sample_id_filter or [])}

    @iteration.subgroup_iterable
    def not_opted_in(target: str, _sample_id_filter=None, **kwargs) -> dict:
        seen["kwargs"] = dict(kwargs)
        return {"target": target, "subgroup_n": len(_sample_id_filter or [])}

    common = {
        "subgroups": ["MSI_H"],
        "subgroup_assignments_manifest": "tcga-subgroup-assignments-coadread-v1",
        "subgroup_catalog_repo": fake_catalog,
    }
    opted_in(target="KRAS", **common)
    assert seen["flag"] is True  # MSI_H has classified rows

    # A reader with **kwargs but no explicit declaration is NOT opted in — the probe looks for the
    # named parameter, so a catch-all cannot silently start receiving (and ignoring) the flag.
    not_opted_in(target="KRAS", **common)
    assert seen["kwargs"] == {}


def test_evaluability_flag_separates_empty_from_unclassified(tmp_path, monkeypatch):
    """`evaluated` is False ONLY for the all-null stratum — the absent-vs-unevaluable discriminator.

    Both MSS (classified, but S1/S2 are non-members) and CIMP_High (nobody classified) resolve to a
    member set that EXCLUDES S1/S2, so `_sample_id_filter` alone cannot tell them apart. The flag
    can: that is the fact `evidence_state(0, False, evaluated=...)` needs to avoid laundering an
    abstention into the measured negative `absent`.
    """
    fake_catalog = _seed_assignments_with_abstentions(tmp_path, monkeypatch)
    flags: dict = {}

    @iteration.subgroup_iterable
    def probe(target: str, _sample_id_filter=None, _stratum_evaluated=None) -> dict:
        flags[len(flags)] = _stratum_evaluated
        return {"target": target, "subgroup_n": len(_sample_id_filter or [])}

    out = probe(
        target="KRAS",
        subgroups=["MSI_H", "MSS", "CIMP_High"],
        subgroup_assignments_manifest="tcga-subgroup-assignments-coadread-v1",
        subgroup_catalog_repo=fake_catalog,
    )
    assert [flags[i] for i in range(3)] == [True, True, False]
    # CIMP_High resolves to ZERO members, so the count alone is indistinguishable from a genuinely
    # empty-but-evaluated stratum — the control that proves the flag is carrying new information.
    assert out["CIMP_High"]["subgroup_n"] == 0
