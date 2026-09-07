"""Regression (burndown P2): resistance_emergence already owns the honest "read failure ->
data_unavailable + _live_read_error breadcrumb" contract, so the PUBLIC reader must NOT let a
transient exception propagate (that would crash the whole skill run on an S3 blip). The refinement:
the breadcrumb REASON now distinguishes transient/creds/broken-env from a genuine NoSuchKey/404, and
a transient failure is NOT permanently cached (a later call retries).
"""

from __future__ import annotations

import sys
from pathlib import Path

from botocore.exceptions import ClientError

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import methods.catalog_query.read as cqr  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
from methods.resistance_emergence import read as res  # noqa: E402


def _nosuchkey():
    return ClientError({"Error": {"Code": "NoSuchKey", "Message": "x"}}, "GetObject")


def _raise(exc):
    def f(*a, **k):
        raise exc

    return f


class _FakeTbl:
    def __init__(self, n):
        self.num_rows = n

    def to_pylist(self):
        return []


def test_transient_failure_is_data_unavailable_with_breadcrumb(monkeypatch):
    res._ROWS_CACHE.clear()
    monkeypatch.setattr(cqr, "bucket_key_for", lambda mid: ("b", "k"))
    monkeypatch.setattr(pq, "read_table", _raise(RuntimeError("throttle / connection reset")))
    out = res.resistance_mediators_for_gene("KRAS", include_tahoe_adaptation=False)
    assert out["resistance_emergence_class"] == "data_unavailable"
    assert "transient" in out["_live_read_error"].lower()
    assert "KRAS" not in res._ROWS_CACHE
    res._ROWS_CACHE.clear()


def test_transient_failure_not_permanently_cached(monkeypatch):
    res._ROWS_CACHE.clear()
    monkeypatch.setattr(cqr, "bucket_key_for", lambda mid: ("b", "k"))
    monkeypatch.setattr(pq, "read_table", _raise(RuntimeError("throttle")))
    out1 = res.resistance_mediators_for_gene("KRAS", include_tahoe_adaptation=False)
    assert out1["resistance_emergence_class"] == "data_unavailable"
    assert "KRAS" not in res._ROWS_CACHE
    monkeypatch.setattr(pq, "read_table", lambda *a, **k: _FakeTbl(0))
    out2 = res.resistance_mediators_for_gene("KRAS", include_tahoe_adaptation=False)
    assert out2["resistance_emergence_class"] != "data_unavailable"
    res._ROWS_CACHE.clear()


def test_genuine_absence_is_data_unavailable_with_no_object_breadcrumb(monkeypatch):
    res._ROWS_CACHE.clear()
    monkeypatch.setattr(cqr, "bucket_key_for", lambda mid: ("b", "k"))
    monkeypatch.setattr(pq, "read_table", _raise(_nosuchkey()))
    out = res.resistance_mediators_for_gene("KRAS", include_tahoe_adaptation=False)
    assert out["resistance_emergence_class"] == "data_unavailable"
    assert "no-object" in out["_live_read_error"].lower()
    res._ROWS_CACHE.clear()
