"""Mutation-teeth for the single-source presence tier ladder + n-power buckets (#1742).

Every assertion here is written to FAIL on the pre-#1742 behavior and pass after:
  - the abundance ladder was triplicated with a rounded `3.46` — a value in the
    [3.4594, 3.46) sliver read "weak" before and "moderate" now;
  - the n-power moderate floor had drifted to 20 in some copies and 30 in others —
    the bulk-vs-single-cell divergence is now DELIBERATE and pinned in both directions;
  - a non-finite median (`inf`) admitted as "strong" is now "unmeasured".

Raw inputs are stored and the tier is RE-DERIVED through the production call sites,
so no assertion fixtures a derived value (a derived fixture can never fail).
"""

from __future__ import annotations

from _skills_common.presence_cardboard_figure import _reliability  # noqa: E402
from _skills_common.presence_claims import _tier_from_median  # noqa: E402
from _skills_common.presence_tiers import (  # noqa: E402
    ABUNDANCE_DETECTABLE_LOG2TPM,
    ABUNDANCE_MODERATE_LOG2TPM,
    ABUNDANCE_MODERATE_PCT,
    ABUNDANCE_STRONG_LOG2TPM,
    ABUNDANCE_STRONG_PCT,
    POWER_HIGH_N,
    POWER_MODERATE_N,
    POWER_VERY_HIGH_N,
    SUBGROUP_N_FLOOR,
    abundance_tier_from_median,
    abundance_tier_from_percentile,
)
from _skills_common.subgroup_derivation import (  # noqa: E402
    _nbucket,
    _stratum_tier,
    default_classify,
)


# ── the constants are exactly the intended, upstream-anchored values ────────────
def test_ladder_constants_are_pinned():
    # STRONG stays a skills-specific TPM≈31 cut, DISTINCT from upstream HIGH_LOG2TPM (5.6724).
    assert ABUNDANCE_STRONG_LOG2TPM == 5.0
    # MODERATE aligned to the exact upstream anchor log2(11)≈TPM10 (was a rounded 3.46).
    assert ABUNDANCE_MODERATE_LOG2TPM == 3.4594
    assert ABUNDANCE_DETECTABLE_LOG2TPM == 1.0
    assert (ABUNDANCE_STRONG_PCT, ABUNDANCE_MODERATE_PCT) == (95, 75)


def test_power_floors_are_pinned_and_two_are_deliberately_distinct():
    assert (POWER_HIGH_N, POWER_VERY_HIGH_N) == (100, 100_000)
    # The two moderate floors are intentionally NOT equal: 30 (bulk) vs 20 (single-cell/generic).
    assert SUBGROUP_N_FLOOR == 30
    assert POWER_MODERATE_N == 20
    assert SUBGROUP_N_FLOOR != POWER_MODERATE_N


# ── abundance median ladder — both directions around every cut ──────────────────
def test_median_strong_cut_both_directions():
    assert abundance_tier_from_median(5.0) == "strong"
    assert abundance_tier_from_median(4.999) == "moderate"


def test_median_moderate_cut_aligned_to_3_4594_not_3_46():
    # THE alignment tooth: 3.4595 lands in the [3.4594, 3.46) sliver. Under the old
    # rounded 3.46 it read "weak"; under the exact upstream 3.4594 it reads "moderate".
    assert abundance_tier_from_median(3.4595) == "moderate"
    assert abundance_tier_from_median(3.4594) == "moderate"
    assert abundance_tier_from_median(3.4593) == "weak"


def test_median_detectable_floor_four_tier():
    assert abundance_tier_from_median(1.0) == "weak"
    assert abundance_tier_from_median(0.999) == "absent"


def test_median_three_tier_has_no_absent_floor():
    # Claim A's raw-median branch (absent_floor=False) bottoms out at "weak", never "absent".
    assert abundance_tier_from_median(0.5, absent_floor=False) == "weak"
    assert abundance_tier_from_median(0.0, absent_floor=False) == "weak"


# ── percentile ladder — both directions ─────────────────────────────────────────
def test_percentile_cuts_both_directions():
    assert abundance_tier_from_percentile(95) == "strong"
    assert abundance_tier_from_percentile(94.9) == "moderate"
    assert abundance_tier_from_percentile(75) == "moderate"
    assert abundance_tier_from_percentile(74.9) == "weak"


