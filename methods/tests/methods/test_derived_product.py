"""Unit tests for the shared materialized-product loader (methods/derived_product.py).

The per-reader _load_product wrappers monkeypatch _load_product itself, so they never exercise
this helper — these tests cover its two behavior contracts directly: dev-build fallback (the
progeny/stemness/oncogenic/pancanatlas/precog shape) vs raise-on-empty (the tcga_mc3 shape).
"""

from __future__ import annotations

import io
import types

import pandas as pd
import pytest

from methods import derived_product as dp


def _parquet_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf)
    return buf.getvalue()


def _fake_run(stdout: bytes):
    def run(*args, **kwargs):
        return types.SimpleNamespace(stdout=stdout)

    return run


def test_success_reads_parquet(monkeypatch):
    df = pd.DataFrame({"indication": ["COAD"], "n_samples": [42]})
    monkeypatch.setattr(dp.subprocess, "run", _fake_run(_parquet_bytes(df)))
    out = dp.load_materialized_product("s3://bucket/key.parquet")
    pd.testing.assert_frame_equal(out, df)


def test_empty_with_dev_build_falls_back(monkeypatch):
    monkeypatch.setattr(dp.subprocess, "run", _fake_run(b""))
    sentinel = pd.DataFrame({"built": [1]})
    out = dp.load_materialized_product("s3://bucket/key.parquet", dev_build=lambda: sentinel)
    pd.testing.assert_frame_equal(out, sentinel)


def test_empty_without_dev_build_raises(monkeypatch):
    monkeypatch.setattr(dp.subprocess, "run", _fake_run(b""))
    with pytest.raises(RuntimeError):
        dp.load_materialized_product("s3://bucket/key.parquet")


def test_subprocess_error_with_dev_build_falls_back(monkeypatch):
    def boom(*a, **k):
        raise OSError("aws cli missing")

    monkeypatch.setattr(dp.subprocess, "run", boom)
    sentinel = pd.DataFrame({"built": [2]})
    out = dp.load_materialized_product("s3://bucket/key.parquet", dev_build=lambda: sentinel)
    pd.testing.assert_frame_equal(out, sentinel)


def test_subprocess_error_without_dev_build_reraises(monkeypatch):
    def boom(*a, **k):
        raise OSError("aws cli missing")

    monkeypatch.setattr(dp.subprocess, "run", boom)
    with pytest.raises(OSError):
        dp.load_materialized_product("s3://bucket/key.parquet")
