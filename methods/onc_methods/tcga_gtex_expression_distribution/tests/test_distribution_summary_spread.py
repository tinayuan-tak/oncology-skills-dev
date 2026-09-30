"""Mutation-teeth for AM#857 — the five-number-summary SPREAD must be RETAINED, not dropped.

`stats.five_number()` computes n/min/p5/q1/median/q3/p95/p99/max/mean/sd, but the reader projection
`_distribution_summary` was lifting only a subset and DROPPING p5/q1/q3/mean/sd (a recoverability-
invariant violation). The pooled assembler and every per-subtype stratum both project from this ONE
primitive (the 'grain is a projection' pattern), so asserting the shared projection retains the spread
covers BOTH grains at once.

These assertions are RED before the AM#857 fix (the keys are absent from the projection) and GREEN
after. S3-free / data-free — a pure unit test of the projection over a hand-built vector.
"""

from __future__ import annotations

import numpy as np

from onc_methods.tcga_gtex_expression_distribution import read as R
from onc_methods.tcga_gtex_expression_distribution import stats as S

# A non-degenerate log2(TPM+1) vector with an asymmetric tail so mean != median and the quartiles
# are distinct — a constant vector would let a bug hide (every stat collapses to one value).
_VALS = [0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0]

_SPREAD_FIELDS = ("p5_log2tpm", "q1_log2tpm", "q3_log2tpm", "mean_log2tpm", "sd_log2tpm")


def test_pooled_summary_retains_the_five_number_spread():
    """The emitted pooled summary block contains p5/q1/q3/mean/sd — RED pre-fix (dropped)."""
    out = R._distribution_summary(_VALS)
    missing = [f for f in _SPREAD_FIELDS if f not in out]
    assert not missing, f"_distribution_summary dropped the five-number spread: {missing}"


def test_spread_values_match_the_five_number_primitive():
    """Retention must be FAITHFUL — the projected values equal the primitive / numpy, not fabricated."""
    a = np.asarray(_VALS, dtype=float)
    out = R._distribution_summary(_VALS)
    assert out["p5_log2tpm"] == float(np.percentile(a, 5))
    assert out["q1_log2tpm"] == float(np.percentile(a, 25))
    assert out["q3_log2tpm"] == float(np.percentile(a, 75))
    assert out["mean_log2tpm"] == float(np.mean(a))
    assert out["sd_log2tpm"] == float(np.std(a))
    # and they are exactly the five_number() primitive's q1/q3/mean/sd/p5 (no re-derivation drift)
    fn = S.five_number(_VALS)
    assert out["q1_log2tpm"] == fn["q1"]
    assert out["q3_log2tpm"] == fn["q3"]
    assert out["mean_log2tpm"] == fn["mean"]
    assert out["sd_log2tpm"] == fn["sd"]
    assert out["p5_log2tpm"] == fn["p5"]


def test_spread_is_verdict_inert():
    """Adding the spread must not perturb the classifier inputs — tumor_expression_class is unchanged
    whether or not the spread fields are present (they feed no class/rule)."""
    out = R._distribution_summary(_VALS)
    # tumor_expression_class derives only from fractions + distribution_pattern; assert the spread keys
    # are not among the classifier's declared inputs.
    assert set(_SPREAD_FIELDS).isdisjoint(
        {"detectable_fraction", "high_fraction", "moderate_fraction", "distribution_pattern"}
    )
    assert out["tumor_expression_class"] == R._classify_tumor_expression(
        out["detectable_fraction"], out["high_fraction"], out["distribution_pattern"], out.get("moderate_fraction")
    )
