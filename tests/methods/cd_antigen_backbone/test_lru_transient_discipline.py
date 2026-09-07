"""Regression (sweep-2, @lru_cache-memoizes-a-failed-read): cd_antigen_backbone._load_roster
(@lru_cache) returned {} on ANY read failure. The caller surfaces a per-call _live_read_error
breadcrumb, but the lru memoized the empty roster process-wide — so one transient blip pinned EVERY
target to "roster unreadable" for the whole process. The transient path must now RAISE (not
memoized); a genuine object-absence (S3 404/NoSuchKey or a missing local members.json) still → {}.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.cd_antigen_backbone import read as R  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_lru():
    R._load_roster.cache_clear()
    yield
    R._load_roster.cache_clear()


class _Body:
    def __init__(self, b):
        self._b = b

    def read(self):
        return self._b


def test_transient_raises_not_cached(monkeypatch):
    import boto3
    import json

    calls = {"n": 0}

    class _Client:
        def get_object(self, Bucket, Key):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient S3 throttle")
            return {"Body": _Body(json.dumps([{"symbol": "CD19"}]).encode())}

    monkeypatch.setattr(boto3, "client", lambda *a, **k: _Client())
    with pytest.raises(RuntimeError):
        R._load_roster()
    roster = R._load_roster()  # NOT memoized: retry succeeds
    assert "CD19" in roster


def test_genuine_absence_empty(tmp_path):
    """A missing local members.json (FileNotFoundError) → {} (caller emits its breadcrumb)."""
    missing = tmp_path / "does_not_exist.json"
    assert R._load_roster(str(missing)) == {}
    out = R.read_cd_antigen_backbone("CD19", members_path=str(missing))
    assert out.get("_live_read_error") == "cd_antigen_roster_read_failed"
