"""Regression (burndown P2): tcga_patient_cn readers must split transient/broken-env failure
(-> re-raise -> _live_read_error) from genuine NoSuchKey/404 absence (-> today's empty result).

`_load_sample_cancer_types` is the SHARED barcode->cancer-type crosswalk that gates EVERY gene's
indication join; it additionally RAISES on an EMPTY map from a well-formed read (the null-strata
guard) so a silent join-collapse to "no samples" can't happen.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.tcga_patient_cn import read as pcn  # noqa: E402


def _nosuchkey():
    return ClientError({"Error": {"Code": "NoSuchKey", "Message": "x"}}, "GetObject")


def _raise(exc):
    def f(*a, **k):
        raise exc
    return f


def test_cancer_types_transient_reraises(monkeypatch):
    pcn._load_sample_cancer_types.cache_clear()
    monkeypatch.setattr(pcn, "_s3_read_bytes", _raise(RuntimeError("throttle")))
    with pytest.raises(RuntimeError):
        pcn._load_sample_cancer_types()
    pcn._load_sample_cancer_types.cache_clear()


def test_cancer_types_genuine_absence_returns_empty(monkeypatch):
    pcn._load_sample_cancer_types.cache_clear()
    monkeypatch.setattr(pcn, "_s3_read_bytes", _raise(_nosuchkey()))
    assert pcn._load_sample_cancer_types() == {}
    pcn._load_sample_cancer_types.cache_clear()


def test_cancer_types_empty_map_guard_raises(monkeypatch):
    # A well-formed read (header only, zero data rows) -> EMPTY crosswalk -> RAISE, not silent {}.
    # This is the null-strata guard: returning {} would collapse every gene's join to "no samples".
    pcn._load_sample_cancer_types.cache_clear()
    monkeypatch.setattr(pcn, "_s3_read_bytes", lambda key: b"patient_barcode\tcancer type\n")
    with pytest.raises(ValueError):
        pcn._load_sample_cancer_types()
    pcn._load_sample_cancer_types.cache_clear()


def test_gistic_transient_reraises(monkeypatch):
    pcn._read_gistic_gene.cache_clear()
    monkeypatch.setattr(pcn, "_s3_read_bytes", _raise(RuntimeError("throttle")))
    with pytest.raises(RuntimeError):
        pcn._read_gistic_gene("EGFR")
    pcn._read_gistic_gene.cache_clear()


def test_gistic_genuine_absence_returns_empty(monkeypatch):
    pcn._read_gistic_gene.cache_clear()
    monkeypatch.setattr(pcn, "_s3_read_bytes", _raise(_nosuchkey()))
    assert pcn._read_gistic_gene("EGFR") == tuple()
    pcn._read_gistic_gene.cache_clear()
