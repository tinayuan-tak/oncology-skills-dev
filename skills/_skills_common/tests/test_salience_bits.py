"""Salience in bits — the per-frame measurement, its three exclusions, and the two pinned failures.

`cohort_bits` reports how surprising a card's value is against the frozen known-target cohort, in bits
of two-sided empirical self-information. It is the label-free replacement for reading rank off a hand-set
`priority:` rung.

The half of this file that matters most is at the bottom. Stage 1 pre-registered two falsifications, and
BOTH fired against the shipped atlas, so they are pinned here as measurements rather than deleted as
inconvenient:

  * `test_min_over_frames_would_be_vacuous_today` — no spec carries more than ONE cohort_percentile frame,
    so the planned `min_R` could never differ from `max_R`.
  * `test_cross_axis_aggregation_ranks_the_negative_controls_first` — summing bits across axes puts the
    curated housekeeping/absent controls in the top ranks, because 10 of the 20 usable reference columns
    are one measurement ("how much of it is there") read ten ways.

Both tests assert the CURRENT, BROKEN state on purpose. If either goes red, the substrate has changed in
the direction that makes cross-frame aggregation viable — that is the signal to revisit it, not a
regression. Each says so in its own failure message.
"""

from __future__ import annotations

import bisect
import math
import statistics
from collections import Counter

import pytest
from _skills_common.archetype_core import (
    USABLE_REFERENCE_MASK_FRACTION,
    _cohort_sorted_column,
    _shipped_atlas_or_none,
    cohort_reference_quality,
)
from _skills_common.evidence_salience import (
    SALIENCE_SPECS,
    _bits_for_cohort_frame,
    build_interpretation,
    cohort_bits,
)

# ── the bit formula ──────────────────────────────────────────────────────────────────────────────────


def test_median_is_exactly_zero_and_unsigned():
    """A middling value is worth NO bits — the correct reading of an unremarkable number, and it must not
    be the signed zero that -log2(1.0) natively produces (json.dumps writes that as "-0.0")."""
    z = cohort_bits(50.0, 297)
    assert z == 0.0
    assert math.copysign(1.0, z) > 0, "-0.0 leaked: an exactly-median card would be byte-unstable"


def test_two_sided_scores_both_tails_equally():
    """Polarity is already carried by `direction`/_DIR_SIGN. Folding it into the surprise as well would
    double-count it, so p and 100-p must be worth the same."""
    for p in (0.0, 5.0, 25.0, 49.9):
        assert cohort_bits(p, 240) == cohort_bits(100.0 - p, 240)


def test_extremum_is_capped_at_the_cohort_resolution_not_infinite():
    """The 1/(n+1) floor on p_hat IS the plan's log2(n_R+1) ceiling on the bits. Without it the most
    extreme value scores inf and wins every argmax forever — the +-Inf-log2FC failure mode, where a
    non-finite sentinel is still a number and abs(inf) takes every max()."""
    for n in (20, 180, 297):
        top = cohort_bits(0.0, n)
        assert math.isfinite(top)
        assert top == pytest.approx(math.log2(n + 1), abs=1e-3)
    # and the cap BINDS: a bigger cohort resolves a smaller tail, so it earns strictly more bits
    assert cohort_bits(0.0, 297) > cohort_bits(0.0, 180) > cohort_bits(0.0, 20)


def test_a_percentile_is_not_worth_more_bits_just_because_the_cohort_grew():
    """Away from the floor the surprise is a property of the TAIL, not of n. p2 in a 180-target column and
    p2 in a 297-target column are the same claim."""
    assert cohort_bits(2.0, 180) == cohort_bits(2.0, 297)


def test_unreadable_inputs_yield_none_never_zero():
    """None means "could not look"; 0.0 means "looked, and it was median". Collapsing them is the whole
    silent-degradation bug class, so the boundary is asserted directly."""
    for pct, n in ((None, 297), (50.0, None), (50.0, 0), (50.0, -1), (True, 297), (50.0, True)):
        assert cohort_bits(pct, n) is None, f"({pct!r}, {n!r}) must be unreadable, not a number"


# ── the three exclusions ─────────────────────────────────────────────────────────────────────────────

_LIVE_KEY = "crispr_lof_dependency::num::median_chronos_panel"  # rmf 1.000, n 297 — the worked anchor


def _frame(**kw):
    return {"kind": "cohort_percentile", "scale": "chronos", "cohort_key": _LIVE_KEY, **kw}


