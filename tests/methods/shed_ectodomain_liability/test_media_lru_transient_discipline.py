"""Regression (sweep-2, @lru_cache-memoizes-a-failed-read): shed_ectodomain_liability.media._load_idmap
(@lru_cache) returned {} on ANY read failure — a transient blip silently flipped every gene to
not_on_secreted_panel AND was memoized process-wide. The transient path must now RAISE (not
memoized); a genuine object-absence (S3 404/NoSuchKey or a missing local id map) still → {}.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.shed_ectodomain_liability import media as M  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_lru():
    M._load_idmap.cache_clear()
    yield
    M._load_idmap.cache_clear()


class _Body:
    def __init__(self, b):
        self._b = b

    def read(self):
        return self._b


def test_idmap_transient_raises_not_cached(monkeypatch):
    import boto3
    calls = {"n": 0}
    csv = b"UniprotID,Symbol\nP01116,KRAS\n"

    class _Client:
        def get_object(self, Bucket, Key):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient S3 throttle")
            return {"Body": _Body(csv)}

    monkeypatch.setattr(boto3, "client", lambda *a, **k: _Client())
    with pytest.raises(RuntimeError):
        M._load_idmap()
    idmap = M._load_idmap()        # NOT memoized: retry succeeds
    assert idmap.get("KRAS") == "P01116"


def test_idmap_genuine_absence_empty(tmp_path):
    """A missing local id map (FileNotFoundError) → {} (target then reads not_on_secreted_panel)."""
    missing = tmp_path / "does_not_exist.csv"
    assert M._load_idmap(str(missing)) == {}
