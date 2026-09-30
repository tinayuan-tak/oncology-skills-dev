"""expression_clinical_association (Q11) — pure classifier + a log-rank numerical check. No S3."""

from __future__ import annotations

import pytest

from onc_methods.expression_clinical_association import read as _R
from onc_methods.expression_clinical_association.read import (
    MIN_EVENTS,
    MIN_PER_ARM,
    _logrank,
    classify_survival_association,
)

np = pytest.importorskip("numpy")


# ── broken-env regression (2026-08-05): a MISSING DEPENDENCY (openpyxl) must NOT read as a
#    data gap. Before the fix, `except: return {}` in _load_cdr masked ImportError → every
#    target read survival_association_class=data_unavailable framework-wide, silently. ──────
def test_load_cdr_raises_on_missing_dependency_not_silent(monkeypatch):
    # _load_cdr must RAISE ImportError (broken env) rather than swallow it into an empty {}
    # that reads as a data gap. S3 fetch succeeds; the .xlsx parse hits a missing openpyxl.
    _R._load_cdr.cache_clear()
    monkeypatch.setattr(
        _R,
        "_boto3",
        lambda: type(
            "S", (), {"get_object": lambda self, Bucket, Key: {"Body": type("B", (), {"read": lambda self: b"x"})()}}
        )(),
    )
    import pandas as pd

    def _raise_import(*a, **k):
        raise ImportError("Missing optional dependency 'openpyxl'.")

    monkeypatch.setattr(pd, "read_excel", _raise_import)
    with pytest.raises(ImportError):
        _R._load_cdr()
    # and the reason is recorded for the caller to surface (dependency, not "table unavailable")
    assert _R._CDR_LOAD_ERROR and "dependency" in _R._CDR_LOAD_ERROR.lower()
    _R._load_cdr.cache_clear()


def test_load_cdr_genuine_s3_absence_is_graceful_empty(monkeypatch):
    # a GENUINE absence (botocore NoSuchKey/404) stays a graceful {} with a distinct note (NOT raised)
    from botocore.exceptions import ClientError

    _R._load_cdr.cache_clear()

    def _nosuchkey(*a, **k):
        raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "x"}}, "GetObject")

    monkeypatch.setattr(
        _R,
        "_boto3",
        lambda: type("S", (), {"get_object": staticmethod(_nosuchkey)})(),
    )
    assert _R._load_cdr() == {}
    assert _R._CDR_LOAD_ERROR and "unreachable" in _R._CDR_LOAD_ERROR.lower()
    _R._load_cdr.cache_clear()


def test_load_cdr_transient_s3_fault_raises_not_masked(monkeypatch):
    # AM#776: a TRANSIENT/creds/broken-env S3 fault is NOT a data gap. Before the fix, the bare
    # `except Exception: return {}` re-masked it into an empty {} that reads as survival
    # data_unavailable framework-wide. It must now PROPAGATE (fail-loud), not fake a honest-negative.
    from botocore.exceptions import ClientError

    _R._load_cdr.cache_clear()

    def _throttle(*a, **k):
        raise ClientError({"Error": {"Code": "SlowDown", "Message": "throttle"}}, "GetObject")

    monkeypatch.setattr(
        _R,
        "_boto3",
        lambda: type("S", (), {"get_object": staticmethod(_throttle)})(),
    )
    with pytest.raises(ClientError):
        _R._load_cdr()
    _R._load_cdr.cache_clear()


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
    assert direction == 1  # group A (early deaths) has more hazard


def test_logrank_censoring_handled():
    # censored observations (event=0) must not count as deaths
    a_t = np.array([10, 20, 30, 40], dtype=float)
    a_e = np.array([0, 0, 0, 0], dtype=int)  # all censored → no events in A
    b_t = np.array([5, 6, 7, 8], dtype=float)
    b_e = np.array([1, 1, 1, 1], dtype=int)  # all events in B
    chi2, p, direction = _logrank(a_t, a_e, b_t, b_e)
    # B has all the hazard → group A direction should be -1 (less hazard)
    assert direction == -1
