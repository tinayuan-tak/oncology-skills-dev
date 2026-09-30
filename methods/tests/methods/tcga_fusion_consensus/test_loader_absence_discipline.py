"""Regression (burndown P3, PR #361; updated for the 2026-08-22 streamed-read conversion):
tcga_fusion_consensus._load_consensus / _load_coverage now STREAM the derived parquet over a pyarrow
S3FileSystem (methods/tcga_fusion_consensus/read.py:_stream_parquet) instead of download_file +
pd.read_parquet(local). The absence discipline is unchanged in SPIRIT: a corrupt-parquet / broken-env
(missing pyarrow) / transient / creds error must PROPAGATE, not be masked as an empty frame; a GENUINE
absence (pyarrow FileNotFoundError / NoSuchKey) still yields an empty frame + latches the status flag.
"""

from __future__ import annotations

import pytest

from onc_methods.tcga_fusion_consensus import read as fus


def _boom(*a, **k):
    raise RuntimeError("corrupt parquet / missing pyarrow / broken env")


def _absent(*a, **k):
    # pyarrow surfaces a missing S3 object as FileNotFoundError -> definitive absence.
    raise FileNotFoundError("s3 object does not exist")


def test_load_consensus_corrupt_or_transient_reraises(monkeypatch):
    fus._load_consensus.cache_clear()
    monkeypatch.setattr(fus, "_DERIVED_STATUS", None)  # clear any latched-absence from a prior test
    monkeypatch.setattr(fus, "_stream_parquet", _boom)
    with pytest.raises(RuntimeError):
        fus._load_consensus()
    fus._load_consensus.cache_clear()


def test_load_consensus_genuine_absence_returns_empty(monkeypatch):
    fus._load_consensus.cache_clear()
    monkeypatch.setattr(fus, "_DERIVED_STATUS", None)
    monkeypatch.setattr(fus, "_stream_parquet", _absent)  # NoSuchKey/404 -> pyarrow FileNotFoundError
    assert fus._load_consensus().empty
    fus._load_consensus.cache_clear()


def test_load_coverage_corrupt_or_transient_reraises(monkeypatch):
    fus._load_coverage.cache_clear()
    monkeypatch.setattr(fus, "_COVERAGE_STATUS", None)
    monkeypatch.setattr(fus, "_stream_parquet", _boom)
    with pytest.raises(RuntimeError):
        fus._load_coverage()
    fus._load_coverage.cache_clear()


def test_load_coverage_genuine_absence_returns_empty(monkeypatch):
    fus._load_coverage.cache_clear()
    monkeypatch.setattr(fus, "_COVERAGE_STATUS", None)
    monkeypatch.setattr(fus, "_stream_parquet", _absent)
    assert fus._load_coverage().empty
    fus._load_coverage.cache_clear()
