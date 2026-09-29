"""Regression (sweep-2, @lru_cache-memoizes-a-failed-read): cspa_surface_confirmation._load_indexed
must RAISE on a transient/broken-env read failure (so @lru_cache never memoizes it — one blip must
not poison the whole process) and return None ONLY on a genuine object-absence (404/NoSuchKey).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.cspa_surface_confirmation import read as R  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_lru():
    R._load_indexed.cache_clear()
    yield
    R._load_indexed.cache_clear()


def test_transient_raises_and_is_not_cached(monkeypatch):
    """A transient failure raises out of the lru (not memoized); the next call retries + succeeds."""
    calls = {"n": 0}
    good = pd.DataFrame(
        [
            {
                "uniprot_ac": "P01116",
                "surface_confirmation_class": "confirmed",
                "cspa_category": "1 - high confidence",
                "n_celllines_detected": 5,
            },
        ]
    )

    def fake_read_parquet(path, bucket, key):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient S3 throttle (SlowDown)")
        return good

    monkeypatch.setattr(R, "_read_parquet", fake_read_parquet)

    with pytest.raises(RuntimeError):
        R._load_indexed()

    # NOT memoized: a subsequent call re-invokes the read and now succeeds.
    idx = R._load_indexed()
    assert idx is not None
    payload_by_ac, _symbol_to_ac = idx
    assert "P01116" in payload_by_ac


def test_genuine_absence_returns_none(monkeypatch):
    """A genuine NoSuchKey → None (honest data_unavailable)."""
    from botocore.exceptions import ClientError

    def fake_read_parquet(path, bucket, key):
        raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")

    monkeypatch.setattr(R, "_read_parquet", fake_read_parquet)
    assert R._load_indexed() is None
    # public reader surfaces the honest data_unavailable (hpa_if={} short-circuits the corroboration leg)
    out = R.read_surface_confirmation("KRAS", hpa_if={})
    assert out["surface_confirmation_class"] == "data_unavailable"


def test_sidecar_transient_raises(monkeypatch):
    """A transient failure on the SIDECAR read (payload OK) must also raise, not silently drop symbol→AC."""
    good_payload = pd.DataFrame(
        [
            {
                "uniprot_ac": "P01116",
                "surface_confirmation_class": "confirmed",
                "cspa_category": "1 - high confidence",
                "n_celllines_detected": 5,
            },
        ]
    )

    def fake_read_parquet(path, bucket, key):
        if key == R.PAYLOAD_KEY:
            return good_payload
        raise RuntimeError("transient S3 throttle on sidecar")

    monkeypatch.setattr(R, "_read_parquet", fake_read_parquet)
    with pytest.raises(RuntimeError):
        R._load_indexed()
