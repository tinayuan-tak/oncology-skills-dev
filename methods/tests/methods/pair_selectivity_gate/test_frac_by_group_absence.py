"""Regression (burndown P2): pair_selectivity_gate._frac_by_group has TWO broad excepts (the
s3_uri_for resolve + the DuckDB execute). Both must split genuine NoSuchKey/404 (-> None ->
data_unavailable, unchanged) from transient/broken-env failure (-> re-raise -> _live_read_error).
DuckDB httpfs surfaces a missing object as an IO error whose message carries NoSuchKey/404 (not a
botocore ClientError), which is treated as genuine absence.
"""

from __future__ import annotations

import pytest
from botocore.exceptions import ClientError

from onc_methods.pair_selectivity_gate import read as psg


def _nosuchkey():
    return ClientError({"Error": {"Code": "NoSuchKey", "Message": "x"}}, "GetObject")


def _raise(exc):
    def f(*a, **k):
        raise exc

    return f


class _FakeCon:
    def __init__(self, exc):
        self.exc = exc

    def execute(self, sql):
        raise self.exc


def test_uri_resolve_transient_reraises(monkeypatch):
    psg._frac_by_group.cache_clear()
    monkeypatch.setattr(psg, "s3_uri_for", _raise(RuntimeError("throttle")))
    with pytest.raises(RuntimeError):
        psg._frac_by_group("A", "B", "AND", "tumor")
    psg._frac_by_group.cache_clear()


def test_uri_resolve_genuine_absence_none(monkeypatch):
    psg._frac_by_group.cache_clear()
    monkeypatch.setattr(psg, "s3_uri_for", _raise(_nosuchkey()))
    assert psg._frac_by_group("A", "B", "AND", "tumor") is None
    psg._frac_by_group.cache_clear()


def test_duckdb_transient_reraises(monkeypatch):
    psg._frac_by_group.cache_clear()
    monkeypatch.setattr(psg, "s3_uri_for", lambda mid: "s3://b/k.parquet")
    monkeypatch.setattr(psg, "_con", lambda: _FakeCon(RuntimeError("connection reset by peer")))
    with pytest.raises(RuntimeError):
        psg._frac_by_group("A", "B", "AND", "tumor")
    psg._frac_by_group.cache_clear()


def test_duckdb_genuine_absence_none(monkeypatch):
    psg._frac_by_group.cache_clear()
    monkeypatch.setattr(psg, "s3_uri_for", lambda mid: "s3://b/k.parquet")
    monkeypatch.setattr(psg, "_con", lambda: _FakeCon(RuntimeError("HTTP GET error ... NoSuchKey")))
    assert psg._frac_by_group("A", "B", "AND", "tumor") is None
    psg._frac_by_group.cache_clear()
