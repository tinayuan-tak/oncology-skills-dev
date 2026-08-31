"""B11-S1-2: the across-subtype KW/ε² omnibus must run PER AXIS over disjoint arms.

A subtype shard packs strata from several ORTHOGONAL axes (MSI, CMS, …) whose memberships
OVERLAP — the same sample sits in one arm per axis. Feeding all strata into ONE
`kruskal_epsilon_squared` call replicates each sample ~n_axes-fold (inflating N and
invalidating ε²). `kruskal_epsilon_squared_by_axis` groups strata by axis and runs one omnibus
per axis, so N is never inflated and the effect-size class is computed on a valid single-axis test.
"""
from __future__ import annotations

from methods.tcga_gtex_expression_distribution.stats import (
    kruskal_epsilon_squared,
    kruskal_epsilon_squared_by_axis,
)


def _two_axis_vectors():
    """40 samples partitioned two orthogonal ways:
      MSI axis  — MSI_H (samples 0-19, HIGH) vs MSS (20-39, LOW): strong separation.
      CMS axis  — CMS1 (even idx) vs CMS2 (odd idx): interleaved → no separation.
    The SAME 40 samples appear in BOTH axes' arms (overlapping membership)."""
    high = [5.0 + (i % 5) * 0.1 for i in range(20)]   # samples 0-19
    low = [1.0 + (i % 5) * 0.1 for i in range(20)]    # samples 20-39
    msi_h, mss = high, low
    all_vals = high + low                              # index i -> sample i's value
    cms1 = [all_vals[i] for i in range(40) if i % 2 == 0]
    cms2 = [all_vals[i] for i in range(40) if i % 2 == 1]
    vectors = {"MSI_H": msi_h, "MSS": mss, "CMS1": cms1, "CMS2": cms2}
    member_sets = {
        "MSI_H": set(range(0, 20)), "MSS": set(range(20, 40)),
        "CMS1": {i for i in range(40) if i % 2 == 0},
        "CMS2": {i for i in range(40) if i % 2 == 1},
    }
    return vectors, member_sets


def test_per_axis_does_not_double_count_samples():
    vectors, member_sets = _two_axis_vectors()

    # The OLD naive single pooled call over all 4 strata double-counts: N = 80 (each of the
    # 40 samples appears once in an MSI arm AND once in a CMS arm).
    naive = kruskal_epsilon_squared(vectors)
    assert naive["n_samples_tested"] == 80  # the invalid inflation the fix removes

    # PER-AXIS: two axes, each tested over the true 40 samples — never pooled across axes.
    out = kruskal_epsilon_squared_by_axis(vectors, member_sets)
    assert out["n_axes_tested"] == 2
    by_axis = {a["axis"]: a for a in out["subtype_omnibus_by_axis"]}
    assert set(by_axis) == {"MSI", "CMS"}
    assert by_axis["MSI"]["n_samples_tested"] == 40
    assert by_axis["CMS"]["n_samples_tested"] == 40

    # MSI separates strongly; CMS (interleaved) does not → MSI is the driving axis.
    assert out["driving_axis"] == "MSI"
    assert by_axis["MSI"]["subtype_variance_explained"] > by_axis["CMS"]["subtype_variance_explained"]
    # flat back-compat fields carry the driving axis's VALID number
    assert out["subtype_variance_explained"] == by_axis["MSI"]["subtype_variance_explained"]
    assert out["subtype_effect_size_class"] == by_axis["MSI"]["subtype_effect_size_class"]


def test_per_axis_drops_within_axis_overlapping_composite():
    """A composite arm that overlaps its axis-mates (e.g. stage_resectable ⊇ stage_I/II) is
    dropped by the disjointness guard so the axis omnibus runs over disjoint arms only."""
    vectors = {
        "stage_I": [1.0, 1.1, 1.2, 1.3],
        "stage_II": [3.0, 3.1, 3.2, 3.3],
        "stage_resectable": [1.0, 1.1, 1.2, 1.3, 3.0, 3.1, 3.2, 3.3],  # = I ∪ II
    }
    member_sets = {"stage_I": {1, 2, 3, 4}, "stage_II": {5, 6, 7, 8},
                   "stage_resectable": set(range(1, 9))}
    out = kruskal_epsilon_squared_by_axis(vectors, member_sets)
    assert out["n_axes_tested"] == 1
    stage = out["subtype_omnibus_by_axis"][0]
    assert stage["axis"] == "stage"
    assert stage["strata"] == ["stage_I", "stage_II"]   # resectable dropped
    assert stage["n_samples_tested"] == 8               # not 16


def test_empty_and_singleton_axis_safe():
    assert kruskal_epsilon_squared_by_axis({})["n_axes_tested"] == 0
    # a single arm on an axis is not testable (need >= 2 disjoint arms)
    out = kruskal_epsilon_squared_by_axis({"MSI_H": [1.0, 2.0, 3.0]}, {"MSI_H": {1, 2, 3}})
    assert out["n_axes_tested"] == 0
    assert out["subtype_effect_size_class"] == "data_unavailable"