# ── non-finite trap: inf/nan/None are NOT a measurement ─────────────────────────
def test_non_finite_median_is_not_a_tier():
    assert abundance_tier_from_median(float("inf")) is None
    assert abundance_tier_from_median(float("-inf")) is None
    assert abundance_tier_from_median(float("nan")) is None
    assert abundance_tier_from_median(None) is None
    assert abundance_tier_from_percentile(float("inf")) is None
    assert abundance_tier_from_percentile(float("nan")) is None


def test_tier_from_median_maps_non_finite_to_unmeasured():
    # Pre-fix `inf >= 5` admitted inf as "strong"; nan fell through to "absent".
    assert _tier_from_median(float("inf")) == "unmeasured"
    assert _tier_from_median(float("nan")) == "unmeasured"
    assert _tier_from_median(None) == "unmeasured"


# ── the three median call sites resolve the SAME tier for the SAME input ────────
def test_all_median_call_sites_agree_no_copy_can_drift():
    # If any copy re-hardcoded a divergent cut, one of these would disagree.
    for med in (-2.0, 0.5, 1.0, 3.4593, 3.4594, 3.4595, 4.999, 5.0, 8.0):
        expected = abundance_tier_from_median(med)  # 4-tier reference
        assert _tier_from_median(med) == (expected if expected is not None else "unmeasured")
        # _stratum_tier reads median off a row when no class field is present.
        assert _stratum_tier({"median_log2tpm": med}, default_classify) == expected


# ── n-power buckets — both directions around every floor ────────────────────────
def test_nbucket_generic_grain_floors():
    assert _nbucket(POWER_VERY_HIGH_N) == "very high"
    assert _nbucket(POWER_VERY_HIGH_N - 1) == "high"
    assert _nbucket(POWER_HIGH_N) == "high"
    assert _nbucket(POWER_HIGH_N - 1) == "moderate"
    assert _nbucket(POWER_MODERATE_N) == "moderate"
    assert _nbucket(POWER_MODERATE_N - 1) == "low"
    assert _nbucket(None) == "low"


def test_cardboard_bulk_floor_is_30():
    # tumor-rna-distribution = bulk tumor samples -> moderate opens at SUBGROUP_N_FLOOR (30).
    assert _reliability("tumor-rna-distribution", {"n_tumor_samples": 30}, {}) == "moderate"
    assert _reliability("tumor-rna-distribution", {"n_tumor_samples": 29}, {}) == "low"
    assert _reliability("tumor-rna-distribution", {"n_tumor_samples": 100}, {}) == "high"


def test_cardboard_single_cell_floor_is_20():
    # tumor-scrna-celltype = single-cell donor groups -> moderate opens at POWER_MODERATE_N (20).
    h = {"sc_n_donor_groups": 20}
    assert _reliability("tumor-scrna-celltype-expression", {}, h) == "moderate"
    h19 = {"sc_n_donor_groups": 19}
    assert _reliability("tumor-scrna-celltype-expression", {}, h19) == "low"


def test_bulk_vs_single_cell_divergence_is_pinned():
    # THE deliberate-divergence tooth: at n=25 the SAME count reads differently by GRAIN.
    # Bulk (floor 30) -> low; single-cell (floor 20) -> moderate. Unifying both floors
    # to a single value would break exactly one of these.
    bulk = _reliability("tumor-rna-distribution", {"n_tumor_samples": 25}, {})
    sc = _reliability("tumor-scrna-celltype-expression", {}, {"sc_n_donor_groups": 25})
    assert bulk == "low"
    assert sc == "moderate"
    assert bulk != sc


def test_ssot_median_helper_is_pure_and_finite_guarded():
    # sanity: the helper never raises on odd input types and returns a valid tier or None.
    for v in (0, 1, 5, 3.4594, True, False):
        t = abundance_tier_from_median(v)
        assert t in ("strong", "moderate", "weak", "absent")
    for bad in ("x", [], {}, float("nan")):
        assert abundance_tier_from_median(bad) is None
