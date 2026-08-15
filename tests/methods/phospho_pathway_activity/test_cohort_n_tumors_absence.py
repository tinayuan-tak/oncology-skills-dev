"""Regression (burndown P2): phospho_pathway_activity._cohort_n_tumors mirrors the Stage-1
_read_gene_sites fix — a genuinely-missing product (FileNotFoundError / NoSuchKey) -> None
(unchanged), a transient/broken-env failure -> re-raise -> _live_read_error.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.phospho_pathway_activity import read as phospho  # noqa: E402


def _raise(exc):
    def f(*a, **k):
        raise exc
    return f


def test_cohort_n_tumors_missing_local_is_none(tmp_path):
    # pyarrow raises FileNotFoundError on a missing local path -> None (genuine absence).
    assert phospho._cohort_n_tumors("coad", product_path=str(tmp_path / "nope.parquet")) is None


def test_cohort_n_tumors_transient_reraises(monkeypatch, tmp_path):
    import pyarrow.parquet as pq
    monkeypatch.setattr(pq, "read_table", _raise(RuntimeError("throttle")))
    with pytest.raises(RuntimeError):
        phospho._cohort_n_tumors("coad", product_path=str(tmp_path / "x.parquet"))
