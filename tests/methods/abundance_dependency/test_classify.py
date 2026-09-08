"""abundance_dependency (Q7) pure classifier — no S3."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.abundance_dependency.read import (  # noqa: E402
    MIN_PAIRED_MODELS,
    STRONG_R,
    WEAK_R,
    classify_abundance_dependency,
)


def test_strong_negative_significant_predicts_dependency():
    # high protein → dependent (low Chronos) = strong negative r, significant
    assert classify_abundance_dependency(-0.55, 0.001, 60) == "protein_predicts_dependency"
    assert classify_abundance_dependency(STRONG_R, 0.01, 40) == "protein_predicts_dependency"


def test_strong_negative_but_insignificant_is_weak():
    # strong r but p above alpha → not a confident predict call
    assert classify_abundance_dependency(-0.5, 0.20, 40) == "weak_protein_dependency_link"


def test_moderate_negative_is_weak_link():
    assert classify_abundance_dependency(-0.3, 0.01, 50) == "weak_protein_dependency_link"
    assert classify_abundance_dependency(WEAK_R, 0.01, 50) == "weak_protein_dependency_link"


def test_near_zero_or_positive_is_no_link():
    assert classify_abundance_dependency(-0.05, 0.5, 50) == "no_protein_dependency_link"
    assert classify_abundance_dependency(0.3, 0.01, 50) == "no_protein_dependency_link"


def test_underpowered_is_insufficient():
    assert classify_abundance_dependency(-0.9, 0.0001, MIN_PAIRED_MODELS - 1) == "insufficient_paired_models"
    assert classify_abundance_dependency(None, None, 5) == "insufficient_paired_models"


def test_none_r_with_enough_models_is_data_unavailable():
    assert classify_abundance_dependency(None, None, 50) == "data_unavailable"
