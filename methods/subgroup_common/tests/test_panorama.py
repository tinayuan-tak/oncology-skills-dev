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
    build_panorama,
    delta_reducer,
    evidence_state,
)


def test_evidence_state_trichotomy():
    assert evidence_state(0, False) == "absent"
    assert evidence_state(10, False) == "underpowered"
    assert evidence_state(50, True) == "measured"
    # floor constant is the shared single source of truth
    assert SUBGROUP_N_FLOOR == 30


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
