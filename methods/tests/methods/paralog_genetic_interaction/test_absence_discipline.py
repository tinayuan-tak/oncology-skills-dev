"""Regression (burndown P2): paralog_genetic_interaction already owns the honest "read failure ->
data_unavailable + _live_read_error breadcrumb" contract, so the PUBLIC readers
(combinatorial_dependency_for_gene, lineage_breakdown_for_pair) must NOT let a transient exception
propagate (that would crash the whole skill run on an S3 blip). The refinement: the breadcrumb REASON
now distinguishes transient/creds/broken-env from a genuine NoSuchKey/404, and a transient failure is
NOT permanently cached.
"""

from __future__ import annotations

import pyarrow.parquet as pq
from botocore.exceptions import ClientError

from onc_methods.paralog_genetic_interaction import read as para


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
    para._SUMMARY_CACHE.clear()
    monkeypatch.setattr(para, "_bucket_keys", lambda: ("b", "pk", "sk"))
    monkeypatch.setattr(pq, "read_table", _raise(RuntimeError("throttle / connection reset")))
    out = para.combinatorial_dependency_for_gene("EGFR")
    assert out["combinatorial_dependency_class"] == "data_unavailable"
    assert "transient" in out["_live_read_error"].lower()
    assert "EGFR" not in para._SUMMARY_CACHE
    para._SUMMARY_CACHE.clear()


def test_transient_failure_not_permanently_cached(monkeypatch):
    para._SUMMARY_CACHE.clear()
    monkeypatch.setattr(para, "_bucket_keys", lambda: ("b", "pk", "sk"))
    monkeypatch.setattr(pq, "read_table", _raise(RuntimeError("throttle")))
    out1 = para.combinatorial_dependency_for_gene("EGFR")
    assert out1["combinatorial_dependency_class"] == "data_unavailable"
    assert "EGFR" not in para._SUMMARY_CACHE
    monkeypatch.setattr(pq, "read_table", lambda *a, **k: _FakeTbl(0))
    out2 = para.combinatorial_dependency_for_gene("EGFR")
    assert out2["combinatorial_dependency_class"] != "data_unavailable"
    para._SUMMARY_CACHE.clear()


def test_genuine_absence_is_data_unavailable_with_no_object_breadcrumb(monkeypatch):
    para._SUMMARY_CACHE.clear()
    monkeypatch.setattr(para, "_bucket_keys", lambda: ("b", "pk", "sk"))
    monkeypatch.setattr(pq, "read_table", _raise(_nosuchkey()))
    out = para.combinatorial_dependency_for_gene("EGFR")
    assert out["combinatorial_dependency_class"] == "data_unavailable"
    assert "no-object" in out["_live_read_error"].lower()
    para._SUMMARY_CACHE.clear()


def test_lineage_breakdown_transient_is_graceful(monkeypatch):
    # _read_pair_lines raises on transient; the public lineage_breakdown_for_pair must catch it and
    # return a data_unavailable status + breadcrumb, NOT propagate.
    monkeypatch.setattr(para, "_bucket_keys", lambda: ("b", "pk", "sk"))
    monkeypatch.setattr(pq, "read_table", _raise(RuntimeError("throttle")))
    out = para.lineage_breakdown_for_pair("EGFR", "ERBB2")
    assert out["status"] == "data_unavailable"
    assert "transient" in out["_live_read_error"].lower()


def test_lineage_breakdown_genuine_absence_is_data_unavailable(monkeypatch):
    monkeypatch.setattr(para, "_bucket_keys", lambda: ("b", "pk", "sk"))
    monkeypatch.setattr(pq, "read_table", _raise(_nosuchkey()))
    out = para.lineage_breakdown_for_pair("EGFR", "ERBB2")
    assert out["status"] == "data_unavailable"
