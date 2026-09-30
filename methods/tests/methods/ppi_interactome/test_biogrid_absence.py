"""Regression (burndown P2): ppi_interactome._biogrid_physical_for splits genuine absence
(NoSuchKey/404 or pyarrow FileNotFoundError -> None -> BioGRID leg simply absent) from a
transient/broken-env failure (-> re-raise -> _live_read_error).
"""

from __future__ import annotations

import pyarrow.parquet as pq
import pytest
from botocore.exceptions import ClientError

from onc_methods.ppi_interactome import read as ppi


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
