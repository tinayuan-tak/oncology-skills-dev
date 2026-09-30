"""T2.1 hotspot-gate: a directional oncogene-addiction call (mutant_strongly/moderately_dependent)
may be set ONLY from the hotspot (activating) tier. The damaging/'any' pool (activating+LoF+VUS)
cannot MANUFACTURE oncogene-addiction on its own — the biologically-unsound pooled-tier call the
genomic-alteration review flagged.

Pure-dict (no S3): construct chronos + hotspot/damaging bool dicts so the hotspot tier is
underpowered (< min_mutant) while the damaging tier shows a strong directional signal.
"""

from __future__ import annotations

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")


from onc_methods.depmap_mutation_dependency.cli import compute_mutation_stratification as C


def _dicts(n_hot_mut, n_dam_mut, n_wt, mut_chronos, wt_chronos):
    """Build chronos + hotspot + damaging bool dicts. First n_hot_mut lines are hotspot-mutant,
    next n_dam_mut are damaging-only-mutant, rest are WT. Mutant lines get mut_chronos, WT get wt."""
    import random

    rng = random.Random(0)
    chronos, hot, dam = {}, {}, {}
    i = 0
    for _ in range(n_hot_mut):
        m = f"ACH-{i:05d}"
        chronos[m] = mut_chronos + rng.uniform(-0.1, 0.1)
        hot[m] = True
        dam[m] = True
        i += 1
    for _ in range(n_dam_mut):
        m = f"ACH-{i:05d}"
        chronos[m] = mut_chronos + rng.uniform(-0.1, 0.1)
        hot[m] = False
        dam[m] = True
        i += 1
    for _ in range(n_wt):
        m = f"ACH-{i:05d}"
        chronos[m] = wt_chronos + rng.uniform(-0.1, 0.1)
        hot[m] = False
        dam[m] = False
        i += 1
    return chronos, hot, dam


def test_pooled_tier_alone_does_not_confer_oncogene_addiction():
    # hotspot underpowered (3 < min 5); damaging tier has 40 mutants strongly dependent → the OLD
    # behavior would fall through to damaging → mutant_strongly_dependent. T2.1: NOT credited.
    chronos, hot, dam = _dicts(n_hot_mut=3, n_dam_mut=40, n_wt=300, mut_chronos=-1.2, wt_chronos=-0.05)
    r = C(chronos, hot, dam)
    assert r["mutation_stratification_class"] == "not_mutation_stratified"
    assert r["hotspot_gate_note"] is not None and "pooled-tier" in r["hotspot_gate_note"]


def test_hotspot_tier_still_confers_when_powered():
    # hotspot tier well-powered + strong → mutant_strongly_dependent (unchanged; the gate only blocks
    # POOLED-only calls). Note is None.
    chronos, hot, dam = _dicts(n_hot_mut=40, n_dam_mut=0, n_wt=300, mut_chronos=-1.3, wt_chronos=-0.05)
    r = C(chronos, hot, dam)
    assert r["mutation_stratification_class"] == "mutant_strongly_dependent"
    assert r["hotspot_gate_note"] is None


def test_no_signal_anywhere_is_not_stratified():
    chronos, hot, dam = _dicts(n_hot_mut=10, n_dam_mut=20, n_wt=300, mut_chronos=-0.05, wt_chronos=-0.05)
    r = C(chronos, hot, dam)
    assert r["mutation_stratification_class"] == "not_mutation_stratified"
    assert r["hotspot_gate_note"] is None  # no directional pooled call to suppress


# ============================================================================
# Second-pass reverse test (gap #4): the reverse-direction class must be REACHABLE.
# Previously `wt_strongly_dependent` sat behind a `delta >= 0.3` branch that a one-sided
# "less" test could never reach at significance — a dead branch. Now a dedicated reverse
# ("greater") pass makes it fire on genuine WT-more-dependent (TSG synthetic-dependency)
# data, while staying verdict-inert (the consuming rule emits only neutral signals).
# ============================================================================


def test_reverse_direction_now_reachable_wt_strongly_dependent():
    # WT cells strongly dependent, hotspot-mutant cells NOT (positive delta ~ +1.2).
    # Hotspot tier well-powered so the reverse call is set from it.
    chronos, hot, dam = _dicts(n_hot_mut=40, n_dam_mut=0, n_wt=300, mut_chronos=-0.05, wt_chronos=-1.25)
    r = C(chronos, hot, dam)
    assert r["mutation_stratification_class"] == "wt_strongly_dependent"
    assert r["stratification_direction"] == "reverse_wt_dependent"
    # the reverse BH q must be populated + significant; forward q must NOT be significant
    assert r["hotspot_mannwhitney_q_reverse"] is not None
    assert r["hotspot_mannwhitney_q_reverse"] < 0.05
    assert r["hotspot_mannwhitney_q"] >= 0.05


def test_forward_call_byte_identical_after_reverse_pass_added():
    # A forward strong call must be UNCHANGED by the addition of the reverse pass:
    # same class, and the forward q is still the significant driver.
    chronos, hot, dam = _dicts(n_hot_mut=40, n_dam_mut=0, n_wt=300, mut_chronos=-1.3, wt_chronos=-0.05)
    r = C(chronos, hot, dam)
    assert r["mutation_stratification_class"] == "mutant_strongly_dependent"
    assert r["stratification_direction"] == "forward_mutant_dependent"
    assert r["hotspot_mannwhitney_q"] < 0.05
    # the reverse pass on strongly-forward data must NOT be significant (no double-firing)
    assert r["hotspot_mannwhitney_q_reverse"] is None or r["hotspot_mannwhitney_q_reverse"] >= 0.05


def test_reverse_requires_strong_magnitude():
    # A significant-but-small POSITIVE delta (WT only mildly more dependent, +0.15) must NOT
    # cross the strong reverse threshold (>= +0.5) → stays not_mutation_stratified.
    chronos, hot, dam = _dicts(n_hot_mut=60, n_dam_mut=0, n_wt=300, mut_chronos=-0.05, wt_chronos=-0.20)
    r = C(chronos, hot, dam)
    assert r["mutation_stratification_class"] != "wt_strongly_dependent"


def test_uncomputable_is_flagged_not_swallowed():
    # All-identical Chronos in both arms → MW raises → historically p=1.0 (kept), but now the
    # tier is FLAGGED uncomputable rather than silently reported as a tested negative (gap #5).
    chronos, hot, dam = {}, {}, {}
    for i in range(40):
        m = f"ACH-{i:05d}"
        chronos[m] = -0.5
        hot[m] = True
        dam[m] = True
    for i in range(40, 340):
        m = f"ACH-{i:05d}"
        chronos[m] = -0.5
        hot[m] = False
        dam[m] = False
    r = C(chronos, hot, dam)
    assert r["mutation_stratification_class"] in ("not_mutation_stratified", "insufficient_mutation_rate")
    assert "hotspot" in r["_uncomputable_tiers"]  # flagged, not a silent null