def test_the_positive_control_actually_scores():
    """Anti-vacuity FIRST: if the happy path did not produce bits, every refusal below would pass for the
    wrong reason and this file would prove nothing."""
    bits, withheld = _bits_for_cohort_frame(_frame(), 4.0, 297)
    assert withheld is None
    assert bits is not None and bits > 0


def test_display_only_ruler_is_refused():
    """atlas_numeric: False axes mint no atlas numeric ON PURPOSE — a mutation-SHAPE fraction has no fixed
    polarity (high missense reads driver for an oncogene, passenger for a TSG). Scoring them scores what
    was deliberately excluded."""
    bits, withheld = _bits_for_cohort_frame(_frame(atlas_numeric=False), 4.0, 297)
    assert bits is None and withheld == "display_only_ruler"


@pytest.mark.parametrize("scale", ["qvalue", "q_value", "pvalue", "QValue"])
def test_significance_scales_are_refused(scale):
    """The q-value pass-through is dropped, not passed through. A driver q is ~0 for every gene that has
    one, so -log2 q is maximal for essentially the whole corpus: the axis would rank as the most
    surprising thing in every profile while discriminating nothing."""
    bits, withheld = _bits_for_cohort_frame(_frame(scale=scale), 4.0, 297)
    assert bits is None and withheld == "significance_scale_not_rankable"


def test_undermeasured_reference_is_refused_and_names_its_fraction():
    """tumor_protein_abundance is the live case: measured in 143 of 297 corpus targets. It stays perfectly
    usable as a VALUE and is rejected as a REFERENCE, and the reason carries the number so the refusal is
    auditable without re-reading the atlas."""
    key = "tumor_protein_abundance::num::protein_effect_size"
    q = cohort_reference_quality(key)
    assert q is not None and q < USABLE_REFERENCE_MASK_FRACTION, f"fixture drifted: rmf={q}"
    bits, withheld = _bits_for_cohort_frame(_frame(cohort_key=key), 4.0, 240)
    assert bits is None
    assert withheld == f"reference_undermeasured_{q:.2f}"


def test_absent_column_is_refused_rather_than_scored_against_nothing():
    """The frame self-drop, inherited. Computing log2(n+1) against an empty column returns a confident 0
    that is indistinguishable from a genuinely median value."""
    bits, withheld = _bits_for_cohort_frame(_frame(cohort_key="not_a_real::num::column"), 4.0, 297)
    assert bits is None and withheld == "reference_quality_unknown"


def test_mask_columns_can_never_read_as_a_usable_reference():
    """Every ::mask column records reference_mask_fraction 1.000 BY CONSTRUCTION — a mask is measured for
    every target — so the >=0.6 gate is vacuous against masks while a rank inside a 0/1 Bernoulli column
    still comes back as a confident-looking percentile. Excluded at the reader so no caller can be fooled."""
    a = _shipped_atlas_or_none()
    if a is None:
        pytest.skip("shipped atlas absent")
    masks = [k for k in a.feature_order if k.endswith("::mask")]
    assert masks, "no ::mask columns found — this guard would be vacuous"
    raw = {a.reference_mask_fraction[a.feature_order.index(k)] for k in masks}
    assert raw == {1.0}, f"a ::mask column no longer reads 1.000 ({raw}) — re-derive this exclusion"
    assert all(cohort_reference_quality(k) is None for k in masks)


# ── reachability through the PUBLIC entry point ──────────────────────────────────────────────────────


def test_bits_reach_the_projected_interpretation():
    """The exclusion tests above call `_bits_for_cohort_frame` directly, which proves the logic and NOT the
    wiring. This drives the real entry point on a live spec so the field cannot be dead code — the failure
    mode where a display projection is correct in isolation and never actually reached."""
    out = build_interpretation(
        {},
        {"median_chronos_panel": -1.05, "dep_control_position_class": "strongly_dependent"},
        SALIENCE_SPECS["crispr_lof_dependency"],
        card_id="crispr-lof-dependency",
    )
    cohort = [gv for gv in out if gv.get("frame", {}).get("kind") == "cohort_percentile"]
    assert len(cohort) == 1, f"expected exactly one cohort ruler, got {len(cohort)}"
    assert cohort[0]["bits"] == pytest.approx(cohort_bits(cohort[0]["cohort_percentile"], cohort[0]["cohort_n"]))
    # the non-cohort frame on the same card carries neither key: bits are a property of a DISTRIBUTION,
    # and a card-cut ruler has no distribution behind it to be surprising against.
    other = [gv for gv in out if gv.get("frame", {}).get("kind") != "cohort_percentile"]
    assert other, "single-frame card — this half of the assertion would be vacuous"
    assert all("bits" not in gv and "bits_withheld" not in gv for gv in other)


