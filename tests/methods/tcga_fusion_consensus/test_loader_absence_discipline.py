"""Regression (burndown P3, PR #361): tcga_fusion_consensus._load_consensus / _load_coverage read a
LOCAL cached parquet (S3 is already latched definitive-vs-transient in _ensure_*_cached). A corrupt
cache / broken env (missing pyarrow) must PROPAGATE, not be masked as an empty frame; a GENUINE
absence (S3 404 latched upstream -> path=None) still yields empty, unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.tcga_fusion_consensus import read as fus  # noqa: E402


def _boom(*a, **k):
    raise RuntimeError("corrupt cache / missing pyarrow")


def test_load_consensus_corrupt_cache_reraises(monkeypatch, tmp_path):
    fus._load_consensus.cache_clear()
    fake = tmp_path / "consensus.parquet"
    fake.write_bytes(b"not-a-real-parquet")
    monkeypatch.setattr(fus, "_ensure_derived_cached", lambda: fake)
    monkeypatch.setattr(fus.pd, "read_parquet", _boom)
    with pytest.raises(RuntimeError):
        fus._load_consensus()
    fus._load_consensus.cache_clear()


def test_load_consensus_genuine_absence_returns_empty(monkeypatch):
    fus._load_consensus.cache_clear()
    # S3 404/NoSuchKey latched in _ensure_derived_cached -> path=None (unchanged genuine-absence).
    monkeypatch.setattr(fus, "_ensure_derived_cached", lambda: None)
    assert fus._load_consensus().empty
    fus._load_consensus.cache_clear()


def test_load_coverage_corrupt_cache_reraises(monkeypatch, tmp_path):
    fus._load_coverage.cache_clear()
    fake = tmp_path / "coverage.parquet"
    fake.write_bytes(b"not-a-real-parquet")
    monkeypatch.setattr(fus, "_ensure_coverage_cached", lambda: fake)
    monkeypatch.setattr(fus.pd, "read_parquet", _boom)
    with pytest.raises(RuntimeError):
        fus._load_coverage()
    fus._load_coverage.cache_clear()
