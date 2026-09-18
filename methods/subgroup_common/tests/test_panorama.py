"""Tests for subgroup_common.panorama — the substrate-agnostic composer.

Uses a trivial fake reader (no real data) to prove the generic mechanics:
fan-out collection, projection, cross-stratum reduction, and the shared
evidence_state / SUBGROUP_N_FLOOR primitives. Substrate-specific readers are
tested in their own method packages.
"""

from __future__ import annotations

from functools import partial

import pytest

from methods.subgroup_common.panorama import (
    SUBGROUP_EXPLORATORY_FLOOR,
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
    # every stratum EVALUATED and none has members — a real negative about the axis.
    # (The DepMap STAD/PAAD shards were long cited here as the example. They are NOT:
    # measured 2026-09-18, both are 100% is_member=None, i.e. `unevaluable`. See
    # test_axis_quality_unevaluable_outranks_empty.)
    assert axis_quality([a, a, a]) == "empty"
    # no records at all → no axis
    assert axis_quality([]) == "unavailable"
    # threshold is tunable
    assert axis_quality([m], min_powered_strata=1) == "powered"


# ---- the two opt-in grades ---------------------------------------------------------
#
# `unevaluable` and `exploratory` are additive: both are reachable ONLY when a reader
# passes the corresponding keyword. The byte-identity test below is the load-bearing
# guard for the eight existing call sites and the nine cards that still declare
# `evidence_state: {enum: [measured, underpowered, absent]}`.

_HISTORICAL_STATES = frozenset({"measured", "underpowered", "absent"})


@pytest.mark.parametrize("n", [0, 1, 2, 9, 10, 11, 29, 30, 31, 50, 600])
@pytest.mark.parametrize("floor_met", [False, True])
def test_evidence_state_positional_call_is_byte_identical(n, floor_met):
    """NULL DIFF over the whole (n, floor_met) grid: the 2-arg call is unchanged.

    Reproduces the pre-change implementation independently rather than comparing the
    function to itself, so this cannot pass vacuously.
    """
    historical = "absent" if n == 0 else ("measured" if floor_met else "underpowered")
    assert evidence_state(n, floor_met) == historical
    assert evidence_state(n, floor_met) in _HISTORICAL_STATES
    # explicit-default keywords are also inert
    assert evidence_state(n, floor_met, evaluated=None, exploratory_floor=None) == historical


def test_evidence_state_unevaluable_requires_explicit_false():
    """An UNCLASSIFIED stratum abstains instead of asserting a measured absence."""
    assert evidence_state(0, False, evaluated=False) == "unevaluable"
    # evaluated=True is the affirmative "we looked" → a real negative
    assert evidence_state(0, False, evaluated=True) == "absent"
    # ANTI-VACUITY: the two 0-member arms must actually differ, or the fix is cosmetic
    assert evidence_state(0, False, evaluated=False) != evidence_state(0, False, evaluated=True)
    # `evaluated` is consulted ONLY at n == 0 — a stratum with members was evaluated by
    # construction, so a contradictory flag cannot manufacture a false unevaluable.
    assert evidence_state(5, False, evaluated=False) == "underpowered"
    assert evidence_state(50, True, evaluated=False) == "measured"


def test_evidence_state_exploratory_band():
    """10-29 becomes visible WITHOUT relaxing the floor of 30."""
    f = SUBGROUP_EXPLORATORY_FLOOR
    assert f == 10 and f < SUBGROUP_N_FLOOR
    assert evidence_state(10, False, exploratory_floor=f) == "exploratory"
    assert evidence_state(29, False, exploratory_floor=f) == "exploratory"
    # below the exploratory floor is still simply underpowered
    assert evidence_state(9, False, exploratory_floor=f) == "underpowered"
    assert evidence_state(1, False, exploratory_floor=f) == "underpowered"
    # THE BAR IS NOT RELAXED: floor_met still decides `measured`, and 29 never reaches it
    assert evidence_state(30, True, exploratory_floor=f) == "measured"
    assert evidence_state(29, False, exploratory_floor=f) != "measured"
    # a 0-member stratum is never exploratory
    assert evidence_state(0, False, exploratory_floor=f) == "absent"


def test_evidence_state_both_kwargs_compose():
    f = SUBGROUP_EXPLORATORY_FLOOR
    assert evidence_state(0, False, evaluated=False, exploratory_floor=f) == "unevaluable"
    assert evidence_state(15, False, evaluated=True, exploratory_floor=f) == "exploratory"


def test_axis_quality_unevaluable_outranks_empty():
    """An axis nobody classified must NOT be graded `empty` — that is a false absence.

    The real defect: the DepMap paad + stad shards are 100% is_member=None, so every
    stratum reported 0 members and the axis graded `empty` — "we looked, no cell line is
    a member" — when nothing had been looked at.
    """
    a = {"evidence_state": "absent"}
    x = {"evidence_state": "unevaluable"}
    assert axis_quality([x, x]) == "unevaluable"
    # MIXED: the absent half is a real negative, but it cannot carry an absence claim for
    # the strata never examined, so the conservative grade wins.
    assert axis_quality([x, a]) == "unevaluable"
    assert axis_quality([a, x, a]) == "unevaluable"
    # ANTI-VACUITY: `empty` must remain reachable, or this is a blanket rename
    assert axis_quality([a, a]) == "empty"
    assert axis_quality([x, x]) != axis_quality([a, a])
    # any real evaluated evidence outranks the abstention
    m = {"evidence_state": "measured"}
    u = {"evidence_state": "underpowered"}
    assert axis_quality([m, m, x]) == "powered"
    assert axis_quality([u, x]) == "underpowered"


def test_axis_quality_exploratory_grade():
    m = {"evidence_state": "measured"}
    e = {"evidence_state": "exploratory"}
    u = {"evidence_state": "underpowered"}
    a = {"evidence_state": "absent"}
    # contrastable as a HYPOTHESIS: >=2 of (measured + exploratory) but <2 measured
    assert axis_quality([e, e]) == "exploratory"
    assert axis_quality([m, e]) == "exploratory"
    assert axis_quality([m, e, u, a]) == "exploratory"
    # THE BAR IS NOT RELAXED: two measured strata are still required for `powered`
    assert axis_quality([m, e]) != "powered"
    assert axis_quality([m, m, e]) == "powered"
    # a single exploratory stratum contrasts with nothing
    assert axis_quality([e, u, a]) == "underpowered"
    assert axis_quality([e]) == "underpowered"
    # the one knob governs both thresholds
    assert axis_quality([e], min_powered_strata=1) == "exploratory"
    # HNSC shape measured 2026-09-18: oral_cavity 63 (measured), larynx 10 (exploratory),
    # oropharyngeal 2 (underpowered), 6 further strata never classified.
    assert axis_quality([m, e, u] + [{"evidence_state": "unevaluable"}] * 6) == "exploratory"


def test_axis_quality_historical_records_are_byte_identical():
    """NULL DIFF: over every combination of the three historical states, the grade is
    exactly what the pre-change implementation returned."""
    from itertools import combinations_with_replacement

    def historical(states):
        if not states:
            return "unavailable"
        if all(s == "absent" for s in states):
            return "empty"
        return "powered" if sum(1 for s in states if s == "measured") >= 2 else "underpowered"

    for k in range(1, 5):
        for combo in combinations_with_replacement(sorted(_HISTORICAL_STATES), k):
            records = [{"evidence_state": s} for s in combo]
            assert axis_quality(records) == historical(combo), combo
    assert axis_quality([]) == "unavailable"


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
    assert out["max_subgroup_frequency"] == 0.50  # NOT the 0.99 underpowered outlier
    assert out["min_subgroup_frequency"] == 0.40
    assert out["cross_subgroup_delta_frequency"] == 0.1  # 0.50-0.40, not 0.99-0.40
    assert out["n_subgroups_measured"] == 2
    assert out["n_subgroups_with_data"] == 3  # underpowered stratum still has samples


def test_delta_reducer_excludes_exploratory_and_unevaluable():
    """A new grade must be excluded from the spread BY DEFAULT, not by a deny-list.

    `exploratory` exists so a 10-29-member stratum stops being invisible — NOT so it can
    carry a comparative claim. The reducer's `== "measured"` test is what guarantees that,
    and this pins it: an extreme exploratory value must not move max/min/delta.
    """
    records = [
        {"metric": 0.50, "subgroup_n": 100, "evidence_state": "measured"},
        {"metric": 0.40, "subgroup_n": 40, "evidence_state": "measured"},
        # 15 members: visible, hypothesis-grade, and 0.99 must NOT reach the spread
        {"metric": 0.99, "subgroup_n": 15, "evidence_state": "exploratory"},
        {"metric": None, "subgroup_n": 0, "evidence_state": "unevaluable"},
    ]
    out = delta_reducer(records, metric_key="metric", label="frequency")
    assert out["max_subgroup_frequency"] == 0.50
    assert out["cross_subgroup_delta_frequency"] == 0.1
    assert out["n_subgroups_measured"] == 2
    # the exploratory stratum HAS samples and is counted as such; the unevaluable one (n=0)
    # is not — an abstention is not data.
    assert out["n_subgroups_with_data"] == 3


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
    axes = partition_axes(
        [
            "MSI_H",
            "MSS",
            "CMS1",
            "CMS2",
            "left_sided",
            "right_sided",
            "CIMP_High",
            "stage_I",
            "stage_II",
            "stage_resectable",
        ]
    )
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
        "stage_resectable": {1, 2, 3, 4, 5, 6},  # overlaps both
    }
    kept, dropped = disjoint_arms(["stage_I", "stage_II", "stage_resectable"], member_sets)
    assert kept == ["stage_I", "stage_II"]
    assert dropped == ["stage_resectable"]


def _fake_reader(
    target, indication, *, subgroups=None, subgroup_assignments_manifest=None, subgroup_catalog_repo=None, scale=1.0
):
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
        target="KRAS",
        indication="COADREAD",
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
