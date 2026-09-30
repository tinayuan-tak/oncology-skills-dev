"""cn_homozygous_deletion_recurrent — the DISPLAY flag isolating recurrent DEEP (homozygous)
deletion, distinct from copy_number_class (which folds deep+shallow into recurrently_deleted).

Key byte-stability property: adding this flag must NOT change copy_number_class (verdict-driving).
"""

from __future__ import annotations

from onc_methods.depmap_cn_distribution.cli import compute_summary_stats


def _cn(n_deep, n_total, deep_val=0.1, other=1.0):
    return {f"M{i}": (deep_val if i < n_deep else other) for i in range(n_total)}


def test_recurrent_homdel_flag_fires_above_threshold():
    s = compute_summary_stats(_cn(6, 20), {}, "wes")  # 30% deep-del
    assert s["cn_homozygous_deletion_recurrent"] == "recurrent_homozygous_deletion"
    # copy_number_class UNCHANGED (deep folds into recurrently_deleted) — verdict spine intact
    assert s["copy_number_class"] == "recurrently_deleted"


def test_flag_not_fired_below_threshold():
    s = compute_summary_stats(_cn(2, 20), {}, "wes")  # 10% deep-del < 20%
    assert s["cn_homozygous_deletion_recurrent"] == "not_recurrent_homozygous_deletion"


def test_flag_data_unavailable_on_empty():
    s = compute_summary_stats({}, {}, "wes")
    assert s["cn_homozygous_deletion_recurrent"] == "data_unavailable"


def test_shallow_del_does_not_trip_homdel_flag():
    # shallow deletions (0.6, between DEEP_DEL 0.5 and SHALLOW_DEL) must NOT count as homozygous.
    s = compute_summary_stats(_cn(10, 20, deep_val=0.6), {}, "wes")
    assert s["cn_homozygous_deletion_recurrent"] == "not_recurrent_homozygous_deletion"


def test_underpowered_below_cn_floor():
    # PR-C3: fewer than MIN_COVERED_CN (20) CN-covered cell lines → too thin to characterize a
    # recurrence pattern. copy_number_class emits `underpowered` (coverage gap → insufficient),
    # NOT broadly_neutral (a measured negative) — even when every line is deeply deleted.
    s = compute_summary_stats(_cn(15, 15), {}, "wes")  # 15 lines, all deep-del
    assert s["cn_n_cell_lines_evaluated"] == 15
    assert s["copy_number_class"] == "underpowered"


def test_at_cn_floor_is_powered():
    # Exactly MIN_COVERED_CN (20) clears the floor — classification proceeds.
    s = compute_summary_stats(_cn(10, 20), {}, "wes")  # 50% deep-del
    assert s["cn_n_cell_lines_evaluated"] == 20
    assert s["copy_number_class"] == "recurrently_deleted"
