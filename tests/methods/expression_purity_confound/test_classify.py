"""expression_purity_confound (Q9) pure classifier — no S3."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.expression_purity_confound.read import (  # noqa: E402
    classify_purity_confound,
    MIN_PAIRED_SAMPLES,
    INTRINSIC_R,
    CONFOUND_R,
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
