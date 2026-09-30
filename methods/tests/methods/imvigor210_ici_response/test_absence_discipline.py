"""Absence discipline (#832 second pass) for imvigor210_ici_response.read.read_target_summary.

Genuine absence: _rows_for_candidates converts ClientError NoSuchKey/404 (and an unknown manifest id)
to FileNotFoundError, which the reader maps to a graceful ici_response_class=data_unavailable (the
fire-able absence branch). A transient / creds fault now PROPAGATES (the broad masking except was
removed) instead of being laundered into data_unavailable.
"""

from __future__ import annotations

import pytest

from onc_methods.imvigor210_ici_response import read as R


def test_genuine_absence_is_data_unavailable(monkeypatch):
    def _absent(cands):
        raise FileNotFoundError("imvigor210-ici-response-v1 not found (404)")

    monkeypatch.setattr(R, "_rows_for_candidates", _absent)
    out = R.read_target_summary("EGFR", "BLCA")
    assert out["ici_response_class"] == "data_unavailable"


def test_transient_fault_propagates(monkeypatch):
    def _boom(cands):
        raise RuntimeError("s3 throttle")

    monkeypatch.setattr(R, "_rows_for_candidates", _boom)
    with pytest.raises(RuntimeError, match="s3 throttle"):
        R.read_target_summary("EGFR", "BLCA")
