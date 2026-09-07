"""Regression (burndown P1): cptac_protein_deg._load_indexed must PROPAGATE a broken-env /
corrupt-cache local-parquet failure (honest _live_read_error at the live-read seam), NOT mask it as
an empty frame — while a GENUINE absent product (S3 404 latched upstream -> path=None) still yields
data_unavailable, unchanged. Also guards that the raise propagates through the callers
(read_target_summary / read_all_cohorts) rather than being re-swallowed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.cptac_protein_deg import read as cptac  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_lru():
    cptac._load_indexed.cache_clear()
    yield
    cptac._load_indexed.cache_clear()


def _point_at_local_cache(monkeypatch, tmp_path):
    fake = tmp_path / "cptac.parquet"
    fake.write_bytes(b"not-a-real-parquet")  # present-but-corrupt local cache
    monkeypatch.setattr(cptac, "_ensure_derived_cached", lambda: fake)


def test_load_indexed_reraises_corrupt_local_cache(monkeypatch, tmp_path):
    _point_at_local_cache(monkeypatch, tmp_path)
    import pandas as pd

    def boom(*a, **k):
        raise RuntimeError("corrupt cache / missing pyarrow")

    monkeypatch.setattr(pd, "read_parquet", boom)
    with pytest.raises(RuntimeError):
        cptac._load_indexed()


def test_read_target_summary_propagates_broken_env(monkeypatch, tmp_path):
    _point_at_local_cache(monkeypatch, tmp_path)
    import pandas as pd

    monkeypatch.setattr(pd, "read_parquet", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        cptac.read_target_summary("EGFR", "COADREAD")


def test_read_all_cohorts_propagates_broken_env(monkeypatch, tmp_path):
    _point_at_local_cache(monkeypatch, tmp_path)
    import pandas as pd

    monkeypatch.setattr(pd, "read_parquet", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        cptac.read_all_cohorts("EGFR")


def test_genuine_absence_is_data_unavailable(monkeypatch):
    # S3 404/NoSuchKey is latched in _ensure_derived_cached -> path=None (unchanged genuine-absence).
    monkeypatch.setattr(cptac, "_ensure_derived_cached", lambda: None)
    r = cptac.read_target_summary("EGFR", "COADREAD")
    assert r["protein_expression_class"] == "data_unavailable"
    assert cptac.read_all_cohorts("EGFR") == []
