"""Tests for subgroup_common.panorama — the substrate-agnostic composer.

Uses a trivial fake reader (no real data) to prove the generic mechanics:
fan-out collection, projection, cross-stratum reduction, and the shared
evidence_state / SUBGROUP_N_FLOOR primitives. Substrate-specific readers are
tested in their own method packages.
"""

from __future__ import annotations

from functools import partial

from methods.subgroup_common.panorama import (
    SUBGROUP_N_FLOOR,
    axis_quality,
    build_panorama,
    delta_reducer,
    disjoint_arms,
    evidence_state,
    partition_axes,
    stratum_axis,
)


def test_evidence_state_trichotomy():
    assert evidence_state(0, False) == "absent"
    assert evidence_state(10, False) == "underpowered"
    assert evidence_state(50, True) == "measured"
    # floor constant is the shared single source of truth
    assert SUBGROUP_N_FLOOR == 30


def test_axis_quality_grades():
    m = {"evidence_state": "measured"}
    u = {"evidence_state": "underpowered"}
    a = {"evidence_state": "absent"}
    # >=2 measured strata → an actionable, contrastable axis
    assert axis_quality([m, m, u]) == "powered"
    assert axis_quality([m, m]) == "powered"
    # only ONE measured stratum can't support a cross-subtype contrast (NSCLC KRAS_G12C case)
    assert axis_quality([m, u, a]) == "underpowered"
    assert axis_quality([u, u]) == "underpowered"
    # axis defined but every stratum empty (DepMap STAD/PAAD case)
    assert axis_quality([a, a, a]) == "empty"
    # no records at all → no axis
    assert axis_quality([]) == "unavailable"
    # threshold is tunable
    assert axis_quality([m], min_powered_strata=1) == "powered"


def test_delta_reducer_ignores_absent_and_null():
    records = [
        {"metric": 0.5, "subgroup_n": 100, "evidence_state": "measured"},
        {"metric": 0.1, "subgroup_n": 40, "evidence_state": "measured"},
        {"metric": None, "subgroup_n": 0, "evidence_state": "absent"},
    ]
    out = delta_reducer(records, metric_key="metric", label="frequency")
    assert out["max_subgroup_frequency"] == 0.5
    assert out["min_subgroup_frequency"] == 0.1
    assert out["cross_subgroup_delta_frequency"] == 0.4
    assert out["n_subgroups_with_data"] == 2  # absent stratum has subgroup_n=0
    assert out["n_subgroups_measured"] == 2


def test_delta_reducer_excludes_underpowered_from_spread():
    """B11-S2-1: a tiny-n (underpowered) stratum with an extreme value must NOT drive
    the max/min/delta scalars (the cards deem underpowered strata inadmissible in
    comparative prose). It is still counted in n_subgroups_with_data, just excluded
    from the spread."""
    records = [
        {"metric": 0.50, "subgroup_n": 100, "evidence_state": "measured"},
        {"metric": 0.40, "subgroup_n": 40, "evidence_state": "measured"},
        # tiny-n outlier — 0.99 would blow up the delta if admitted
        {"metric": 0.99, "subgroup_n": 3, "evidence_state": "underpowered"},
    ]
    out = delta_reducer(records, metric_key="metric", label="frequency")
    assert out["max_subgroup_frequency"] == 0.50   # NOT the 0.99 underpowered outlier
    assert out["min_subgroup_frequency"] == 0.40
    assert out["cross_subgroup_delta_frequency"] == 0.1   # 0.50-0.40, not 0.99-0.40
    assert out["n_subgroups_measured"] == 2
    assert out["n_subgroups_with_data"] == 3  # underpowered stratum still has samples


def test_stratum_axis_and_partition():
    """B11-S1: the 5 orthogonal COADREAD axes are recovered from stratum_ids, and
    unrecognised strata fall back to their own singleton axis (never falsely pooled)."""
    assert stratum_axis("MSI_H") == "MSI"
    assert stratum_axis("MSS") == "MSI"
    assert stratum_axis("CMS2") == "CMS"
    assert stratum_axis("left_sided") == "sidedness"
    assert stratum_axis("CIMP_High") == "CIMP"
    assert stratum_axis("stage_II") == "stage"
    assert stratum_axis("KRAS_G12C") == "KRAS_G12C"  # unknown → singleton
    axes = partition_axes(["MSI_H", "MSS", "CMS1", "CMS2", "left_sided", "right_sided",
                           "CIMP_High", "stage_I", "stage_II", "stage_resectable"])
    assert axes["MSI"] == ["MSI_H", "MSS"]
    assert axes["CMS"] == ["CMS1", "CMS2"]
    assert axes["sidedness"] == ["left_sided", "right_sided"]
    assert axes["stage"] == ["stage_I", "stage_II", "stage_resectable"]


def test_disjoint_arms_drops_overlapping_composite():
    """The composite stage_resectable is a superset of stage_I ∪ stage_II; the
    disjointness guard drops it so the omnibus runs over disjoint arms only."""
    member_sets = {
        "stage_I": {1, 2, 3},
        "stage_II": {4, 5, 6},
        "stage_resectable": {1, 2, 3, 4, 5, 6},   # overlaps both
    }
    kept, dropped = disjoint_arms(["stage_I", "stage_II", "stage_resectable"], member_sets)
    assert kept == ["stage_I", "stage_II"]
    assert dropped == ["stage_resectable"]


def _fake_reader(target, indication, *, subgroups=None,
                 subgroup_assignments_manifest=None, subgroup_catalog_repo=None,
                 scale=1.0):
    """Fake @subgroup_iterable-style reader: returns {stratum: record} directly."""
    out = {}
    for i, s in enumerate(subgroups):
        n = (i + 1) * 40  # 40, 80, ...  all clear the floor
        out[s] = {
            "metric": round(0.1 * (i + 1) * scale, 4),
            "subgroup_n": n,
            "subgroup_n_floor_met": n >= SUBGROUP_N_FLOOR,
            "evidence_state": evidence_state(n, n >= SUBGROUP_N_FLOOR),
            "source_cohort": "FAKE",
        }
    return out


def test_build_panorama_generic_shape():
    def projection(stratum_id, rec):
        return {
            "stratum": stratum_id,
            "metric": rec["metric"],
            "subgroup_n": rec["subgroup_n"],
            "subgroup_n_floor_met": rec["subgroup_n_floor_met"],
            "evidence_state": rec["evidence_state"],
            "source_cohort": rec["source_cohort"],
        }

    pan = build_panorama(
        _fake_reader,
        target="KRAS", indication="COADREAD",
        subgroups=["A", "B", "C"],
        subgroup_assignments_manifest="fake-v1",
        record_projection=projection,
        reducer=partial(delta_reducer, metric_key="metric", label="metric"),
        reader_kwargs={"scale": 2.0},
    )
    assert pan["target"] == "KRAS"
    assert [r["stratum"] for r in pan["per_subgroup_metrics"]] == ["A", "B", "C"]
    # scale=2.0 threaded through reader_kwargs → metrics 0.2, 0.4, 0.6
    assert pan["max_subgroup_metric"] == 0.6
    assert pan["min_subgroup_metric"] == 0.2
    assert pan["cross_subgroup_delta_metric"] == 0.4
    assert pan["n_subgroups_with_data"] == 3
    # every record carries the mandatory provenance field
    assert all(r["source_cohort"] == "FAKE" for r in pan["per_subgroup_metrics"])
