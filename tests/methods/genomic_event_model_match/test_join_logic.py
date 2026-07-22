"""genomic_event_model_match (M11) pure join logic — no S3 (dict fixtures)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.genomic_event_model_match.read import (  # noqa: E402
    _patient_dominant_event, _screen_role, _classify_event_correspondence,
)


# ── patient dominant event ───────────────────────────────────────────────────
def test_recurrent_biallelic_is_the_event():
    arm = {"n_samples": 100, "state_counts": {"biallelic-genetic": 45, "monoallelic": 20,
                                              "wt": 30, "uncertain": 5}}
    ev, frac = _patient_dominant_event(arm)
    assert ev == "biallelic-genetic"
    assert frac == pytest.approx(0.45)


def test_biallelic_precedence_over_monoallelic():
    # both clear the 10% floor → biallelic wins (stronger, more specific two-hit event)
    arm = {"n_samples": 100, "state_counts": {"biallelic-genetic": 12, "monoallelic": 50,
                                              "wt": 38, "uncertain": 0}}
    ev, _ = _patient_dominant_event(arm)
    assert ev == "biallelic-genetic"


def test_monoallelic_when_biallelic_below_floor():
    # activating-oncogene shape: monoallelic recurrent, biallelic negligible
    arm = {"n_samples": 100, "state_counts": {"biallelic-genetic": 2, "monoallelic": 40,
                                              "wt": 58, "uncertain": 0}}
    ev, frac = _patient_dominant_event(arm)
    assert ev == "monoallelic"
    assert frac == pytest.approx(0.40)


def test_no_recurrent_event_when_mostly_wt():
    arm = {"n_samples": 100, "state_counts": {"biallelic-genetic": 3, "monoallelic": 4,
                                              "wt": 90, "uncertain": 3}}
    ev, frac = _patient_dominant_event(arm)
    assert ev is None and frac is None


def test_empty_patient_arm():
    assert _patient_dominant_event({}) == (None, None)
    assert _patient_dominant_event({"n_samples": 0, "state_counts": {}}) == (None, None)


# ── screen role from Chronos ─────────────────────────────────────────────────
def test_screen_role_thresholds():
    assert _screen_role(-0.8) == "positive_model"      # dependent
    assert _screen_role(-0.5) == "positive_model"      # boundary
    assert _screen_role(-0.1) == "resistance_model"    # not dependent
    assert _screen_role(-0.3) == "indeterminate"       # intermediate
    assert _screen_role(None) == "indeterminate"       # missing


# ── event correspondence rollup ──────────────────────────────────────────────
def test_correspondence_matched_dependent_in_lineage():
    assert _classify_event_correspondence(
        n_matched=5, n_matched_dependent=3, n_matched_dep_lineage=1, has_lineage=True
    ) == "event_matched_dependent_in_lineage"


def test_correspondence_matched_dependent_off_lineage():
    assert _classify_event_correspondence(
        n_matched=5, n_matched_dependent=3, n_matched_dep_lineage=0, has_lineage=True
    ) == "event_matched_dependent_off_lineage"
    # no lineage defined at all → off-lineage bucket
    assert _classify_event_correspondence(
        n_matched=5, n_matched_dependent=3, n_matched_dep_lineage=0, has_lineage=False
    ) == "event_matched_dependent_off_lineage"


def test_correspondence_matched_not_dependent():
    assert _classify_event_correspondence(
        n_matched=4, n_matched_dependent=0, n_matched_dep_lineage=0, has_lineage=True
    ) == "event_matched_not_dependent"


def test_correspondence_no_event_match():
    assert _classify_event_correspondence(
        n_matched=0, n_matched_dependent=0, n_matched_dep_lineage=0, has_lineage=True
    ) == "no_event_match"
