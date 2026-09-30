"""onsides_adverse_event._read_onsides_row must distinguish a GENUINE absent object (NoSuchKey/404 or
pyarrow FileNotFoundError -> None -> no_mapped_drug_ade coverage gap) from a transient/creds/broken-env
failure (-> re-raise, so the live-read seam surfaces an honest error instead of a false "no ADE" for a
live gene). Mirrors methods/dgidb_drug_gene/test_absence_discipline.py.
"""

from __future__ import annotations

import pytest

from onc_methods.onsides_adverse_event import read as onsides


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
        onsides._read_onsides_row("EGFR")
    with pytest.raises(RuntimeError):
        onsides.read_target_summary("EGFR")


def test_nosuchkey_returns_none_and_coverage_gap(monkeypatch):
    _stub_s3(monkeypatch)
    from botocore.exceptions import ClientError

    err = ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
    import pyarrow.parquet as pq

    monkeypatch.setattr(pq, "read_table", lambda *a, **k: (_ for _ in ()).throw(err))
    assert onsides._read_onsides_row("EGFR") is None
    s = onsides.read_target_summary("EGFR")
    assert s["onsides_ade_class"] == "no_mapped_drug_ade"


def test_filenotfound_returns_none(monkeypatch):
    _stub_s3(monkeypatch)
    import pyarrow.parquet as pq

    monkeypatch.setattr(pq, "read_table", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("missing object")))
    assert onsides._read_onsides_row("EGFR") is None
