"""Regression (burndown P3, PR #361): the tcga_aneuploidy_burden S3-direct loaders must PROPAGATE a
transient / broken-env / creds failure (honest _live_read_error at the live-read seam) rather than
mask it as an empty result -- while a GENUINE NoSuchKey/404 still yields today's empty (verdict-inert
absence), unchanged. Representative of the six loaders fixed in #361 (all read directly via
_s3_read_bytes -> is_definitively_absent(+FileNotFoundError) discipline).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.tcga_aneuploidy_burden import read as anu  # noqa: E402


def _nosuchkey():
    return ClientError({"Error": {"Code": "NoSuchKey", "Message": "x"}}, "GetObject")


def _raise(exc):
    def f(*a, **k):
        raise exc
    return f


def test_load_absolute_transient_reraises(monkeypatch):
    anu._load_absolute.cache_clear()
    monkeypatch.setattr(anu, "_s3_read_bytes", _raise(RuntimeError("throttle / expired creds")))
    with pytest.raises(RuntimeError):
        anu._load_absolute()
    anu._load_absolute.cache_clear()


def test_load_absolute_genuine_absence_returns_empty(monkeypatch):
    anu._load_absolute.cache_clear()
    monkeypatch.setattr(anu, "_s3_read_bytes", _raise(_nosuchkey()))
    assert anu._load_absolute().empty          # genuine 404 -> honest empty (unchanged)
    anu._load_absolute.cache_clear()


def test_load_msi_labels_transient_reraises(monkeypatch):
    anu._load_msi_labels.cache_clear()
    monkeypatch.setattr(anu, "_s3_read_bytes", _raise(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        anu._load_msi_labels("some/key.csv", "MSI_status")
    anu._load_msi_labels.cache_clear()


def test_load_msi_labels_genuine_absence_returns_empty(monkeypatch):
    anu._load_msi_labels.cache_clear()
    monkeypatch.setattr(anu, "_s3_read_bytes", _raise(_nosuchkey()))
    assert anu._load_msi_labels("some/key.csv", "MSI_status") == tuple()
    anu._load_msi_labels.cache_clear()
