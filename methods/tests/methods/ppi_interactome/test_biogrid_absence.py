"""Regression (burndown P2): ppi_interactome._biogrid_physical_for splits genuine absence
(NoSuchKey/404 or pyarrow FileNotFoundError -> None -> BioGRID leg simply absent) from a
transient/broken-env failure (-> re-raise -> _live_read_error).
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

from methods.ppi_interactome import read as ppi  # noqa: E402


def _nosuchkey():
    return ClientError({"Error": {"Code": "NoSuchKey", "Message": "x"}}, "GetObject")


def _raise(exc):
    def f(*a, **k):
        raise exc

    return f


def test_biogrid_missing_local_file_none(tmp_path):
    # pyarrow raises FileNotFoundError on a missing local path -> None (genuine absence).
    assert ppi._biogrid_physical_for("EGFR", product_path=str(tmp_path / "nope.parquet")) is None


def test_biogrid_genuine_absence_none(monkeypatch):
    monkeypatch.setattr(pq, "read_table", _raise(_nosuchkey()))
    assert ppi._biogrid_physical_for("EGFR") is None


def test_biogrid_transient_reraises(monkeypatch):
    monkeypatch.setattr(pq, "read_table", _raise(RuntimeError("throttle")))
    with pytest.raises(RuntimeError):
        ppi._biogrid_physical_for("EGFR")
