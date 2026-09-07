"""Regression (sweep-2, @lru_cache-memoizes-a-failed-read): the lru-cached loaders
_load_structure_indexed / _load_ligandability_indexed sit over _ensure_*_cached, whose
None-on-transient retry latch NEVER re-fired because the lru never re-invoked it — one transient
S3 blip memoized an empty index for the whole process. The transient path must now RAISE (so the
lru does not memoize the empty), while a genuine object-absence (404/NoSuchKey) still degrades to
an empty index → honest data_unavailable / insufficient_evidence.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.structure_features_static import read as R  # noqa: E402


class _FlakyClient:
    """download_file raises `exc` on the first call; on later calls writes `df` to the destination."""

    def __init__(self, exc, df):
        self._exc = exc
        self._df = df
        self.calls = 0

    def download_file(self, bucket, key, dest):
        self.calls += 1
        if self.calls == 1:
            raise self._exc
        self._df.to_parquet(dest)


class _AbsentClient:
    def __init__(self, exc):
        self._exc = exc

    def download_file(self, bucket, key, dest):
        raise self._exc


def _reset(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(R, "CACHE_PARQUET", tmp_path / "structure_features.parquet")
    monkeypatch.setattr(R, "CACHE_LIGAND_PARQUET", tmp_path / "structure_ligandability_per_protein.parquet")
    monkeypatch.setattr(R, "_DERIVED_STATUS", None)
    monkeypatch.setattr(R, "_LIGAND_STATUS", None)
    R._load_structure_indexed.cache_clear()
    R._load_ligandability_indexed.cache_clear()


def test_structure_transient_raises_not_cached(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    df = pd.DataFrame(
        [
            {
                "gene_symbol": "KRAS",
                "uniprot_ac": "P01116",
                "hotspot_pocket_adjacency_call": "adjacent",
                "mutation_hotspot_in_druggable_pocket": True,
            }
        ]
    )
    client = _FlakyClient(RuntimeError("transient S3 throttle"), df)
    monkeypatch.setattr(R, "_boto3_client", lambda: client)

    with pytest.raises(RuntimeError):
        R._load_structure_indexed()
    # NOT memoized + latch never flipped to False (transient) → next call retries + succeeds.
    idx = R._load_structure_indexed()
    assert "KRAS" in idx


def test_structure_genuine_absence_empty(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    from botocore.exceptions import ClientError

    monkeypatch.setattr(
        R, "_boto3_client", lambda: _AbsentClient(ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject"))
    )
    assert R._load_structure_indexed() == {}


def test_ligandability_transient_raises_not_cached(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    df = pd.DataFrame(
        [
            {
                "gene_symbol": "KRAS",
                "uniprot_id": "P01116",
                "structural_ligandability_class": "experimental_ligandable",
                "n_ligandability_axes": 2,
            }
        ]
    )
    client = _FlakyClient(RuntimeError("transient S3 throttle"), df)
    monkeypatch.setattr(R, "_boto3_client", lambda: client)

    with pytest.raises(RuntimeError):
        R._load_ligandability_indexed()
    idx = R._load_ligandability_indexed()
    assert "KRAS" in idx


def test_ligandability_genuine_absence_insufficient(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    from botocore.exceptions import ClientError

    monkeypatch.setattr(
        R, "_boto3_client", lambda: _AbsentClient(ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject"))
    )
    assert R._load_ligandability_indexed() == {}
    fields = R._ligandability_fields("KRAS")
    assert fields["structural_ligandability_class"] == "insufficient_evidence"


def test_read_target_summary_propagates_transient(monkeypatch, tmp_path):
    """The public reader must let a transient surface (→ _live_read_error at the seam), NOT mask it
    as a false no_structure / insufficient_evidence."""
    _reset(monkeypatch, tmp_path)
    monkeypatch.setattr(R, "_boto3_client", lambda: _AbsentClient(RuntimeError("transient S3 throttle")))
    with pytest.raises(RuntimeError):
        R.read_target_summary("KRAS")
