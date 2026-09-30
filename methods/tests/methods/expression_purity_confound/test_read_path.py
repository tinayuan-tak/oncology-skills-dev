"""expression_purity_confound read-path robustness (issue #735).

Covers F5 (last-wins purity collapse → per-case MEAN) and F1 (ProfileNotFound-safe read via the
shared s3_client helper). Fixtures store the RAW sample-level rows / raw TSV bytes and RE-DERIVE the
expected value, so a derived fixture cannot silently pass a regressed collapse.
"""

from __future__ import annotations

from onc_methods.expression_purity_confound import read as purity_read
from onc_methods.expression_purity_confound.read import collapse_purity_by_case

# --- F5: per-case MEAN collapse (not last-wins dict(zip)) ------------------------------------


def test_collapse_uses_mean_not_last_wins():
    # Case A has THREE ABSOLUTE samples (e.g. primary + met + aliquot) with DIFFERING purity given
    # in an order where the last row (0.90) would win under the old dict(zip). Case B is single-row.
    samples = [
        "TCGA-AA-1111-01A",
        "TCGA-AA-1111-06A",
        "TCGA-AA-1111-01B",
        "TCGA-BB-2222-01A",
    ]
    purities = [0.30, 0.60, 0.90, 0.50]

    out = collapse_purity_by_case(samples, purities)

    # re-derived expectation (mean of case A's three rows), not a stored constant
    expected_a = (0.30 + 0.60 + 0.90) / 3
    assert out["TCGA-AA-1111"] == expected_a
    assert out["TCGA-BB-2222"] == 0.50
    # the old last-wins behaviour would have yielded 0.90 for case A — guard against regression
    assert out["TCGA-AA-1111"] != 0.90


def test_collapse_drops_nonnumeric_purity():
    samples = ["TCGA-AA-1111-01A", "TCGA-AA-1111-06A", "TCGA-CC-3333-01A"]
    purities = ["0.40", "not_a_number", "0.70"]

    out = collapse_purity_by_case(samples, purities)

    assert out["TCGA-AA-1111"] == 0.40  # the NaN row dropped, single valid row remains
    assert out["TCGA-CC-3333"] == 0.70


# --- F1: read goes through s3_client (ProfileNotFound-safe) and collapses per case ----------


class _FakeBody:
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data


class _FakeS3Client:
    def __init__(self, tsv_bytes: bytes):
        self._tsv = tsv_bytes
        self.calls = []

    def get_object(self, Bucket, Key):  # noqa: N803 — boto3 kwarg names
        self.calls.append((Bucket, Key))
        return {"Body": _FakeBody(self._tsv)}


def test_load_purity_by_case_uses_s3_client_and_collapses(monkeypatch):
    # RAW TSV bytes with a multi-sample case (same last-wins trap as F5) stored verbatim.
    tsv = ("sample\tpurity\nTCGA-AA-1111-01A\t0.30\nTCGA-AA-1111-06A\t0.90\nTCGA-BB-2222-01A\t0.50\n").encode()
    fake = _FakeS3Client(tsv)

    # Route through the shared helper (F1). If read.py still built a bare boto3 client this would
    # not be exercised; the assertion on `fake.calls` proves s3_client was the read path.
    monkeypatch.setattr(purity_read, "s3_client", lambda *a, **k: fake)
    purity_read._load_purity_by_case.cache_clear()
    try:
        out = purity_read._load_purity_by_case()
    finally:
        purity_read._load_purity_by_case.cache_clear()

    assert fake.calls == [(purity_read.S3_BUCKET, purity_read.ABS_TABLES_KEY)]
    assert out["TCGA-AA-1111"] == (0.30 + 0.90) / 2  # mean, not last-wins 0.90
    assert out["TCGA-BB-2222"] == 0.50


def test_load_purity_by_case_typed_absence_returns_empty(monkeypatch):
    # A genuine NoSuchKey (table absent) must return {} → data_unavailable upstream, NOT crash.
    from botocore.exceptions import ClientError

    class _AbsentS3:
        def get_object(self, Bucket, Key):  # noqa: N803
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")

    monkeypatch.setattr(purity_read, "s3_client", lambda *a, **k: _AbsentS3())
    purity_read._load_purity_by_case.cache_clear()
    try:
        assert purity_read._load_purity_by_case() == {}
    finally:
        purity_read._load_purity_by_case.cache_clear()


def test_load_purity_by_case_env_break_raises(monkeypatch):
    # An access/throttle error is an ENV break — must RAISE (fail loud), never mask as no-data.
    from botocore.exceptions import ClientError

    class _DeniedS3:
        def get_object(self, Bucket, Key):  # noqa: N803
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")

    monkeypatch.setattr(purity_read, "s3_client", lambda *a, **k: _DeniedS3())
    purity_read._load_purity_by_case.cache_clear()
    try:
        try:
            purity_read._load_purity_by_case()
            assert False, "expected ClientError to propagate"
        except ClientError:
            pass
    finally:
        purity_read._load_purity_by_case.cache_clear()
