"""Absence discipline (#832 second pass) for pharos_tdl.cli.read_pharos_tdl.

The TCRD table is read via s3_client().get_object, so a genuinely-missing object raises a ClientError
NoSuchKey -> honest tdl_class=data_unavailable (fire-able absence branch). A transient / creds fault
now PROPAGATES instead of being masked. (Target-present/row-absent is handled separately, outside the
try, and is covered by test_pharos_tdl.py::test_unmapped.)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.pharos_tdl import cli as pt  # noqa: E402


def test_genuine_object_absence_is_data_unavailable(monkeypatch):
    def _absent():
        raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")

    monkeypatch.setattr(pt, "_load_table", _absent)
    out = pt.read_pharos_tdl("EGFR")
    assert out["tdl_class"] == "data_unavailable"
    assert "_live_read_error" in out


def test_transient_fault_propagates(monkeypatch):
    def _boom():
        raise ClientError({"Error": {"Code": "ThrottlingException"}}, "GetObject")

    monkeypatch.setattr(pt, "_load_table", _boom)
    with pytest.raises(ClientError):
        pt.read_pharos_tdl("EGFR")
