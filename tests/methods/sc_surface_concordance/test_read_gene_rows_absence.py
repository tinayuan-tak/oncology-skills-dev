"""Regression (burndown P2): sc_surface_concordance.read_gene_rows keeps the FileNotFoundError arm
(product not on S3 -> None -> coverage gap) and swallows a genuine NoSuchKey/404 (-> None), but
re-raises a transient/broken-env failure (-> _live_read_error) instead of masking it as a gap.
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
from methods.sc_surface_concordance import read as scc  # noqa: E402


def _nosuchkey():
    return ClientError({"Error": {"Code": "NoSuchKey", "Message": "x"}}, "GetObject")


def _raise(exc):
    def f(*a, **k):
        raise exc
    return f


def test_transient_reraises(monkeypatch):
    monkeypatch.setattr(scc, "_s3fs", lambda: None)
    monkeypatch.setattr(pq, "read_table", _raise(RuntimeError("throttle")))
    with pytest.raises(RuntimeError):
        scc.read_gene_rows("EGFR")


def test_genuine_absence_none(monkeypatch):
    monkeypatch.setattr(scc, "_s3fs", lambda: None)
    monkeypatch.setattr(pq, "read_table", _raise(_nosuchkey()))
    assert scc.read_gene_rows("EGFR") is None


def test_filenotfound_none(monkeypatch):
    monkeypatch.setattr(scc, "_s3fs", lambda: None)
    monkeypatch.setattr(pq, "read_table", _raise(FileNotFoundError("gone")))
    assert scc.read_gene_rows("EGFR") is None
