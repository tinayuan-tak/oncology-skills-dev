"""Unit tests for the shared resolver-sidecar loader + error-discipline helpers (P5.1, 2026-08-11).

Hermetic (no S3): read a local fixture parquet, and pin the definitive-vs-transient classifier that
decides which failures propagate (broken env / transient / creds) vs which are honest data gaps
(NoSuchKey). The whole point of this module is that a resolver crosswalk RAISES rather than silently
returns {} — an empty crosswalk fails every target (the bare-except dead-axis bug)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from methods.target_id_sidecar import (  # noqa: E402
    is_definitively_absent, read_resolver_sidecar_map,
)


def _write_sidecar(tmp_path, rows):
    import pandas as pd
    p = tmp_path / "resolver.sidecar.parquet"
    pd.DataFrame(rows).to_parquet(p)
    return str(p)


def test_reads_local_fixture_upper_first_wins_nan_skipped(tmp_path):
    sc = _write_sidecar(tmp_path, [
        {"hgnc_primary_symbol_at_resolution": "egfr", "native_row_key": "P00533"},
        {"hgnc_primary_symbol_at_resolution": "EGFR", "native_row_key": "P99999"},  # dup -> first wins
        {"hgnc_primary_symbol_at_resolution": "KRAS", "native_row_key": "nan"},     # stringified null -> skipped
        {"hgnc_primary_symbol_at_resolution": "TP53", "native_row_key": "P04637"},
    ])
    m = read_resolver_sidecar_map(
        "b", "k", "hgnc_primary_symbol_at_resolution", "native_row_key", local_path=sc)
    assert m["EGFR"] == "P00533"        # upper-cased key; first value wins
    assert "KRAS" not in m               # 'nan' value skipped
    assert m["TP53"] == "P04637"


def test_missing_columns_raises(tmp_path):
    sc = _write_sidecar(tmp_path, [{"wrong_col": "x", "other": "y"}])
    with pytest.raises(ValueError):   # schema drift -> loud, never a silent {}
        read_resolver_sidecar_map(
            "b", "k", "hgnc_primary_symbol_at_resolution", "native_row_key", local_path=sc)


def test_is_definitively_absent_classifier():
    from botocore.exceptions import ClientError
    absent = ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
    throttle = ClientError({"Error": {"Code": "SlowDown"}}, "GetObject")
    denied = ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")
    assert is_definitively_absent(absent) is True         # genuine gap -> may swallow to data_unavailable
    assert is_definitively_absent(throttle) is False      # transient -> must propagate
    assert is_definitively_absent(denied) is False        # creds/env -> must propagate
    assert is_definitively_absent(ImportError("no pyarrow")) is False   # broken env -> must propagate
