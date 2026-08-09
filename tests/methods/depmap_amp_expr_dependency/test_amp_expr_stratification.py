"""depmap_amp_expr_dependency.compute_amp_expr_stratification — hermetic (synthetic chronos+CN+TPM, no S3).

Mirrors the CN/fusion stratification tests but for the CONJOINT (amplified AND high-TPM) boolean. Pins the
decisive classifications: lines that are BOTH amplified and overexpressed AND cleanly more dependent →
amplified_overexpressed_*_dependent (the ERBB2/MYC signal this slice captures, which the CN-only path
under-weights and the expression facet can't establish); no separation → not_amp_expr_stratified; the
conjunction gates correctly (amplified-but-low-expr and high-expr-but-not-amplified are BOTH excluded from
the positive arm); too few conjoint lines → insufficient_amp_expr_rate. The one-sided test guarantees the
conjunction is never credited with a dependency it lacks.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.depmap_amp_expr_dependency.cli import (  # noqa: E402
    compute_amp_expr_stratification, FOCAL_AMP,
)


def _panel(conjoint_chronos, other_chronos, *, amp_cn=3.0, neut_cn=1.0, high_tpm=9.0, low_tpm=1.0,
           decoy_amp_lowexpr=0, decoy_highexpr_neut=0):
    """Build (chronos, cn, tpm) dicts.

    - conjoint_chronos: lines that are amplified (amp_cn) AND high-expr (high_tpm).
    - other_chronos: plain comparator lines (neutral CN, low TPM).
    - decoy_amp_lowexpr: N extra lines amplified but LOW expression (must NOT enter the positive arm).
    - decoy_highexpr_neut: N extra lines high-expr but NEUTRAL cn (must NOT enter the positive arm).
    The decoys are given comparator-like (near-0) chronos so that if they leaked into the positive arm
    they'd blunt the delta — the test asserts they don't.
    """
    chronos, cn, tpm = {}, {}, {}
    i = 0
    for c in conjoint_chronos:
        m = f"ACH-{i:05d}"; chronos[m] = c; cn[m] = amp_cn; tpm[m] = high_tpm; i += 1
    for c in other_chronos:
        m = f"ACH-{i:05d}"; chronos[m] = c; cn[m] = neut_cn; tpm[m] = low_tpm; i += 1
    for _ in range(decoy_amp_lowexpr):
        m = f"ACH-{i:05d}"; chronos[m] = 0.0; cn[m] = amp_cn; tpm[m] = low_tpm; i += 1
    for _ in range(decoy_highexpr_neut):
        m = f"ACH-{i:05d}"; chronos[m] = 0.0; cn[m] = neut_cn; tpm[m] = high_tpm; i += 1
    return chronos, cn, tpm


def test_amplified_overexpressed_strongly_dependent():
    """Conjoint lines deeply dependent (~-1.2), rest ~0 → delta <= -0.5 + significant → strongly (KRAS live)."""
    import random
    rng = random.Random(0)
    conj = [-1.2 + rng.uniform(-0.1, 0.1) for _ in range(40)]
    other = [-0.05 + rng.uniform(-0.1, 0.1) for _ in range(300)]
    chronos, cn, tpm = _panel(conj, other)
    s = compute_amp_expr_stratification(chronos, cn, tpm)
    assert s["amp_expr_stratification_class"] == "amplified_overexpressed_strongly_dependent"
    assert s["delta_chronos_amp_expr_vs_rest"] <= -0.5
    assert s["n_amplified_overexpressed"] == 40
    assert s["amplification_threshold_relative_cn"] == FOCAL_AMP


def test_moderate_tier():
    """A modest but real separation (delta ~ -0.3) → moderately (ERBB2/MYC live)."""
    import random
    rng = random.Random(2)
    conj = [-0.35 + rng.uniform(-0.08, 0.08) for _ in range(50)]
    other = [-0.02 + rng.uniform(-0.08, 0.08) for _ in range(300)]
    chronos, cn, tpm = _panel(conj, other)
    s = compute_amp_expr_stratification(chronos, cn, tpm)
    assert s["amp_expr_stratification_class"] == "amplified_overexpressed_moderately_dependent"
    assert -0.5 < s["delta_chronos_amp_expr_vs_rest"] <= -0.2


def test_not_stratified_when_no_separation():
    """Conjoint + rest both near 0 → not_amp_expr_stratified (MET-live: amplified but not amp-addicted)."""
    import random
    rng = random.Random(1)
    conj = [-0.02 + rng.uniform(-0.08, 0.08) for _ in range(40)]
    other = [0.0 + rng.uniform(-0.08, 0.08) for _ in range(300)]
    chronos, cn, tpm = _panel(conj, other)
    s = compute_amp_expr_stratification(chronos, cn, tpm)
    assert s["amp_expr_stratification_class"] == "not_amp_expr_stratified"


def test_conjunction_gates_decoys_out():
    """THE CONJUNCTION TEST: amplified-but-low-expr and high-expr-but-neutral-CN lines must NOT enter the
    positive arm. With 40 true-conjoint dependent lines + 30 amp-low-expr decoys + 30 high-expr-neutral
    decoys (all decoys near-0 chronos), the positive arm must be exactly the 40 conjoint lines (decoys
    would blunt the delta if they leaked in)."""
    import random
    rng = random.Random(3)
    conj = [-1.0 + rng.uniform(-0.08, 0.08) for _ in range(40)]
    other = [-0.03 + rng.uniform(-0.08, 0.08) for _ in range(200)]
    chronos, cn, tpm = _panel(conj, other, decoy_amp_lowexpr=30, decoy_highexpr_neut=30)
    s = compute_amp_expr_stratification(chronos, cn, tpm)
    # positive arm is ONLY the true conjoint lines
    assert s["n_amplified_overexpressed"] == 40, "decoys leaked into the amplified∩overexpressed arm"
    assert s["amp_expr_stratification_class"] == "amplified_overexpressed_strongly_dependent"
    assert s["delta_chronos_amp_expr_vs_rest"] <= -0.5


def test_insufficient_conjoint_rate():
    """Fewer than min_conjoint (5) amplified+overexpressed lines → insufficient_amp_expr_rate."""
    conj = [-1.2, -1.1, -1.3]  # only 3 conjoint
    other = [0.0] * 300
    chronos, cn, tpm = _panel(conj, other)
    s = compute_amp_expr_stratification(chronos, cn, tpm)
    assert s["amp_expr_stratification_class"] == "insufficient_amp_expr_rate"


def test_negative_more_dependent_never_mislabeled():
    """Inverse: comparator strongly MORE dependent than the conjoint arm. Key guarantee — the conjunction
    is NEVER credited with a dependency it lacks — must hold: the FORWARD amplified_overexpressed_*_dependent
    classes must NOT fire. With the second-pass reverse test (gap #4) this strong inverse now correctly
    surfaces as `amp_expr_negative_more_dependent` (verdict-inert)."""
    import random
    rng = random.Random(4)
    conj = [-0.02 + rng.uniform(-0.08, 0.08) for _ in range(40)]
    other = [-0.6 + rng.uniform(-0.1, 0.1) for _ in range(300)]
    chronos, cn, tpm = _panel(conj, other)
    s = compute_amp_expr_stratification(chronos, cn, tpm)
    assert s["amp_expr_stratification_class"] not in ("amplified_overexpressed_strongly_dependent",
                                                      "amplified_overexpressed_moderately_dependent")
    assert s["amp_expr_stratification_class"] == "amp_expr_negative_more_dependent"
    assert s["amp_expr_mannwhitney_q_reverse"] < 0.05
    assert s["delta_chronos_amp_expr_vs_rest"] > 0
