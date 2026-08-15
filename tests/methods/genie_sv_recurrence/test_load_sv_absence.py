"""Regression (burndown P2): genie_sv_recurrence._load_sv splits genuine NoSuchKey/404 (-> None ->
data_unavailable, unchanged) from transient/broken-env failure (-> re-raise -> _live_read_error).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.genie_sv_recurrence import read as gsv  # noqa: E402


def _nosuchkey():
    return ClientError({"Error": {"Code": "NoSuchKey", "Message": "x"}}, "GetObject")


class _FakeS3:
    def __init__(self, exc):
        self.exc = exc

    def get_object(self, **k):
        raise self.exc


def test_load_sv_transient_reraises(monkeypatch):
    gsv._load_sv.cache_clear()
    monkeypatch.setattr(gsv, "_boto3_client", lambda: _FakeS3(RuntimeError("throttle")))
    with pytest.raises(RuntimeError):
        gsv._load_sv()
    gsv._load_sv.cache_clear()


def test_load_sv_genuine_absence_none(monkeypatch):
    gsv._load_sv.cache_clear()
    monkeypatch.setattr(gsv, "_boto3_client", lambda: _FakeS3(_nosuchkey()))
    assert gsv._load_sv() is None
    gsv._load_sv.cache_clear()
