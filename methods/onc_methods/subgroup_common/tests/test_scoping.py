"""Tests for subgroup_common.scoping (Phase 3.1) — sample-filtering primitives."""

from pathlib import Path

import pandas as pd
import pytest

from onc_methods.subgroup_common import loaders, scoping


@pytest.fixture(autouse=True)
def clear_caches():
    loaders.clear_all_caches()
    yield
    loaders.clear_all_caches()


def _seed_assignments(tmp_path, monkeypatch, df: pd.DataFrame | None = None) -> Path:
    """Fabricate a data-catalog repo + assignments parquet in tmp cache.

    `df` overrides the default 2-stratum frame for tests that need a different
    is_member composition (e.g. an all-null stratum). The default is unchanged, so
    passing nothing reproduces the historical fixture exactly.
    """
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
    if df is None:
        df = pd.DataFrame(
            {
                "sample_id": ["S1", "S2", "S3", "S4", "S1", "S2", "S3", "S4"],
                "stratum_id": ["MSI_H"] * 4 + ["MSS"] * 4,
                "is_member": [True, True, False, None, False, False, True, True],
            }
        )
    df.to_parquet(parquet_dir / "assignments.parquet", index=False)
    return fake_catalog


def test_filter_samples_by_subgroup_msi_h(tmp_path, monkeypatch):
    """filter_samples_by_subgroup returns only True members (excludes False + null)."""
    fake_catalog = _seed_assignments(tmp_path, monkeypatch)
    source_df = pd.DataFrame(
        {
            "Tumor_Sample_Barcode": ["S1", "S2", "S3", "S4", "S5"],  # S5 not in assignments
            "gene_expression": [1.0, 2.0, 3.0, 4.0, 5.0],
        }
    )
    result = scoping.filter_samples_by_subgroup(
        source_df,
        sample_id_col="Tumor_Sample_Barcode",
        subgroup_id="MSI_H",
        assignments_manifest_id="tcga-subgroup-assignments-coadread-v1",
        data_catalog_repo=fake_catalog,
    )
    # Only S1 + S2 have is_member=True for MSI_H
    assert set(result["Tumor_Sample_Barcode"]) == {"S1", "S2"}


def test_filter_samples_by_subgroup_mss(tmp_path, monkeypatch):
    """MSS stratum: S3 + S4 are True; S1 + S2 are False; S5 not in assignments."""
    fake_catalog = _seed_assignments(tmp_path, monkeypatch)
    source_df = pd.DataFrame(
        {
            "Tumor_Sample_Barcode": ["S1", "S2", "S3", "S4", "S5"],
            "value": range(5),
        }
    )
    result = scoping.filter_samples_by_subgroup(
        source_df,
        sample_id_col="Tumor_Sample_Barcode",
        subgroup_id="MSS",
        assignments_manifest_id="tcga-subgroup-assignments-coadread-v1",
        data_catalog_repo=fake_catalog,
    )
    assert set(result["Tumor_Sample_Barcode"]) == {"S3", "S4"}


def test_null_and_missing_samples_excluded(tmp_path, monkeypatch):
    """S4 has is_member=null for MSI_H (insufficient); S5 not in assignments; both excluded."""
    fake_catalog = _seed_assignments(tmp_path, monkeypatch)
    source_df = pd.DataFrame(
        {
            "Tumor_Sample_Barcode": ["S4", "S5"],
            "value": [1.0, 2.0],
        }
    )
    result = scoping.filter_samples_by_subgroup(
        source_df,
        sample_id_col="Tumor_Sample_Barcode",
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
        "tcga-subgroup-assignments-coadread-v1",
        "MSI_H",
        data_catalog_repo=fake_catalog,
    )
    assert cohort == {"S1", "S2"}


def test_cohort_size(tmp_path, monkeypatch):
    """cohort_size returns integer for subgroup-n-floor discipline."""
    fake_catalog = _seed_assignments(tmp_path, monkeypatch)
    assert (
        scoping.cohort_size(
            "tcga-subgroup-assignments-coadread-v1",
            "MSI_H",
            data_catalog_repo=fake_catalog,
        )
        == 2
    )
    assert (
        scoping.cohort_size(
            "tcga-subgroup-assignments-coadread-v1",
            "MSS",
            data_catalog_repo=fake_catalog,
        )
        == 2
    )


def test_join_coverage_healthy(tmp_path, monkeypatch):
    """compute_join_coverage reports matched/assignment-only + no warning on a good join."""
    import warnings

    fake_catalog = _seed_assignments(tmp_path, monkeypatch)
    source_df = pd.DataFrame({"Tumor_Sample_Barcode": ["S1", "S2", "S3", "S4"]})
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        cov = scoping.compute_join_coverage(
            source_df,
            "Tumor_Sample_Barcode",
            "MSI_H",
            "tcga-subgroup-assignments-coadread-v1",
            data_catalog_repo=fake_catalog,
        )
    # MSI_H members = {S1, S2}; both present in source → 100% match, no warning
    assert cov.n_members == 2
    assert cov.n_matched == 2
    assert cov.match_rate == 1.0
    assert cov.id_convention_warning is False
    assert len(w) == 0


