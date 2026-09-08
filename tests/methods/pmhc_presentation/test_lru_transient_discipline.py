"""Regression (sweep-2, @lru_cache-memoizes-a-failed-read): pmhc_presentation._symbol_to_ac
(@lru_cache) memoized {} on a transient sidecar failure (every symbol unresolvable process-wide),
and _row_for_ac (@lru_cache maxsize=512) memoized an "UNREADABLE" sentinel per-AC on a transient
payload failure. Both must RAISE on transient/broken-env (not memoized) and return the honest empty
/ sentinel ONLY on a genuine object-absence.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")
pa = pytest.importorskip("pyarrow")

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.pmhc_presentation import read as R  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_lru():
    R._symbol_to_ac.cache_clear()
    R._row_for_ac.cache_clear()
    yield
    R._symbol_to_ac.cache_clear()
    R._row_for_ac.cache_clear()


def test_symbol_to_ac_transient_raises_not_cached(monkeypatch):
    calls = {"n": 0}
    tbl = pa.table({"hgnc_primary_symbol_at_resolution": ["KRAS"], "uniprot_canonical": ["P01116"]})

    def fake_read_parquet(bucket, key):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient S3 throttle")
        return tbl

    monkeypatch.setattr(R, "_read_parquet", fake_read_parquet)
    with pytest.raises(RuntimeError):
        R._symbol_to_ac()
    m = R._symbol_to_ac()  # NOT memoized: retry succeeds
    assert m.get("KRAS") == "P01116"


def test_symbol_to_ac_genuine_absence_empty(monkeypatch):
    def fake_read_parquet(bucket, key):
        raise FileNotFoundError("object does not exist")

    monkeypatch.setattr(R, "_read_parquet", fake_read_parquet)
    assert R._symbol_to_ac() == {}


def test_symbol_to_ac_schema_drift_raises(monkeypatch):
    """A present sidecar missing its expected columns is schema drift — raise, don't memoize {}."""
    bad = pa.table({"wrong_col": ["x"]})
    monkeypatch.setattr(R, "_read_parquet", lambda b, k: bad)
    with pytest.raises(ValueError):
        R._symbol_to_ac()


def _patch_pyarrow(monkeypatch, read_table):
    import pyarrow.fs as fs
    import pyarrow.parquet as pq

    monkeypatch.setattr(fs, "S3FileSystem", lambda **k: object())
    monkeypatch.setattr(pq, "read_table", read_table)


def test_row_for_ac_transient_raises_not_cached(monkeypatch):
    calls = {"n": 0}

    def read_table(path, filesystem=None, filters=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient S3 throttle")
        return pa.table({"uniprot_id": ["P01116"], "n_peptides": [3]})

    _patch_pyarrow(monkeypatch, read_table)
    with pytest.raises(RuntimeError):
        R._row_for_ac("P01116")
    row = R._row_for_ac("P01116")  # NOT memoized: retry succeeds
    assert row not in (None, "UNREADABLE")
    assert row["uniprot_id"] == "P01116"


def test_row_for_ac_genuine_absence_sentinel(monkeypatch):
    def read_table(path, filesystem=None, filters=None):
        raise FileNotFoundError("object does not exist")

    _patch_pyarrow(monkeypatch, read_table)
    assert R._row_for_ac("P99999") == "UNREADABLE"
