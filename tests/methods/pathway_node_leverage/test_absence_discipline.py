"""Absence discipline (#832 second pass) for pathway_node_leverage.cli.read_node_leverage.

The lens loaders read via s3_client().get_object (C._get), so a genuinely-missing object raises a
ClientError NoSuchKey -> honest node_leverage_class=data_unavailable (fire-able absence branch). A
transient / creds fault now PROPAGATES instead of being masked.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import methods.pathway_node_leverage.cli as C  # noqa: E402


def test_genuine_object_absence_is_data_unavailable(monkeypatch):
    monkeypatch.setattr(C, "_model_ids_for_lineage", lambda lineage: [])

    def _absent(key):
        raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")

    monkeypatch.setattr(C, "_get", _absent)
    out = C.read_node_leverage("EGFR", None)
    assert out["node_leverage_class"] == "data_unavailable"
    assert "_live_read_error" in out


def test_transient_fault_propagates(monkeypatch):
    monkeypatch.setattr(C, "_model_ids_for_lineage", lambda lineage: [])

    def _boom(key):
        raise RuntimeError("throttle")

    monkeypatch.setattr(C, "_get", _boom)
    with pytest.raises(RuntimeError, match="throttle"):
        C.read_node_leverage("EGFR", None)
