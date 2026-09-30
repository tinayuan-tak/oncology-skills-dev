"""expression_purity_confound (Q9) pure classifier — no S3."""

from __future__ import annotations

from onc_methods.expression_purity_confound.read import (
    CONFOUND_R,
    INTRINSIC_R,
    MIN_PAIRED_SAMPLES,
    MIN_PURITY_IQR,
    classify_purity_confound,
    is_purity_spread_underpowered,
    purity_spread_iqr,
)


def test_positive_significant_is_tumor_intrinsic():
    # expression rises with tumor purity → cancer-cell-intrinsic signal
    assert classify_purity_confound(0.5, 0.001, 200) == "tumor_intrinsic"
    assert classify_purity_confound(INTRINSIC_R, 0.01, 100) == "tumor_intrinsic"


def test_negative_significant_is_microenvironment_confounded():
    # expression higher in LOW-purity tumors → stromal/immune-derived confound
    assert classify_purity_confound(-0.5, 0.0001, 200) == "microenvironment_confounded"
    assert classify_purity_confound(CONFOUND_R, 0.02, 100) == "microenvironment_confounded"


def test_significant_but_weak_is_purity_independent():
    # significant p but |r| below the direction thresholds → no confound call
    assert classify_purity_confound(0.1, 0.001, 300) == "purity_independent"
    assert classify_purity_confound(-0.15, 0.001, 300) == "purity_independent"


def test_strong_but_insignificant_is_purity_independent():
    # strong r but p above alpha → not a confident direction call
    assert classify_purity_confound(0.5, 0.5, 40) == "purity_independent"


def test_underpowered_is_insufficient():
    assert classify_purity_confound(0.9, 0.0001, MIN_PAIRED_SAMPLES - 1) == "insufficient_paired_samples"
    assert classify_purity_confound(None, None, 5) == "insufficient_paired_samples"


def test_none_r_with_enough_samples_is_data_unavailable():
    assert classify_purity_confound(None, None, 200) == "data_unavailable"


# --- purity-SPREAD power gate ---------------------------------------------------------------
# Fixtures store the RAW paired ABSOLUTE purity vectors (not a pre-computed IQR), so the test
# re-derives the qualifier and can genuinely fail if the derivation regresses.

# A narrow high-purity band (an ACC/KICH/UCS-like small, high-purity cohort: values tightly
# concentrated near 0.85). The design cannot resolve a purity confound here.
_NARROW_HIGH_PURITY = [
    0.80,
    0.82,
    0.83,
    0.84,
    0.84,
    0.85,
    0.85,
    0.86,
    0.86,
    0.87,
    0.87,
    0.88,
    0.88,
    0.89,
    0.90,
    0.83,
    0.86,
    0.84,
    0.88,
    0.85,
]
# A wide band spanning low-to-high purity (a BLCA/PAAD-like cohort) — a confound IS resolvable.
_WIDE_PURITY = [
    0.20,
    0.30,
    0.35,
    0.42,
    0.48,
    0.52,
    0.55,
    0.60,
    0.62,
    0.68,
    0.70,
    0.72,
    0.75,
    0.78,
    0.80,
    0.25,
    0.45,
    0.58,
    0.65,
    0.85,
]


def _manual_iqr(vals):
    import numpy as np

    q25, q75 = np.percentile(np.asarray(vals, dtype=float), [25, 75])
    return float(q75 - q25)


def test_narrow_band_iqr_is_below_threshold_and_underpowered():
    iqr = purity_spread_iqr(_NARROW_HIGH_PURITY)
    assert iqr == _manual_iqr(_NARROW_HIGH_PURITY)  # re-derived, not a stored constant
    assert iqr < MIN_PURITY_IQR
    assert is_purity_spread_underpowered(iqr) is True


def test_wide_band_grades_cleanly_not_underpowered():
    iqr = purity_spread_iqr(_WIDE_PURITY)
    assert iqr == _manual_iqr(_WIDE_PURITY)
    assert iqr >= MIN_PURITY_IQR
    assert is_purity_spread_underpowered(iqr) is False


def test_iqr_undefined_below_two_values_and_not_flagged():
    # degenerate spread → None (routed to data_unavailable upstream by the variance guard),
    # and None must NOT be treated as under-powered.
    assert purity_spread_iqr([0.7]) is None
    assert purity_spread_iqr([]) is None
    assert is_purity_spread_underpowered(None) is False


def test_iqr_ignores_nonfinite_values():
    import math

    with_nan = _NARROW_HIGH_PURITY + [float("nan"), math.inf]
    assert purity_spread_iqr(with_nan) == _manual_iqr(_NARROW_HIGH_PURITY)
