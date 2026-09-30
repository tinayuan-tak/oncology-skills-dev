"""Regression (burndown P2): kinome_atlas_prediction._load_atlas_indexed streams the derived parquet
from S3 via a pyarrow S3FileSystem pushdown (methods.kinome_atlas_prediction.read._read_atlas_df).
A GENUINELY-absent object (NoSuchKey/404 or a pyarrow FileNotFoundError) -> empty indices (honest
absence); a CORRUPT parquet / broken-env / creds / transient failure -> re-raise -> _live_read_error
(and lru_cache never latches the empty).
"""

from __future__ import annotations

import pandas as pd
import pytest

from onc_methods.kinome_atlas_prediction import read as kin


def _raise(exc):
    def f(*a, **k):
        raise exc

    return f


def test_atlas_stream_corrupt_reraises(monkeypatch):
    kin._load_atlas_indexed.cache_clear()
    monkeypatch.setattr(kin, "_get_s3fs", lambda: None)
    monkeypatch.setattr(pd, "read_parquet", _raise(RuntimeError("corrupt parquet footer")))
    with pytest.raises(RuntimeError):
        kin._load_atlas_indexed()
    kin._load_atlas_indexed.cache_clear()


def test_atlas_stream_missing_is_empty(monkeypatch):
    kin._load_atlas_indexed.cache_clear()
    monkeypatch.setattr(kin, "_get_s3fs", lambda: None)
    monkeypatch.setattr(pd, "read_parquet", _raise(FileNotFoundError("gone")))
    df, kinase_index, substrate_index = kin._load_atlas_indexed()
    assert df.empty and kinase_index == {} and substrate_index == {}
    kin._load_atlas_indexed.cache_clear()
