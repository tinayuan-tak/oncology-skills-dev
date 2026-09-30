"""Regression (burndown P1): depmap_rna_protein_concordance._read_matched_cohort must re-raise a
transient/broken-env failure (honest _live_read_error) instead of returning a silent empty frame
(which would read as "no matched tumors" and dead-axe the concordance verdict). A GENUINE missing
object (NoSuchKey/404, or FileNotFoundError) still yields the empty frame, unchanged.
"""

from __future__ import annotations

import sys
import types

import pytest

from onc_methods.depmap_rna_protein_concordance import read as conc

_COLS = ["patient_id", "gene", "rna_log2tpm", "protein_log2abundance"]


def _fake_s3fs(monkeypatch):
    fake = types.ModuleType("s3fs")
    fake.S3FileSystem = lambda *a, **k: object()
    monkeypatch.setitem(sys.modules, "s3fs", fake)


def test_transient_reraises(monkeypatch):
    _fake_s3fs(monkeypatch)
    import pyarrow.parquet as pq

    monkeypatch.setattr(pq, "read_table", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("SlowDown")))
    with pytest.raises(RuntimeError):
        conc._read_matched_cohort("coad")


def test_genuine_absence_returns_empty_frame(monkeypatch):
    _fake_s3fs(monkeypatch)
    import pyarrow.parquet as pq

    monkeypatch.setattr(pq, "read_table", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("missing")))
    df = conc._read_matched_cohort("coad")
    assert df.empty
    assert list(df.columns) == _COLS


def test_nosuchkey_returns_empty_frame(monkeypatch):
    _fake_s3fs(monkeypatch)
    from botocore.exceptions import ClientError

    err = ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
    import pyarrow.parquet as pq

    monkeypatch.setattr(pq, "read_table", lambda *a, **k: (_ for _ in ()).throw(err))
    df = conc._read_matched_cohort("coad")
    assert df.empty and list(df.columns) == _COLS
