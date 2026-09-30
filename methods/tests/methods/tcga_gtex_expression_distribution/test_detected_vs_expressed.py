"""Regression (tumor-presence expert review, finding G4): "detected at TPM≈1" must not inherit the
broadly-EXPRESSED (tier-3 presence-positive) class.

Bug: `_classify_tumor_expression` returned `broadly_detected` on `detectable_fraction >= 0.7` (TPM>=1 in
>=70% of tumors) regardless of expression LEVEL. `broadly_detected` maps (via the tumor-expression rule)
to the `tumor_broadly_expressed` presence-positive rung, which the tumor-presence ladder re-anchors above
the cell-line proxy and which drives the surface/ADC/degrader reads this signal informs. So a gene at
TPM 1-3 in 75% of tumors — transcriptional background — got the SAME positive word as a TPM-50 gene.

Fix: `broadly_detected` now also requires the target to reach a MODERATE level (TPM≈10) in
>= BROADLY_DETECTED_MODERATE_FRACTION_MIN of tumors; otherwise it drops to `broadly_moderate` (the
tier-2 NEUTRAL `tumor_moderately_expressed` rung — present, but not a top-tier positive). A legacy
caller passing moderate_fraction=None keeps the historical detection-only label.
"""

from __future__ import annotations

import pytest

pytest.importorskip("numpy")


from onc_methods.tcga_gtex_expression_distribution import read as R

_MIN = R.BROADLY_DETECTED_MODERATE_FRACTION_MIN


def test_detected_but_background_level_is_broadly_moderate_not_expressed():
    # TPM≈1 background: detected in 80% of tumors but almost never reaches TPM≈10 → broadly_moderate,
    # NOT broadly_detected (would have inherited tumor_broadly_expressed).
    cls = R._classify_tumor_expression(
        detectable_fraction=0.80, high_fraction=0.0, pattern="unimodal", moderate_fraction=0.05
    )
    assert cls == "broadly_moderate"


def test_detected_and_moderately_expressed_is_broadly_detected():
    # detected broadly AND reaches TPM≈10 in a real share of tumors → the genuine broadly_detected.
    cls = R._classify_tumor_expression(
        detectable_fraction=0.80, high_fraction=0.0, pattern="unimodal", moderate_fraction=0.70
    )
    assert cls == "broadly_detected"


def test_moderate_fraction_boundary():
    at = R._classify_tumor_expression(0.80, 0.0, "unimodal", moderate_fraction=_MIN)
    below = R._classify_tumor_expression(0.80, 0.0, "unimodal", moderate_fraction=_MIN - 0.01)
    assert at == "broadly_detected"
    assert below == "broadly_moderate"


def test_legacy_none_moderate_fraction_preserves_broadly_detected():
    # no moderate_fraction supplied (legacy caller / unit test) → historical detection-only label.
    cls = R._classify_tumor_expression(0.80, 0.0, "unimodal", moderate_fraction=None)
    assert cls == "broadly_detected"


def test_broadly_high_and_subset_high_unaffected_by_level_gate():
    # high_fraction wins first regardless of moderate_fraction
    assert R._classify_tumor_expression(0.9, 0.6, "unimodal", moderate_fraction=0.0) == "broadly_high"
    # subset_high (bimodal with a real high minority) also precedes the broadly_detected branch
    assert R._classify_tumor_expression(0.9, 0.2, "bimodal", moderate_fraction=0.0) == "subset_high"


def test_low_detection_still_broadly_low():
    assert R._classify_tumor_expression(0.2, 0.0, "unimodal", moderate_fraction=0.0) == "broadly_low"
