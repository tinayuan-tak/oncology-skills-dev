"""expression_clinical_association (Q11) — pure classifier + a log-rank numerical check. No S3."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.expression_clinical_association.read import (  # noqa: E402
    classify_survival_association, _logrank, MIN_EVENTS, MIN_PER_ARM,
)

np = pytest.importorskip("numpy")


# ── classifier ───────────────────────────────────────────────────────────────
def test_significant_high_worse():
    assert classify_survival_association(0.01, 1, 50, 40, 40) == "expression_high_worse_survival"


def test_significant_high_better():
    assert classify_survival_association(0.01, -1, 50, 40, 40) == "expression_high_better_survival"


def test_insignificant_is_no_association():
    assert classify_survival_association(0.4, 1, 50, 40, 40) == "no_survival_association"


def test_too_few_events_insufficient():
    assert classify_survival_association(0.001, 1, MIN_EVENTS - 1, 40, 40) == "insufficient_survival_data"


def test_small_arm_insufficient():
    assert classify_survival_association(0.001, 1, 50, MIN_PER_ARM - 1, 40) == "insufficient_survival_data"


# ── log-rank numerical check ─────────────────────────────────────────────────
def test_logrank_identical_groups_null():
    # two identical groups → no difference → p ~ 1, direction 0
    t = np.array([5, 10, 15, 20, 25, 30], dtype=float)
    e = np.array([1, 1, 1, 1, 1, 1], dtype=int)
    chi2, p, direction = _logrank(t, e, t.copy(), e.copy())
    assert p > 0.5
    assert abs(chi2) < 1.0


def test_logrank_separated_groups_significant():
    # group A dies early, group B late → strong separation, A has MORE hazard (+1)
    a_t = np.array([1, 2, 3, 4, 5, 6, 7, 8], dtype=float)
    a_e = np.ones(8, dtype=int)
    b_t = np.array([50, 55, 60, 65, 70, 75, 80, 85], dtype=float)
    b_e = np.ones(8, dtype=int)
    chi2, p, direction = _logrank(a_t, a_e, b_t, b_e)
    assert p < 0.01
    assert direction == 1          # group A (early deaths) has more hazard


def test_logrank_censoring_handled():
    # censored observations (event=0) must not count as deaths
    a_t = np.array([10, 20, 30, 40], dtype=float)
    a_e = np.array([0, 0, 0, 0], dtype=int)   # all censored → no events in A
    b_t = np.array([5, 6, 7, 8], dtype=float)
    b_e = np.array([1, 1, 1, 1], dtype=int)   # all events in B
    chi2, p, direction = _logrank(a_t, a_e, b_t, b_e)
    # B has all the hazard → group A direction should be -1 (less hazard)
    assert direction == -1
