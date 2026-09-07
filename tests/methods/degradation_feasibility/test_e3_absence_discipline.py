"""Regression (burndown P2): degradation_feasibility._read_e3_substrate treats genuine NoSuchKey/404
absence as NEUTRAL (-> None), but must NOT swallow a transient/broken-env failure — doing so silently
downgrades a real `ubiquitination_substrate` positive to `plausible_untested`. A transient error
re-raises and propagates through the public entrypoint (surfaced as _live_read_error by the seam).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import methods.catalog_query.read as cqr  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
from methods.degradation_feasibility import read as deg  # noqa: E402


def _nosuchkey():
    return ClientError({"Error": {"Code": "NoSuchKey", "Message": "x"}}, "GetObject")


def _raise(exc):
    def f(*a, **k):
        raise exc

    return f


def test_e3_transient_reraises(monkeypatch):
    monkeypatch.setattr(cqr, "bucket_key_for", lambda mid: ("b", "k"))
    monkeypatch.setattr(pq, "read_table", _raise(RuntimeError("throttle")))
    with pytest.raises(RuntimeError):
        deg._read_e3_substrate("EGFR")


def test_e3_genuine_absence_none(monkeypatch):
    monkeypatch.setattr(cqr, "bucket_key_for", lambda mid: ("b", "k"))
    monkeypatch.setattr(pq, "read_table", _raise(_nosuchkey()))
    assert deg._read_e3_substrate("EGFR") is None


def test_transient_not_silent_downgrade(monkeypatch):
    # A transient E3 read must surface as an error at the public entrypoint, NOT be swallowed into
    # a plausible_untested downgrade.
    monkeypatch.setattr(cqr, "bucket_key_for", lambda mid: ("b", "k"))
    monkeypatch.setattr(pq, "read_table", _raise(RuntimeError("throttle")))
    with pytest.raises(RuntimeError):
        deg.degradation_feasibility_for_gene("SOMEGENE", is_surface_protein=False, precedent={})
