"""shet_selection.classify_shet + compute_summary — hermetic (no S3)."""

from __future__ import annotations

from onc_methods.shet_selection.cli import (
    HIGH_INTOLERANCE,
    MODERATE_INTOLERANCE,
    classify_shet,
    compute_summary,
)


def test_classify_bands():
    assert classify_shet(0.463) == "high_intolerance"  # ARID1A
    assert classify_shet(0.1) == "high_intolerance"  # boundary inclusive
    assert classify_shet(0.079) == "moderate_intolerance"  # TP53
    assert classify_shet(0.01) == "moderate_intolerance"  # boundary inclusive
    assert classify_shet(0.005) == "tolerant"  # BRCA1
    assert classify_shet(None) == "indeterminate"  # gene absent


def test_thresholds_pinned():
    assert HIGH_INTOLERANCE == 0.1 and MODERATE_INTOLERANCE == 0.01


def test_summary_from_row():
    s = compute_summary(
        {"shet": 0.265, "shet_lower_95": 0.2, "shet_upper_95": 0.33, "obs_lof": 5.0, "exp_lof": 40.0}, "KRAS"
    )
    assert s["shet_class"] == "high_intolerance"
    assert s["shet_score"] == 0.265
    assert s["obs_lof_count"] == 5.0 and s["exp_lof_count"] == 40.0
    assert "s_het" in s["shet_context"]


def test_summary_absent_is_indeterminate():
    s = compute_summary(None, "ZZZ")
    assert s["shet_class"] == "indeterminate"
    assert s["shet_score"] is None