def test_withholding_is_reached_and_carries_its_reason_in_a_real_projection():
    """The live under-measured case end to end. Worth pinning because the SHIPPED display already says
    "stronger than 100% of 143 known targets" here — the percentile keeps rendering, and only the bits
    (the claim that would be ranked on) are withheld, with the fraction named in the reason."""
    out = build_interpretation(
        {},
        {"protein_effect_size": 1.4, "allgene_percentile": 88.0, "protein_effect_cohens_d": 0.62},
        SALIENCE_SPECS["tumor_protein_abundance"],
        card_id="tumor-protein-abundance-cptac",
    )
    withheld = [gv for gv in out if "bits_withheld" in gv]
    assert len(withheld) == 1, "the under-measured cohort ruler did not project — fixture drifted"
    assert withheld[0]["bits_withheld"].startswith("reference_undermeasured_")
    assert "bits" not in withheld[0]
    assert withheld[0]["cohort_percentile"] is not None, "the percentile must still render — only bits stop"


# ── the two pinned failures ──────────────────────────────────────────────────────────────────────────


def test_min_over_frames_would_be_vacuous_today():
    """PINNED FAILURE 1. The plan's `min_R` needs >=2 reference frames on one fact; the fleet appends
    exactly one cohort ruler per axis and skips any spec that already carries one, so the maximum is 1."""
    counts = Counter()
    for spec in SALIENCE_SPECS.values():
        rf = spec.get("reference_frame")
        frames = rf if isinstance(rf, list) else ([rf] if isinstance(rf, dict) else [])
        counts[sum(1 for f in frames if isinstance(f, dict) and f.get("kind") == "cohort_percentile")] += 1
    assert counts[1] > 0, "no spec carries a cohort ruler at all — the fleet loop regressed"
    assert max(counts) == 1, (
        "a SALIENCE_SPEC now carries >1 cohort_percentile frame, so `min` over frames could finally "
        "discriminate. This is GOOD NEWS, not a regression: revisit the cross-frame aggregator that was "
        "deliberately not shipped, and check that min actually differs from max somewhere."
    )


def test_cross_axis_aggregation_ranks_the_negative_controls_first():
    """PINNED FAILURE 2 — the kill criterion. Ranking the corpus by the mean of each target's top-5 bits
    puts the curated controls at the head of the list, because 10 of the 20 usable columns are one
    measurement read ten ways and a control is extreme on exactly that one thing by construction.

    Asserts the BROKEN state so the finding cannot be quietly lost. Going red means the reference set
    became less redundant (e.g. feature_corr landed and the aggregation was corrected) — revisit, don't
    'fix' this test."""
    a = _shipped_atlas_or_none()
    if a is None or not a.reference_mask_fraction:
        pytest.skip("shipped atlas absent or predates reference_mask_fraction")
    usable = [
        (i, k)
        for i, k in enumerate(a.feature_order)
        if "::num::" in k and (cohort_reference_quality(k) or 0.0) >= USABLE_REFERENCE_MASK_FRACTION
    ]
    assert len(usable) >= 15, f"only {len(usable)} usable reference columns — this ranking would be noise"

    ranked = []
    for ti, target in enumerate(a.targets):
        facts = []
        for j, k in usable:
            v = a.X[ti][j] if j < len(a.X[ti]) else None
            if v is None:
                continue
            col = _cohort_sorted_column(k)
            n = len(col)
            pct = round((bisect.bisect_left(col, v) + bisect.bisect_right(col, v)) / 2.0 / n * 100.0, 1)
            b = cohort_bits(pct, n)
            if b is not None:
                facts.append(b)
        if facts:
            label = a.labels[ti] if ti < len(a.labels) else "?"
            ranked.append((statistics.mean(sorted(facts, reverse=True)[:5]), target, label))
    ranked.sort(reverse=True)
    assert len(ranked) > 100, "too few ranked targets to say anything"

    controls_top20 = sum(1 for _, _, lab in ranked[:20] if lab.startswith("control"))
    assert controls_top20 >= 5, (
        f"only {controls_top20} of the top 20 are curated controls (was 10 at 2026-09-13). The reference "
        "set is less redundant than when cross-frame aggregation was shelved — re-measure and reconsider "
        "shipping an aggregator."
    )
