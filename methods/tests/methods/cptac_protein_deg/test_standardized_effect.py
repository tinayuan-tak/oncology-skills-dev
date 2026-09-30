"""Variance-standardized CPTAC effect (2026-08-20). The protein_expression_class thresholds on the RAW
log2 effect_size (+/-0.5 / +/-1.5), blind to variance — so a statistically-significant `modest_up` on a
large cohort with a small per-sample separation is indistinguishable from a genuinely large-effect one.
_standardized_effect adds the variance-aware companion: exact logFC/SE when the (rebuilt) product carries
SE, else a p-value z-score approximation, plus a sample-size-independent Cohen's d + class. Pure math.
"""

from __future__ import annotations

import math

from onc_methods.cptac_protein_deg.read import _cohens_d_class, _standardized_effect


def test_exact_moderated_se_path():
    """SE present → exact standardized t = logFC/SE, method flagged exact."""
    r = _standardized_effect(effect_size=1.0, p_value=0.01, se=0.5, n_tumor=100, n_normal=100)
    assert r["protein_effect_standardized_method"] == "moderated_se_exact"
    assert r["protein_effect_standardized_t"] == 2.0
    assert r["protein_effect_size_se"] == 0.5
    # n_eff = 50 → d = 2/sqrt(50) ≈ 0.283 → small
    assert math.isclose(r["protein_effect_cohens_d"], 2.0 / math.sqrt(50.0), abs_tol=1e-3)
    assert r["protein_effect_standardized_class"] == "small"


def test_pvalue_approx_when_no_se():
    """No SE (pre-rebuild product) → recover |z| from the two-sided p; sign from the effect."""
    r = _standardized_effect(effect_size=0.5, p_value=0.05, se=None, n_tumor=100, n_normal=100)
    assert r["protein_effect_standardized_method"] == "pvalue_zscore_approx"
    assert math.isclose(r["protein_effect_standardized_t"], 1.9600, abs_tol=1e-3)  # z_{0.975}
    assert r["protein_effect_size_se"] is None


def test_negative_effect_keeps_sign():
    r = _standardized_effect(effect_size=-0.8, p_value=0.001, se=None, n_tumor=50, n_normal=50)
    assert r["protein_effect_standardized_t"] < 0


def test_se_preferred_over_pvalue_when_both_present():
    r = _standardized_effect(effect_size=1.0, p_value=0.5, se=0.25, n_tumor=80, n_normal=80)
    assert r["protein_effect_standardized_method"] == "moderated_se_exact"
    assert r["protein_effect_standardized_t"] == 4.0


def test_significant_but_small_standardized_effect_is_distinguished():
    """The core payoff: two SAME raw-logFC (0.6, both `modest_up`) reads — one on a huge cohort with a
    tiny p, one on a modest cohort — differ in Cohen's d. The standardized class exposes when a modest_up
    rests on a small per-sample effect that only cleared significance via n."""
    huge_n = _standardized_effect(0.6, p_value=1e-12, se=None, n_tumor=600, n_normal=600)
    modest_n = _standardized_effect(0.6, p_value=0.02, se=None, n_tumor=40, n_normal=40)
    # same raw logFC, different standardized effect size (d) — the point of the field
    assert huge_n["protein_effect_cohens_d"] != modest_n["protein_effect_cohens_d"]
    # both are recovered via the p-value approximation
    assert huge_n["protein_effect_standardized_method"] == "pvalue_zscore_approx"


def test_data_unavailable_paths():
    assert _standardized_effect(None, 0.01, 0.5, 100, 100)["protein_effect_standardized_class"] == "data_unavailable"
    # no SE and no usable p → cannot standardize
    r = _standardized_effect(0.5, None, None, 100, 100)
    assert r["protein_effect_standardized_t"] is None
    assert r["protein_effect_standardized_method"] == "data_unavailable"
    # standardized t computable but n missing → class stays data_unavailable (d needs n)
    r2 = _standardized_effect(0.5, 0.05, None, None, None)
    assert r2["protein_effect_standardized_t"] is not None
    assert r2["protein_effect_cohens_d"] is None
    assert r2["protein_effect_standardized_class"] == "data_unavailable"


def test_nan_effect_and_p_floor():
    assert (
        _standardized_effect(float("nan"), 0.01, None, 10, 10)["protein_effect_standardized_method"]
        == "data_unavailable"
    )
    # p == 0 must not blow up (floored) — yields a large finite t
    r = _standardized_effect(1.0, 0.0, None, 100, 100)
    assert r["protein_effect_standardized_t"] is not None and math.isfinite(r["protein_effect_standardized_t"])


def test_cohens_d_class_bands():
    assert _cohens_d_class(0.05) == "negligible"
    assert _cohens_d_class(0.3) == "small"
    assert _cohens_d_class(0.6) == "medium"
    assert _cohens_d_class(1.2) == "large"
