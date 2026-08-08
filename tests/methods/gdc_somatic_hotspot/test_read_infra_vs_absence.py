"""Guard: _read_product_table distinguishes DEFINITIVE ABSENCE (→ None → data_unavailable) from a
TRANSIENT/AUTH failure (→ re-raise), so a broken environment is never silently masked as a coverage
gap (the bare-except-masks-broken-env bug class; genomic-alteration review T0.4)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.gdc_somatic_hotspot import read as R  # noqa: E402

_ABSENT = Path("/nonexistent/definitely-not-here.parquet")


def _force_s3_path(monkeypatch):
    monkeypatch.setattr(R, "_manifest_s3_path", lambda mid: "onc-compbio/fake/key.parquet")


def test_transient_error_is_reraised_not_masked(monkeypatch):
    _force_s3_path(monkeypatch)
    monkeypatch.setattr(pq, "read_table", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("throttled")))
    with pytest.raises(RuntimeError):
        R._read_product_table(_ABSENT, "fake-manifest")   # infra failure must surface


def test_nosuchkey_returns_none_graceful(monkeypatch):
    _force_s3_path(monkeypatch)
    class NoSuchKey(Exception):
        pass
    monkeypatch.setattr(pq, "read_table", lambda *a, **k: (_ for _ in ()).throw(NoSuchKey("no such key")))
    assert R._read_product_table(_ABSENT, "fake-manifest") is None   # real absence → data_unavailable


def test_missing_manifest_key_returns_none(monkeypatch):
    monkeypatch.setattr(R, "_manifest_s3_path", lambda mid: None)
    assert R._read_product_table(_ABSENT, "fake-manifest") is None
