"""Regression (burndown P2): kinome_atlas_prediction._load_atlas_indexed reads a LOCAL cached
parquet (the S3 fetch is discriminated upstream in _ensure_derived_cached). A genuinely-missing
file (FileNotFoundError) -> empty indices (honest absence); a CORRUPT parquet / broken-env failure
-> re-raise -> _live_read_error (and lru_cache never latches the empty).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402
from methods.kinome_atlas_prediction import read as kin  # noqa: E402


def _raise(exc):
    def f(*a, **k):
        raise exc
    return f


def test_atlas_local_corrupt_reraises(monkeypatch):
    kin._load_atlas_indexed.cache_clear()
    monkeypatch.setattr(kin, "_ensure_derived_cached", lambda: Path("/tmp/kin_x.parquet"))
    monkeypatch.setattr(pd, "read_parquet", _raise(RuntimeError("corrupt parquet footer")))
    with pytest.raises(RuntimeError):
        kin._load_atlas_indexed()
    kin._load_atlas_indexed.cache_clear()


def test_atlas_missing_file_is_empty(monkeypatch):
    kin._load_atlas_indexed.cache_clear()
    monkeypatch.setattr(kin, "_ensure_derived_cached", lambda: Path("/tmp/kin_x.parquet"))
    monkeypatch.setattr(pd, "read_parquet", _raise(FileNotFoundError("gone")))
    df, kinase_index, substrate_index = kin._load_atlas_indexed()
    assert df.empty and kinase_index == {} and substrate_index == {}
    kin._load_atlas_indexed.cache_clear()
