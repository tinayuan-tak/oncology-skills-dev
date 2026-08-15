"""Regression (burndown P2): tcga_aneuploidy_burden._load_sample_cancer_types is the identical
shared barcode->cancer-type crosswalk twin of tcga_patient_cn. Same discipline: re-raise
transient/broken-env, return {} only on genuine NoSuchKey/404, and RAISE on an EMPTY map from a
well-formed read (null-strata guard against a silent join-collapse to "no samples").
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.tcga_aneuploidy_burden import read as anu  # noqa: E402


def _nosuchkey():
    return ClientError({"Error": {"Code": "NoSuchKey", "Message": "x"}}, "GetObject")


def _raise(exc):
    def f(*a, **k):
        raise exc
    return f


def test_cancer_types_transient_reraises(monkeypatch):
    anu._load_sample_cancer_types.cache_clear()
    monkeypatch.setattr(anu, "_s3_read_bytes", _raise(RuntimeError("throttle")))
    with pytest.raises(RuntimeError):
        anu._load_sample_cancer_types()
    anu._load_sample_cancer_types.cache_clear()


def test_cancer_types_genuine_absence_returns_empty(monkeypatch):
    anu._load_sample_cancer_types.cache_clear()
    monkeypatch.setattr(anu, "_s3_read_bytes", _raise(_nosuchkey()))
    assert anu._load_sample_cancer_types() == {}
    anu._load_sample_cancer_types.cache_clear()


def test_cancer_types_empty_map_guard_raises(monkeypatch):
    anu._load_sample_cancer_types.cache_clear()
    monkeypatch.setattr(anu, "_s3_read_bytes", lambda key: b"patient_barcode\tcancer type\n")
    with pytest.raises(ValueError):
        anu._load_sample_cancer_types()
    anu._load_sample_cancer_types.cache_clear()
