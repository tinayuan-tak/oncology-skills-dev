"""Absence discipline (#832 second pass) for depmap_protein_abundance.read.read_target_summary.

Measures BOTH sides of the narrowing: genuine absence (missing object / 404 / FileNotFound) still
degrades to a graceful data_unavailable summary (the fire-able absence branch), while a transient /
creds / broken-env fault now PROPAGATES (an honest _live_read_error at the compose seam) instead of
being masked as protein_expression_class=data_unavailable.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

cli = importlib.import_module("methods.depmap_protein_abundance.cli")
read = importlib.import_module("methods.depmap_protein_abundance.read")


def test_genuine_absence_is_data_unavailable(monkeypatch):
    def _absent(*a, **k):
        raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")

    monkeypatch.setattr(cli, "load_and_classify", _absent)
    out = read.read_target_summary("EGFR", indication="COADREAD")
    assert out["protein_expression_class"] == "data_unavailable"
    assert out["_live_read_error"] == "depmap_protein_abundance_read_failed"

    def _missing(*a, **k):
        raise FileNotFoundError("product gone")

    monkeypatch.setattr(cli, "load_and_classify", _missing)
    assert read.read_target_summary("EGFR")["protein_expression_class"] == "data_unavailable"


def test_transient_fault_propagates(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("s3 down")

    monkeypatch.setattr(cli, "load_and_classify", _boom)
    with pytest.raises(RuntimeError, match="s3 down"):
        read.read_target_summary("EGFR", indication="COADREAD")
