"""Deferred-(d): the Mann-Whitney determinism pin is VERDICT-NEUTRAL.

The primitive now sets method="auto" + use_continuity=True EXPLICITLY. These are scipy's current
defaults, so pinning them must not change any p-value — it only makes the exact/asymptotic behaviour
version-stable. This test proves byte-identity to the unset-default call across the exact-regime
(n<=8) and asymptotic-regime (n>=9) boundary.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
scipy_stats = pytest.importorskip("scipy.stats")

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.depmap_mutation_dependency.cli import _mannwhitney_stratification  # noqa: E402


@pytest.mark.parametrize("n_mut", [5, 6, 8, 9, 20, 60])
def test_pinned_forward_p_matches_unset_default(n_mut):
    rng = np.random.RandomState(0)
    chronos, mut = {}, {}
    i = 0
    for _ in range(n_mut):
        m = f"ACH-{i:05d}"; chronos[m] = float(rng.normal(-0.8, 0.2)); mut[m] = True; i += 1
    for _ in range(60):
        m = f"ACH-{i:05d}"; chronos[m] = float(rng.normal(-0.05, 0.2)); mut[m] = False; i += 1

    # the pinned primitive
    r = _mannwhitney_stratification(chronos, mut)

    # the historical unset-default call on the same arrays
    common = set(chronos) & set(mut)
    mut_arr = np.array([chronos[k] for k in common if mut[k]])
    wt_arr = np.array([chronos[k] for k in common if not mut[k]])
    _, p_unset_fwd = scipy_stats.mannwhitneyu(mut_arr, wt_arr, alternative="less")
    _, p_unset_rev = scipy_stats.mannwhitneyu(mut_arr, wt_arr, alternative="greater")

    assert r["p_value"] == pytest.approx(float(p_unset_fwd), rel=0, abs=0), \
        f"pinned forward p diverged from unset default at n_mut={n_mut}"
    assert r["p_value_reverse"] == pytest.approx(float(p_unset_rev), rel=0, abs=0), \
        f"pinned reverse p diverged from unset default at n_mut={n_mut}"


def test_pin_preserves_exact_at_small_n_not_asymptotic():
    # The pin (method="auto") must keep the EXACT null at small n, NOT force asymptotic — that is the
    # whole point (forcing asymptotic would degrade small-n accuracy). Note: the exact method ignores
    # use_continuity, so compare auto-with-continuity to bare exact (matched semantics).
    rng = np.random.RandomState(2)
    a = rng.normal(-0.8, 0.2, 5); b = rng.normal(0.0, 0.2, 50)
    _, p_auto = scipy_stats.mannwhitneyu(a, b, alternative="less", method="auto", use_continuity=True)
    _, p_exact = scipy_stats.mannwhitneyu(a, b, alternative="less", method="exact")
    _, p_asymp = scipy_stats.mannwhitneyu(a, b, alternative="less", method="asymptotic", use_continuity=True)
    assert p_auto == p_exact          # auto picks exact at n=5 (one small group)
    assert p_auto != p_asymp          # and it is NOT the asymptotic value (accuracy preserved)
