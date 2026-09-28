"""#822: the SIGNOR reader's inline Path-2/3 compute fallback
(``signor_mechanism_network/read.py``) caught **all** compute exceptions and returned a clean
``network_class="data_unavailable"`` dict that never raises.

SIGNOR is the ONLY verdict-driving lane feeding ``mechanism_composed`` (whose verdict keys on
``network_class`` alone). The composed reader already re-raises transient faults via
``_is_genuine_absence`` — but that guard was unreachable because the SIGNOR lane swallowed the
fault FIRST and returned a benign ``data_unavailable``. A transient infra fault was thus silently
encoded as a coverage gap, which (via ``risk_projection.py``) also manufactures a false
'Right Target' biological-risk escalation (oncology-skills#1562).

These tests pin BOTH directions on the Path-2/3 fallback so the fix (narrow the catch-all to
``is_definitively_absent``, mirroring the derived-parquet path and the CollecTRI reader) cannot
over- or under-correct:
  1. a genuine NoSuchKey / 404 / NoSuchBucket / FileNotFoundError (true source absence) still
     yields a clean ``data_unavailable`` — no raise.
  2. a simulated transient error (throttling / creds / parse) RE-RAISES rather than being silently
     classified absent.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

import methods.signor_mechanism_network.read as signor_read


def _nosuchkey():
    """A genuine not-found ClientError — the ONLY failure the lane may swallow (honest data_unavailable)."""
    from botocore.exceptions import ClientError

    return ClientError({"Error": {"Code": "NoSuchKey", "Message": "not found"}}, "GetObject")


def _throttling():
    """A transient ClientError (SlowDown) — NOT a genuine-absence signal; must re-raise."""
    from botocore.exceptions import ClientError

    return ClientError({"Error": {"Code": "SlowDown", "Message": "please reduce request rate"}}, "GetObject")


def _run_path2(compute_side_effect):
    """Force Path 1 (derived parquet) to miss so the read falls to the inline Path-2/3 compute,
    then drive _compute_edges_for_target to raise the given error."""
    with (
        patch.object(signor_read, "_read_from_derived_parquet", return_value=None),
        patch.object(signor_read, "_compute_edges_for_target", side_effect=compute_side_effect),
    ):
        return signor_read.read_target_summary("KRAS")


class TestSignorPath23HonestLoud:
    def test_genuine_nosuchkey_yields_clean_data_unavailable(self):
        def _raise(target):
            raise _nosuchkey()

        result = _run_path2(_raise)
        assert result["network_class"] == "data_unavailable"
        assert result["n_upstream_regulators"] == 0
        assert result["n_downstream_effectors"] == 0

    def test_filenotfound_is_genuine_absence(self):
        def _raise(target):
            raise FileNotFoundError("no local SIGNOR cache")

        result = _run_path2(_raise)
        assert result["network_class"] == "data_unavailable"

    def test_transient_throttling_reraises_not_silently_absent(self):
        def _raise(target):
            raise _throttling()

        with pytest.raises(Exception) as ei:
            _run_path2(_raise)
        assert "SlowDown" in str(ei.value) or "reduce request rate" in str(ei.value)

    def test_parse_fault_reraises(self):
        """A parse/decode fault (e.g. corrupted TSV) is NOT genuine absence — must re-raise."""

        def _raise(target):
            raise ValueError("could not parse SIGNOR release row")

        with pytest.raises(ValueError):
            _run_path2(_raise)

    def test_broken_env_reraises(self):
        def _raise(target):
            raise RuntimeError("some import/env failure")

        with pytest.raises(RuntimeError):
            _run_path2(_raise)
