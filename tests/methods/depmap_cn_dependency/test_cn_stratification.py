"""depmap_cn_dependency.compute_cn_stratification — hermetic (synthetic chronos + CN, no S3).

Mirrors depmap_mutation_dependency's stratification test shape but for the CN vector. Pins the
three decisive classifications: amplified lines cleanly more dependent → amplified_*_dependent;
no separation → not_cn_stratified; too few amplified lines → insufficient_amplification_rate.
Amplified boolean = relative CN > FOCAL_AMP (1.5); neutral = everything else (broad comparator).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.depmap_cn_dependency.cli import FOCAL_AMP_HIGH, compute_cn_stratification  # noqa: E402

# T2.2 (2026-08-09): the DEPENDENCY amplified-arm cut is FOCAL_AMP_HIGH (2.0), not the distribution
# card's shallow FOCAL_AMP (1.5) — a focal high-level amp, not an arm-level relative gain.


def _panel(amp_chronos, neutral_chronos, amp_cn=3.0, neutral_cn=1.0):
    """Build (chronos_by_model, cn_by_model) with N amplified + M neutral lines.
    amp_cn > FOCAL_AMP (amplified), neutral_cn <= FOCAL_AMP (neutral)."""
    chronos, cn = {}, {}
    i = 0
    for c in amp_chronos:
        m = f"ACH-{i:05d}"
        chronos[m] = c
        cn[m] = amp_cn
        i += 1
    for c in neutral_chronos:
        m = f"ACH-{i:05d}"
        chronos[m] = c
        cn[m] = neutral_cn
        i += 1
    return chronos, cn


def test_amplified_strongly_dependent():
    """Amplified lines deeply dependent (~-1.2), neutral not (~0) → delta <= -0.5 + significant
    → amplified_strongly_dependent (the ERBB2-class signal this slice exists to capture)."""
    import random

    rng = random.Random(0)
    amp = [-1.2 + rng.uniform(-0.1, 0.1) for _ in range(40)]
    neutral = [-0.05 + rng.uniform(-0.1, 0.1) for _ in range(300)]
    chronos, cn = _panel(amp, neutral)
    s = compute_cn_stratification(chronos, cn)
    assert s["cn_stratification_class"] == "amplified_strongly_dependent"
    assert s["delta_chronos_amplified_vs_neutral"] <= -0.5
    assert s["n_amplified"] == 40 and s["n_neutral"] == 300
    assert s["amplification_threshold_relative_cn"] == FOCAL_AMP_HIGH


def test_not_cn_stratified_when_no_separation():
    """Amplified + neutral both near 0 → no dependency difference → not_cn_stratified
    (the method must NOT fabricate a CN signal, e.g. the MET/EGFR live result)."""
    import random

    rng = random.Random(1)
    amp = [-0.02 + rng.uniform(-0.08, 0.08) for _ in range(40)]
    neutral = [0.0 + rng.uniform(-0.08, 0.08) for _ in range(300)]
    chronos, cn = _panel(amp, neutral)
    s = compute_cn_stratification(chronos, cn)
    assert s["cn_stratification_class"] == "not_cn_stratified"


def test_moderate_tier():
    """A modest but real separation (delta ~ -0.3) → amplified_moderately_dependent (ERBB2/MYC live)."""
    import random

    rng = random.Random(2)
    amp = [-0.35 + rng.uniform(-0.08, 0.08) for _ in range(50)]
    neutral = [-0.02 + rng.uniform(-0.08, 0.08) for _ in range(300)]
    chronos, cn = _panel(amp, neutral)
    s = compute_cn_stratification(chronos, cn)
    assert s["cn_stratification_class"] == "amplified_moderately_dependent"
    assert -0.5 < s["delta_chronos_amplified_vs_neutral"] <= -0.2


def test_insufficient_amplification_rate():
    """Fewer than min_amplified (5) amplified lines → insufficient_amplification_rate, never a call
    off an underpowered amplified group."""
    import random

    rng = random.Random(3)
    amp = [-1.2, -1.1, -1.3]  # only 3 amplified
    neutral = [0.0 + rng.uniform(-0.08, 0.08) for _ in range(300)]
    chronos, cn = _panel(amp, neutral)
    s = compute_cn_stratification(chronos, cn)
    assert s["cn_stratification_class"] == "insufficient_amplification_rate"


def test_neutral_more_dependent_is_never_mislabeled_amplified_dependent():
    """Inverse: neutral lines strongly MORE dependent than amplified. The KEY GUARANTEE — amplification
    is NEVER credited with a dependency it lacks — must hold: the FORWARD `amplified_*_dependent` classes
    must NOT fire. With the second-pass reverse test (gap #4) this strong inverse now correctly surfaces
    as `neutral_strongly_dependent` (verdict-inert: consumed by no rule/resolver) instead of being lost
    as `not_cn_stratified`."""
    import random

    rng = random.Random(4)
    amp = [-0.02 + rng.uniform(-0.08, 0.08) for _ in range(40)]
    neutral = [-0.6 + rng.uniform(-0.1, 0.1) for _ in range(300)]
    chronos, cn = _panel(amp, neutral)
    s = compute_cn_stratification(chronos, cn)
    # the load-bearing guarantee: forward classes never fire on a reverse pattern
    assert s["cn_stratification_class"] not in ("amplified_strongly_dependent", "amplified_moderately_dependent")
    # reverse direction is now reachable + significance-gated
    assert s["cn_stratification_class"] == "neutral_strongly_dependent"
    assert s["cn_stratification_mannwhitney_q_reverse"] < 0.05
    assert s["delta_chronos_amplified_vs_neutral"] > 0  # neutral more dependent → positive delta


def test_shallow_gain_excluded_from_amplified_arm():
    """T2.2: a shallow relative gain (1.5-2.0, arm-level) is NOT counted amplified — only focal
    high-level (>2.0). Build 40 shallow-gain 'amplified-looking' lines at cn=1.7 (below the 2.0
    focal cut) that ARE dependent; they must NOT form an amplified arm → insufficient/not-stratified,
    not amplified_strongly_dependent off arm-level gain."""
    import random

    rng = random.Random(9)
    shallow = [-1.2 + rng.uniform(-0.1, 0.1) for _ in range(40)]  # dependent, but only cn=1.7
    neutral = [-0.05 + rng.uniform(-0.1, 0.1) for _ in range(300)]
    chronos, cn = _panel(shallow, neutral, amp_cn=1.7)  # 1.7 < FOCAL_AMP_HIGH (2.0)
    s = compute_cn_stratification(chronos, cn)
    # all 40 "amplified-looking" lines fall below the focal cut → 0 amplified → not a focal-amp call
    assert s["n_amplified"] == 0
    assert s["cn_stratification_class"] in ("insufficient_amplification_rate", "not_cn_stratified")
