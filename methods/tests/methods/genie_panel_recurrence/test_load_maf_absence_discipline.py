"""Regression (burndown P3, PR #361): genie_panel_recurrence._load_genie_maf's manifest-resolution
except (bucket_key_for) must PROPAGATE a broken-resolver / broken-env failure rather than mask it as
a coverage gap (None) -- while a GENUINE object-absence (NoSuchKey) still yields None (data_unavailable),
unchanged. (The pq read below already carries its own discriminant.)
"""

from __future__ import annotations

import functools

import pytest
from botocore.exceptions import ClientError

import onc_methods.catalog_query.read as cq
from onc_methods.genie_panel_recurrence import read as gen


@pytest.fixture(autouse=True)
def _clear_module_caches():
    """Both guards below monkeypatch a DEPENDENCY of an @lru_cache'd loader. A warm cache short-
    circuits the loader body, so the patched resolver is never reached and the assertions become
    vacuous -- they fail (or, in the mirror case, pass) purely on test ORDER. Cleared before AND
    after: before so the guards can actually fire, after so this file's tmp_path-scoped results
    (notably a cached None for COADREAD) do not leak into downstream tests.

    Swept generically off the module rather than by name: a fourth @lru_cache added to read.py
    later would otherwise silently re-open the hole.
    """

    def _clear():
        for name in dir(gen):
            fn = getattr(gen, name, None)
            if isinstance(fn, functools._lru_cache_wrapper):
                fn.cache_clear()

    _clear()
    yield
    _clear()


def _nosuchkey():
    return ClientError({"Error": {"Code": "NoSuchKey", "Message": "x"}}, "GetObject")


def _raise(exc):
    def f(*a, **k):
        raise exc

    return f


def test_bucket_key_transient_reraises(monkeypatch, tmp_path):
    monkeypatch.setattr(gen, "GENIE_MAF_LOCAL", tmp_path)  # no local cache -> S3 path
    monkeypatch.setattr(cq, "bucket_key_for", _raise(RuntimeError("catalog resolver broken")))
    with pytest.raises(RuntimeError):
        gen._load_genie_maf("COADREAD")


def test_bucket_key_genuine_absence_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(gen, "GENIE_MAF_LOCAL", tmp_path)
    monkeypatch.setattr(cq, "bucket_key_for", _raise(_nosuchkey()))
    assert gen._load_genie_maf("COADREAD") is None
