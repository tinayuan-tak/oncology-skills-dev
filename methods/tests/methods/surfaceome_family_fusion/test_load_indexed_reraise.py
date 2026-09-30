"""Regression (burndown P1): surfaceome_family_fusion._load_indexed must PROPAGATE a broken-env /
corrupt-cache local-parquet failure rather than mask it as an empty frame; a genuine absent product
(S3 404 latched upstream -> path=None) still yields data_unavailable, unchanged.
"""

from __future__ import annotations

import pytest

from onc_methods.surfaceome_family_fusion import read as surf


@pytest.fixture(autouse=True)
def _clear_lru():
    surf._load_indexed.cache_clear()
    yield
    surf._load_indexed.cache_clear()


def test_load_indexed_reraises_corrupt_local_cache(monkeypatch, tmp_path):
    fake = tmp_path / "surf.parquet"
    fake.write_bytes(b"not-a-real-parquet")
    monkeypatch.setattr(surf, "_ensure_derived_cached", lambda: fake)
    import pandas as pd

    monkeypatch.setattr(pd, "read_parquet", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        surf._load_indexed()


def test_read_target_summary_propagates_broken_env(monkeypatch, tmp_path):
    fake = tmp_path / "surf.parquet"
    fake.write_bytes(b"x")
    monkeypatch.setattr(surf, "_ensure_derived_cached", lambda: fake)
    import pandas as pd

    monkeypatch.setattr(pd, "read_parquet", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        surf.read_target_summary("EPCAM")


def test_genuine_absence_is_data_unavailable(monkeypatch):
    monkeypatch.setattr(surf, "_ensure_derived_cached", lambda: None)
    r = surf.read_target_summary("EPCAM")
    assert r["family_class"] == "data_unavailable"
    assert r["is_surface_protein"] is False
