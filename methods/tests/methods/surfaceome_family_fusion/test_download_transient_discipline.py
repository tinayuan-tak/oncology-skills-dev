"""Regression (sweep-2, @lru_cache-memoizes-a-failed-read): the present-file read path in
_load_indexed was hardened to raise (burndown P1), but the S3-DOWNLOAD transient path still let
_ensure_derived_cached return None → _load_indexed returned EMPTY frames that @lru_cache memoized,
poisoning the whole batch off one blip. The download transient path must now RAISE; a genuine
object-absence (404/NoSuchKey) still degrades to data_unavailable.
"""

from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")


from onc_methods.surfaceome_family_fusion import read as surf


class _FlakyClient:
    def __init__(self, exc, df):
        self._exc, self._df, self.calls = exc, df, 0

    def download_file(self, bucket, key, dest):
        self.calls += 1
        if self.calls == 1:
            raise self._exc
        self._df.to_parquet(dest)


def _reset(monkeypatch, tmp_path):
    monkeypatch.setattr(surf, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(surf, "CACHE_PARQUET", tmp_path / "surfaceome_family.parquet")
    monkeypatch.setattr(surf, "_DERIVED_STATUS", None)
    surf._load_indexed.cache_clear()


def test_download_transient_raises_not_cached(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    df = pd.DataFrame(
        [{"gene_symbol": "EPCAM", "uniprot_ac": "P16422", "family_class": "surface", "is_surface_protein": True}]
    )
    client = _FlakyClient(RuntimeError("transient S3 throttle"), df)  # ONE instance (counter persists)
    monkeypatch.setattr(surf, "_boto3_client", lambda: client)
    with pytest.raises(RuntimeError):
        surf._load_indexed()
    # NOT memoized: retry re-invokes the download + succeeds.
    _df, gene_idx, _ac_idx = surf._load_indexed()
    assert "EPCAM" in gene_idx


def test_download_genuine_absence_data_unavailable(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    from botocore.exceptions import ClientError

    class _Absent:
        def download_file(self, b, k, d):
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")

    monkeypatch.setattr(surf, "_boto3_client", lambda: _Absent())
    r = surf.read_target_summary("EPCAM")
    assert r["family_class"] == "data_unavailable"
    assert r["is_surface_protein"] is False
