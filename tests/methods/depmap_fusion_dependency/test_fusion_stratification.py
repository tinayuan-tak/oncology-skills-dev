"""depmap_fusion_dependency.compute_fusion_stratification — hermetic (synthetic chronos + fusion bool, no S3).

Mirrors depmap_cn_dependency's stratification test shape but for the fusion boolean vector. Pins the
decisive classifications: fusion-positive lines cleanly more dependent → fusion_positive_*_dependent
(the FLI1/ABL1 signal this slice exists to capture, which the mutation + CN paths miss); no separation
→ not_fusion_stratified; too few fusion-positive lines → insufficient_fusion_rate. The one-sided test
guarantees a fusion is NEVER credited with a dependency it lacks (protects the symbol-union v1).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.depmap_fusion_dependency.cli import compute_fusion_stratification  # noqa: E402


def _panel(pos_chronos, neg_chronos):
    """Build (chronos_by_model, fusion_by_model) with N fusion-positive + M fusion-negative lines."""
    chronos, fusion = {}, {}
    i = 0
    for c in pos_chronos:
        m = f"ACH-{i:05d}"; chronos[m] = c; fusion[m] = True; i += 1
    for c in neg_chronos:
        m = f"ACH-{i:05d}"; chronos[m] = c; fusion[m] = False; i += 1
    return chronos, fusion


def test_fusion_positive_strongly_dependent():
    """Fusion-positive lines deeply dependent (~-1.0), negative not (~0) → delta <= -0.5 + significant
    → fusion_positive_strongly_dependent (the FLI1/EWSR1-FLI1 Ewing signal, live delta -0.69)."""
    import random
    rng = random.Random(0)
    pos = [-1.0 + rng.uniform(-0.1, 0.1) for _ in range(24)]
    neg = [-0.05 + rng.uniform(-0.1, 0.1) for _ in range(300)]
    chronos, fusion = _panel(pos, neg)
    s = compute_fusion_stratification(chronos, fusion)
    assert s["fusion_stratification_class"] == "fusion_positive_strongly_dependent"
    assert s["delta_chronos_fusion_positive_vs_negative"] <= -0.5
    assert s["n_fusion_positive"] == 24 and s["n_fusion_negative"] == 300


def test_not_fusion_stratified_when_no_separation():
    """Fusion-positive + negative both near 0 → no dependency difference → not_fusion_stratified
    (the method must NOT fabricate a fusion signal, e.g. the ALK/BRAF live result)."""
    import random
    rng = random.Random(1)
    pos = [-0.02 + rng.uniform(-0.08, 0.08) for _ in range(24)]
    neg = [0.0 + rng.uniform(-0.08, 0.08) for _ in range(300)]
    chronos, fusion = _panel(pos, neg)
    s = compute_fusion_stratification(chronos, fusion)
    assert s["fusion_stratification_class"] == "not_fusion_stratified"


def test_moderate_tier():
    """A modest but real separation (delta ~ -0.3) → fusion_positive_moderately_dependent (ABL1 live -0.47)."""
    import random
    rng = random.Random(2)
    pos = [-0.35 + rng.uniform(-0.08, 0.08) for _ in range(30)]
    neg = [-0.02 + rng.uniform(-0.08, 0.08) for _ in range(300)]
    chronos, fusion = _panel(pos, neg)
    s = compute_fusion_stratification(chronos, fusion)
    assert s["fusion_stratification_class"] == "fusion_positive_moderately_dependent"
    assert -0.5 < s["delta_chronos_fusion_positive_vs_negative"] <= -0.2


def test_insufficient_fusion_rate():
    """Fewer than min_positive (5) fusion-positive lines → insufficient_fusion_rate, never a call
    off an underpowered fusion-positive group."""
    import random
    rng = random.Random(3)
    pos = [-1.2, -1.1, -1.3]  # only 3 fusion-positive
    neg = [0.0 + rng.uniform(-0.08, 0.08) for _ in range(300)]
    chronos, fusion = _panel(pos, neg)
    s = compute_fusion_stratification(chronos, fusion)
    assert s["fusion_stratification_class"] == "insufficient_fusion_rate"


def test_fusion_negative_more_dependent_is_never_mislabeled_positive_dependent():
    """Inverse: fusion-NEGATIVE lines strongly MORE dependent than positive. Key guarantee — a fusion is
    NEVER credited with a dependency it lacks — must hold: the FORWARD `fusion_positive_*_dependent`
    classes must NOT fire (this keeps the symbol-union v1 conservative; a bystander-partner fusion only
    dilutes toward the null). With the second-pass reverse test (gap #4) this strong inverse now
    correctly surfaces as `fusion_negative_strongly_dependent` (verdict-inert)."""
    import random
    rng = random.Random(4)
    pos = [-0.02 + rng.uniform(-0.08, 0.08) for _ in range(24)]
    neg = [-0.6 + rng.uniform(-0.1, 0.1) for _ in range(300)]
    chronos, fusion = _panel(pos, neg)
    s = compute_fusion_stratification(chronos, fusion)
    assert s["fusion_stratification_class"] not in ("fusion_positive_strongly_dependent",
                                                    "fusion_positive_moderately_dependent")
    assert s["fusion_stratification_class"] == "fusion_negative_strongly_dependent"
    assert s["fusion_stratification_mannwhitney_q_reverse"] < 0.05
    assert s["delta_chronos_fusion_positive_vs_negative"] > 0   # negative arm more dependent → positive delta
