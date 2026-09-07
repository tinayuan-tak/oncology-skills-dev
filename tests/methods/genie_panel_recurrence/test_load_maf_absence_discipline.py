"""Regression (burndown P3, PR #361): genie_panel_recurrence._load_genie_maf's manifest-resolution
except (bucket_key_for) must PROPAGATE a broken-resolver / broken-env failure rather than mask it as
a coverage gap (None) -- while a GENUINE object-absence (NoSuchKey) still yields None (data_unavailable),
unchanged. (The pq read below already carries its own discriminant.)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.genie_panel_recurrence import read as gen  # noqa: E402
import methods.catalog_query.read as cq  # noqa: E402


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