def test_join_coverage_detects_id_mismatch(tmp_path, monkeypatch):
    """The load-bearing guard (Finding 5): a full-aliquot key against patient-level
    assignments matches 0 members → id_convention_warning True + UserWarning raised."""
    import warnings

    fake_catalog = _seed_assignments(tmp_path, monkeypatch)
    # Method data keyed on a mismatched convention (nothing overlaps S1..S4)
    source_df = pd.DataFrame(
        {
            "aliquot": ["S1-01A-01D", "S2-01A-01D", "S3-01A-01D", "S4-01A-01D"],
        }
    )
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        cov = scoping.compute_join_coverage(
            source_df, "aliquot", "MSI_H", "tcga-subgroup-assignments-coadread-v1", data_catalog_repo=fake_catalog
        )
    assert cov.n_members == 2
    assert cov.n_matched == 0
    assert cov.match_rate == 0.0
    assert cov.id_convention_warning is True
    assert len(w) == 1 and "id-convention mismatch" in str(w[0].message)


def test_join_coverage_suppress_warning(tmp_path, monkeypatch):
    """warn=False computes the diagnostic without raising (for batch/coverage-matrix use)."""
    import warnings

    fake_catalog = _seed_assignments(tmp_path, monkeypatch)
    source_df = pd.DataFrame({"aliquot": ["X", "Y"]})
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        cov = scoping.compute_join_coverage(
            source_df,
            "aliquot",
            "MSI_H",
            "tcga-subgroup-assignments-coadread-v1",
            data_catalog_repo=fake_catalog,
            warn=False,
        )
    assert cov.id_convention_warning is True  # still flagged in the struct
    assert len(w) == 0  # but no warning emitted


# ---- stratum_evaluability: the denominator `is_member == True` discards -----------
#
# The defect these guard (measured 2026-09-18): the DepMap paad + stad assignment shards
# are 100% is_member=None — no cell line was ever classified — yet every consumer saw
# `subgroup_n == 0` and reported the axis as `empty`, i.e. a MEASURED ABSENCE. The
# assigner emits the honest tri-value; the reporting layer was flattening it.


def _all_null_frame() -> pd.DataFrame:
    """3 strata: one normal, one ALL-NULL (the paad/stad shape), one absent-but-evaluated."""
    return pd.DataFrame(
        {
            "sample_id": ["S1", "S2", "S3"] * 3,
            "stratum_id": ["MSI_H"] * 3 + ["NEVER_CLASSIFIED"] * 3 + ["EVALUATED_EMPTY"] * 3,
            "is_member": [True, False, None, None, None, None, False, False, False],
        }
    )


def test_stratum_evaluability_partitions_tri_value(tmp_path, monkeypatch):
    """The three is_member values are counted SEPARATELY and the partition closes."""
    fake_catalog = _seed_assignments(tmp_path, monkeypatch, _all_null_frame())
    ev = scoping.stratum_evaluability("tcga-subgroup-assignments-coadread-v1", "MSI_H", data_catalog_repo=fake_catalog)
    assert (ev.n_member, ev.n_non_member, ev.n_abstained, ev.n_unrecognized) == (1, 1, 1, 0)
    assert ev.n_rows == 3
    assert ev.n_member + ev.n_non_member + ev.n_abstained + ev.n_unrecognized == ev.n_rows
    assert ev.n_evaluated == 2
    assert ev.evaluated is True
    assert ev.abstention_rate == pytest.approx(1 / 3)


def test_stratum_evaluability_distinguishes_unevaluable_from_empty(tmp_path, monkeypatch):
    """THE POINT. Two strata, both with 0 members, MUST NOT report the same evaluability.

    Anti-vacuity: the two arms are asserted to DIFFER, so a regression that re-flattens
    the tri-value fails here rather than passing with both arms equal.
    """
    fake_catalog = _seed_assignments(tmp_path, monkeypatch, _all_null_frame())
    never = scoping.stratum_evaluability(
        "tcga-subgroup-assignments-coadread-v1", "NEVER_CLASSIFIED", data_catalog_repo=fake_catalog
    )
    empty = scoping.stratum_evaluability(
        "tcga-subgroup-assignments-coadread-v1", "EVALUATED_EMPTY", data_catalog_repo=fake_catalog
    )
    # Indistinguishable through the member set alone — this is the erasure being fixed.
    assert never.n_member == empty.n_member == 0
    assert scoping.cohort_size(
        "tcga-subgroup-assignments-coadread-v1", "NEVER_CLASSIFIED", fake_catalog
    ) == scoping.cohort_size("tcga-subgroup-assignments-coadread-v1", "EVALUATED_EMPTY", fake_catalog)
    # …but separable through the evaluability denominator.
    assert never.evaluated is False and never.n_abstained == 3
    assert empty.evaluated is True and empty.n_non_member == 3
    assert never.evaluated != empty.evaluated


