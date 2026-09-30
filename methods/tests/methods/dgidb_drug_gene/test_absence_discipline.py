"""Regression (burndown P1): dgidb_drug_gene._read_dgidb_row must distinguish a GENUINE absent
object (NoSuchKey/404, or pyarrow FileNotFoundError -> None -> no_known_drug_evidence coverage gap,
unchanged) from a transient/creds/broken-env failure (-> re-raise, so the live-read seam surfaces
_live_read_error instead of a false "no known drug" for a live gene).
"""

from __future__ import annotations

import pytest

from onc_methods.dgidb_drug_gene import read as dgidb


def _stub_s3(monkeypatch):
    """Neutralize catalog + S3FileSystem so read_table is the only thing that (mock-)raises."""
    import onc_methods.catalog_query.read as cq

    monkeypatch.setattr(cq, "bucket_key_for", lambda mid: ("bucket", "key"))
    import pyarrow.fs as pafs

    monkeypatch.setattr(pafs, "S3FileSystem", lambda *a, **k: object())


def test_transient_reraises(monkeypatch):
    _stub_s3(monkeypatch)
    import pyarrow.parquet as pq

    monkeypatch.setattr(pq, "read_table", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("SlowDown throttling")))
    with pytest.raises(RuntimeError):
        dgidb._read_dgidb_row("EGFR")
    # and it propagates through the public entrypoint (no swallow):
    with pytest.raises(RuntimeError):
        dgidb.known_drug_tractability_for_gene("EGFR")


def test_nosuchkey_returns_none_and_coverage_gap(monkeypatch):
    _stub_s3(monkeypatch)
    from botocore.exceptions import ClientError

    err = ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
    import pyarrow.parquet as pq

    monkeypatch.setattr(pq, "read_table", lambda *a, **k: (_ for _ in ()).throw(err))
    assert dgidb._read_dgidb_row("EGFR") is None
    s = dgidb.known_drug_tractability_for_gene("EGFR")
    assert s["known_drug_tractability_class"] == "no_known_drug_evidence"


def test_filenotfound_returns_none(monkeypatch):
    _stub_s3(monkeypatch)
    import pyarrow.parquet as pq

    monkeypatch.setattr(pq, "read_table", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("missing object")))
    assert dgidb._read_dgidb_row("EGFR") is None
