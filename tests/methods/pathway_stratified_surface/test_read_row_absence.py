"""Regression (burndown P2): pathway_stratified_surface._read_row splits genuine NoSuchKey/404
(-> None -> not_in_product coverage gap, unchanged) from a transient/broken-env failure (-> re-raise
-> _live_read_error).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pyarrow.parquet as pq  # noqa: E402

import methods.catalog_query.read as cqr  # noqa: E402
from methods.pathway_stratified_surface import read as pss  # noqa: E402


def _nosuchkey():
    return ClientError({"Error": {"Code": "NoSuchKey", "Message": "x"}}, "GetObject")


def _raise(exc):
    def f(*a, **k):
        raise exc

    return f


def test_read_row_transient_reraises(monkeypatch):
    monkeypatch.setattr(cqr, "bucket_key_for", lambda mid: ("b", "k"))
    monkeypatch.setattr(pq, "read_table", _raise(RuntimeError("throttle")))
    with pytest.raises(RuntimeError):
        pss._read_row("EGFR", "HALLMARK_HYPOXIA", "NSCLC")


def test_read_row_genuine_absence_none_and_not_in_product(monkeypatch):
    monkeypatch.setattr(cqr, "bucket_key_for", lambda mid: ("b", "k"))
    monkeypatch.setattr(pq, "read_table", _raise(_nosuchkey()))
    assert pss._read_row("EGFR", "HALLMARK_HYPOXIA", "NSCLC") is None
    r = pss.read_pathway_stratified_surface("EGFR")
    assert r["pathway_stratified_surface_class"] == "not_in_product"