def test_stratum_evaluability_absent_stratum_id_is_unevaluable(tmp_path, monkeypatch):
    """A stratum id absent from the shard has nothing to assert an absence ABOUT."""
    fake_catalog = _seed_assignments(tmp_path, monkeypatch, _all_null_frame())
    ev = scoping.stratum_evaluability(
        "tcga-subgroup-assignments-coadread-v1", "NOT_IN_SHARD", data_catalog_repo=fake_catalog
    )
    assert ev.n_rows == 0 and ev.evaluated is False
    assert ev.abstention_rate is None


def test_stratum_evaluability_flags_unrecognized_is_member_values(tmp_path, monkeypatch):
    """A mis-typed column (string "false") must not silently vanish from the denominator.

    The object-dtype residual case: `"false"` satisfies neither `is False` nor `isna()`,
    so a three-way split would drop it and OVER-report evaluation. It is counted on the
    not-evaluated side (an uninterpretable value is not evidence of evaluation) and warns.
    """
    import warnings

    df = pd.DataFrame(
        {
            "sample_id": ["S1", "S2", "S3"],
            "stratum_id": ["MISTYPED"] * 3,
            "is_member": ["false", "false", "true"],
        }
    )
    fake_catalog = _seed_assignments(tmp_path, monkeypatch, df)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        ev = scoping.stratum_evaluability(
            "tcga-subgroup-assignments-coadread-v1", "MISTYPED", data_catalog_repo=fake_catalog
        )
    assert ev.n_unrecognized == 3
    assert ev.n_member == ev.n_non_member == ev.n_abstained == 0
    assert ev.n_member + ev.n_non_member + ev.n_abstained + ev.n_unrecognized == ev.n_rows == 3
    assert ev.evaluated is False  # abstains rather than claiming an absence
    assert len(w) == 1 and "neither a boolean nor null" in str(w[0].message)


def test_stratum_evaluability_warn_false_is_silent(tmp_path, monkeypatch):
    """warn=False computes the diagnostic without raising (batch/coverage-matrix use)."""
    import warnings

    df = pd.DataFrame({"sample_id": ["S1"], "stratum_id": ["MISTYPED"], "is_member": ["false"]})
    fake_catalog = _seed_assignments(tmp_path, monkeypatch, df)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        ev = scoping.stratum_evaluability(
            "tcga-subgroup-assignments-coadread-v1", "MISTYPED", data_catalog_repo=fake_catalog, warn=False
        )
    assert ev.n_unrecognized == 1  # still flagged in the struct
    assert len(w) == 0


def test_stratum_evaluability_member_count_agrees_with_cohort(tmp_path, monkeypatch):
    """CONSISTENCY: n_member must equal the member set the filters actually use.

    Guards against the two paths drifting — if they disagree, an `evaluated` flag could
    contradict the `subgroup_n` it is paired with in evidence_state().
    """
    fake_catalog = _seed_assignments(tmp_path, monkeypatch)
    for stratum in ("MSI_H", "MSS"):
        ev = scoping.stratum_evaluability(
            "tcga-subgroup-assignments-coadread-v1", stratum, data_catalog_repo=fake_catalog
        )
        cohort = scoping.resolve_subgroup_cohort(
            "tcga-subgroup-assignments-coadread-v1", stratum, data_catalog_repo=fake_catalog
        )
        assert ev.n_member == len(cohort), stratum


def test_path_b_amortization_across_multiple_subgroups(tmp_path, monkeypatch):
    """PATH-B I/O PROOF at the scoping layer: two calls with different subgroups
    of the same manifest hit the load_assignments lru_cache."""
    fake_catalog = _seed_assignments(tmp_path, monkeypatch)
    source_df = pd.DataFrame({"Tumor_Sample_Barcode": ["S1", "S2", "S3", "S4"]})

    # First call: load_assignments cache miss
    _ = scoping.filter_samples_by_subgroup(
        source_df,
        "Tumor_Sample_Barcode",
        "MSI_H",
        "tcga-subgroup-assignments-coadread-v1",
        data_catalog_repo=fake_catalog,
    )
    info_after_first = loaders.load_assignments.cache_info()

    # Second call: MSS stratum, same manifest → SHOULD hit cache
    _ = scoping.filter_samples_by_subgroup(
        source_df,
        "Tumor_Sample_Barcode",
        "MSS",
        "tcga-subgroup-assignments-coadread-v1",
        data_catalog_repo=fake_catalog,
    )
    info_after_second = loaders.load_assignments.cache_info()

    # Cache hits increased on second call (Path-B amortization proof)
    assert info_after_second.hits > info_after_first.hits
