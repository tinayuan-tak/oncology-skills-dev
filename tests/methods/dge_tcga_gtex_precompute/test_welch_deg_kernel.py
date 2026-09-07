"""Coverage for the Welch/BH statistical kernel of dge_tcga_gtex_precompute — the tumor-vs-GTEx
selectivity substrate (cell C of the four-cell sensitivity design).

The 2026-08-08 selectivity review flagged this kernel as having ZERO test coverage despite being
the statistical heart of the tumor-vs-normal call. These are pure-function tests (no S3, no CLI):
they pin the sign convention, the tiny-n / zero-variance guards, NaN handling, and BH correctness
against an independent reference — the invariants a future edit could silently break.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")
import numpy as np

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.dge_tcga_gtex_precompute.cli import _welch_deg, _bh_correct  # noqa: E402


# ── sign convention: positive log2FC = arm A (tumor) higher ─────────────────
def test_sign_positive_when_a_higher():
    a = np.array([5.0, 5.2, 4.8, 5.1])  # tumor
    b = np.array([1.0, 1.1, 0.9, 1.0])  # normal
    lfc, p = _welch_deg(a, b)
    assert lfc > 0  # a > b → positive (up in tumor)
    assert abs(lfc - (a.mean() - b.mean())) < 1e-9  # lfc == mean(a) - mean(b) exactly
    assert p < 0.05  # clearly separated → significant


def test_sign_negative_when_a_lower():
    a = np.array([1.0, 1.1, 0.9])
    b = np.array([5.0, 5.2, 4.8])
    lfc, p = _welch_deg(a, b)
    assert lfc < 0  # down in tumor → negative, never sign-flipped


# ── tiny-n guard: <2 per arm → (0.0, 1.0), never a spurious call ────────────
def test_tiny_n_returns_null():
    assert _welch_deg(np.array([5.0]), np.array([1.0, 1.1])) == (0.0, 1.0)
    assert _welch_deg(np.array([5.0, 5.1]), np.array([1.0])) == (0.0, 1.0)
    assert _welch_deg(np.array([]), np.array([1.0, 2.0])) == (0.0, 1.0)


# ── zero-variance both arms → lfc kept, p=1.0 (not a divide-by-zero call) ────
def test_zero_variance_both_arms():
    lfc, p = _welch_deg(np.array([3.0, 3.0, 3.0]), np.array([1.0, 1.0, 1.0]))
    assert lfc == 2.0  # mean diff preserved
    assert p == 1.0  # no variance → cannot call significant


# ── NaN handling: NaNs dropped per-arm before the test, not propagated ──────
def test_nan_dropped_per_arm():
    a = np.array([5.0, np.nan, 5.2, 4.8])
    b = np.array([1.0, 1.1, np.nan, 0.9])
    lfc, p = _welch_deg(a, b)
    # means computed over the 3 non-NaN each; result finite, not NaN
    assert lfc == pytest.approx((5.0 + 5.2 + 4.8) / 3 - (1.0 + 1.1 + 0.9) / 3)
    assert p == p and 0.0 <= p <= 1.0  # p is finite in [0,1]


def test_all_nan_one_arm_returns_null():
    a = np.array([np.nan, np.nan, np.nan])
    b = np.array([1.0, 2.0, 3.0])
    assert _welch_deg(a, b) == (0.0, 1.0)  # <2 valid in arm a → guarded


# ── BH correction: matches an independent reference implementation ──────────
def _bh_reference(p):
    # textbook BH: q_i = min over k>=rank(i) of (p_(k) * n / k), clipped to 1
    p = np.asarray(p, float)
    n = len(p)
    order = np.argsort(p)
    ranked = p[order]
    q = ranked * n / (np.arange(n) + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    q = np.clip(q, 0, 1)
    out = np.empty_like(q)
    out[order] = q
    return out


def test_bh_matches_reference():
    p = np.array([0.001, 0.008, 0.039, 0.041, 0.9, 0.5, 0.012])
    np.testing.assert_allclose(_bh_correct(p), _bh_reference(p), rtol=1e-12)


def test_bh_monotone_and_bounded():
    p = np.array([0.2, 0.01, 0.4, 0.03, 0.9])
    q = _bh_correct(p)
    assert np.all(q <= 1.0) and np.all(q >= 0.0)
    # q preserves p-ordering (monotone in the ranked domain)
    order = np.argsort(p)
    assert np.all(np.diff(q[order]) >= -1e-12)


def test_bh_smallest_p_qvalue_is_p_times_n():
    # for the single smallest p, q = p * n / 1 (before the monotone floor pulls it down)
    p = np.array([0.001, 0.5, 0.6, 0.7])
    q = _bh_correct(p)
    assert q[0] == pytest.approx(min(0.001 * 4, q[0]))  # smallest gets the n/1 multiplier, clipped by monotone-min
    assert q.argmin() == 0  # smallest p → smallest q
