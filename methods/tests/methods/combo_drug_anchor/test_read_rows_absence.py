"""Regression (burndown P2): combo_drug_anchor already owns the honest "read failure ->
data_unavailable + _live_read_error breadcrumb" contract, so the PUBLIC reader must NOT let a
transient exception propagate (that would crash the whole skill run on an S3 blip). The refinement:
the breadcrumb REASON now distinguishes transient/creds/broken-env from a genuine NoSuchKey/404, and
a transient failure is NOT permanently cached (a later call retries).
"""

from __future__ import annotations

import pyarrow.parquet as pq
from botocore.exceptions import ClientError

import onc_methods.catalog_query.read as cqr
from onc_methods.combo_drug_anchor import read as combo


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
    combo._ROWS_CACHE.clear()
    monkeypatch.setattr(cqr, "bucket_key_for", lambda mid: ("b", "k"))
    monkeypatch.setattr(pq, "read_table", _raise(RuntimeError("throttle / connection reset")))
    out = combo.combination_opportunities_for_gene("KRAS")  # rows=None -> live read
    # A transient blip degrades GRACEFULLY (no uncaught raise) to data_unavailable + a breadcrumb
    # that names the true (transient) cause — NOT the generic no-object message.
    assert out["combination_opportunity_class"] == "data_unavailable"
    assert "transient" in out["_live_read_error"].lower()
    assert "KRAS" not in combo._ROWS_CACHE  # transient must NOT poison the cache
    combo._ROWS_CACHE.clear()


def test_transient_failure_not_permanently_cached(monkeypatch):
    combo._ROWS_CACHE.clear()
    monkeypatch.setattr(cqr, "bucket_key_for", lambda mid: ("b", "k"))
    # 1st call: transient -> data_unavailable, not cached.
    monkeypatch.setattr(pq, "read_table", _raise(RuntimeError("throttle")))
    out1 = combo.combination_opportunities_for_gene("KRAS")
    assert out1["combination_opportunity_class"] == "data_unavailable"
    assert "KRAS" not in combo._ROWS_CACHE
    # 2nd call: the read now succeeds -> NOT stuck on a memoized data_unavailable.
    monkeypatch.setattr(pq, "read_table", lambda *a, **k: _FakeTbl(0))
    out2 = combo.combination_opportunities_for_gene("KRAS")
    assert out2["combination_opportunity_class"] != "data_unavailable"
    combo._ROWS_CACHE.clear()


def test_genuine_absence_is_data_unavailable_with_no_object_breadcrumb(monkeypatch):
    combo._ROWS_CACHE.clear()
    monkeypatch.setattr(cqr, "bucket_key_for", lambda mid: ("b", "k"))
    monkeypatch.setattr(pq, "read_table", _raise(_nosuchkey()))
    out = combo.combination_opportunities_for_gene("KRAS")
    assert out["combination_opportunity_class"] == "data_unavailable"
    assert "no-object" in out["_live_read_error"].lower()  # genuine-absence breadcrumb, not transient
    combo._ROWS_CACHE.clear()
