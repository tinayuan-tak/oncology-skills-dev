"""tcga_gtex_tpm_quantiles.marrow — the primary-marrow substrate reader's three states.

The load-bearing property is the THREE-WAY absence discipline. A safety denominator that silently
scores a missing organ as 0 reports a CLEAN window on the organ whose toxicity (myelosuppression) is
dose-limiting for payload ADCs and myeloid TCEs. So this module must distinguish:
  value found          -> hpa_primary_marrow
  DEFINITIVE absence   -> gene_absent_from_hpa_consensus  (non-coding locus; HPA is protein-coding)
  TRANSIENT failure    -> unavailable                     (network / manifest / vocabulary drift)
and must NEVER return 0.0 for either absence.
"""

from __future__ import annotations

import pytest

from onc_methods.tcga_gtex_tpm_quantiles import marrow


@pytest.fixture(autouse=True)
def _clean_cache():
    marrow._reset_cache_for_tests()
    yield
    marrow._reset_cache_for_tests()


def _inject(table: dict) -> None:
    """Seed the process cache so no S3 read happens (these tests are offline)."""
    marrow._TABLE = dict(table)
    marrow._LOAD_ERROR = None


def test_value_found_is_returned_with_the_primary_substrate_token():
    _inject({"CLEC12A": 75.3})
    tpm, substrate, note = marrow.primary_marrow_tpm("CLEC12A")
    assert tpm == pytest.approx(75.3)
    assert substrate == marrow.SUBSTRATE_PRIMARY
    assert note is None


def test_symbol_lookup_is_case_and_whitespace_insensitive():
    _inject({"CD33": 30.6})
    assert marrow.primary_marrow_tpm("  cd33 ")[0] == pytest.approx(30.6)


def test_definitive_absence_returns_none_not_zero():
    _inject({"CD33": 30.6})
    tpm, substrate, note = marrow.primary_marrow_tpm("SOME-AS1")
    assert tpm is None  # NOT 0.0 — a zero marrow value reads as a clean window
    assert substrate == marrow.SUBSTRATE_GENE_ABSENT
    assert "SOME-AS1" in note


def test_read_failure_returns_unavailable_not_zero_and_not_gene_absent(monkeypatch):
    """A broken environment must NOT be reported as biology. Manifest resolution is inside the
    module's try block precisely so this degrades instead of raising through the dispatcher.

    A bare RuntimeError from catalog resolution is treated as a DEFINITIVE config miss (a
    renamed/removed manifest raises here) → plain `unavailable`, not the transient flavour."""

    def _boom(_manifest_id):
        raise RuntimeError("catalog unreachable")

    monkeypatch.setattr(marrow, "bucket_prefix_for", _boom)
    tpm, substrate, note = marrow.primary_marrow_tpm("CD33")
    assert tpm is None
    assert substrate == marrow.SUBSTRATE_UNAVAILABLE
    assert substrate != marrow.SUBSTRATE_GENE_ABSENT
    assert substrate != marrow.SUBSTRATE_UNAVAILABLE_TRANSIENT
    assert "catalog unreachable" in note


def test_transient_network_failure_is_flagged_unavailable_transient(monkeypatch):
    """#796: a TRANSIENT outage (network/creds/throttle/5xx/parse) must be DISTINGUISHABLE from a
    definitive config miss, so the selectivity clamp can withhold a marrow-plausible selective call
    rather than silently drop the essential-window KILL. A builtin ConnectionError is transient."""

    def _boom(_manifest_id):
        raise ConnectionError("connection reset by peer")

    monkeypatch.setattr(marrow, "bucket_prefix_for", _boom)
    tpm, substrate, note = marrow.primary_marrow_tpm("CD33")
    assert tpm is None
    assert substrate == marrow.SUBSTRATE_UNAVAILABLE_TRANSIENT
    assert substrate != marrow.SUBSTRATE_UNAVAILABLE
    assert substrate != marrow.SUBSTRATE_GENE_ABSENT


def test_botocore_endpoint_connection_error_is_transient(monkeypatch):
    from botocore.exceptions import EndpointConnectionError

    def _boom(_manifest_id):
        raise EndpointConnectionError(endpoint_url="https://s3.amazonaws.com")

    monkeypatch.setattr(marrow, "bucket_prefix_for", _boom)
    assert marrow.primary_marrow_tpm("CD33")[1] == marrow.SUBSTRATE_UNAVAILABLE_TRANSIENT


def test_missing_credentials_is_transient(monkeypatch):
    """An expired/absent role is an environment fault, not biology — recoverable on re-run."""
    from botocore.exceptions import NoCredentialsError

    def _boom(_manifest_id):
        raise NoCredentialsError()

    monkeypatch.setattr(marrow, "bucket_prefix_for", _boom)
    assert marrow.primary_marrow_tpm("CD33")[1] == marrow.SUBSTRATE_UNAVAILABLE_TRANSIENT


def test_client_error_5xx_is_transient_but_4xx_is_definitive(monkeypatch):
    """A boto ClientError throttling/5xx is transient; a 4xx (NoSuchKey/AccessDenied) is a
    DEFINITIVE absence/config state and keeps the plain `unavailable`."""
    from botocore.exceptions import ClientError

    def _server_error(_manifest_id):
        raise ClientError(
            {"Error": {"Code": "InternalError"}, "ResponseMetadata": {"HTTPStatusCode": 503}},
            "GetObject",
        )

    monkeypatch.setattr(marrow, "bucket_prefix_for", _server_error)
    assert marrow.primary_marrow_tpm("CD33")[1] == marrow.SUBSTRATE_UNAVAILABLE_TRANSIENT

    marrow._reset_cache_for_tests()

    def _not_found(_manifest_id):
        raise ClientError(
            {"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
            "GetObject",
        )

    monkeypatch.setattr(marrow, "bucket_prefix_for", _not_found)
    assert marrow.primary_marrow_tpm("CD33")[1] == marrow.SUBSTRATE_UNAVAILABLE


def test_definitive_states_keep_plain_unavailable(monkeypatch):
    """The tissue-vocabulary-drift (`bm.empty`) path is DEFINITIVE, not transient."""
    import io

    import pandas as pd

    tsv = "Gene name\tTissue\tnTPM\nCD33\tliver\t1.0\n"

    class _Body:
        def read(self):
            return tsv.encode()

    class _Client:
        def get_object(self, Bucket, Key):  # noqa: N803
            return {"Body": _Body()}

    class _Session:
        def __init__(self, **_kw):
            pass

        def client(self, _name):
            return _Client()

    import boto3

    real_read_csv = pd.read_csv
    monkeypatch.setattr(boto3, "Session", _Session)
    monkeypatch.setattr(pd, "read_csv", lambda *a, **k: real_read_csv(io.StringIO(tsv), sep="\t"))  # noqa: ARG005
    assert marrow.primary_marrow_tpm("CD33")[1] == marrow.SUBSTRATE_UNAVAILABLE


def test_failure_is_cached_so_a_panel_run_does_not_retry_per_gene(monkeypatch):
    calls = []

    def _boom(_manifest_id):
        calls.append(1)
        raise RuntimeError("nope")

    monkeypatch.setattr(marrow, "bucket_prefix_for", _boom)
    for _ in range(5):
        assert marrow.primary_marrow_tpm("CD33")[1] == marrow.SUBSTRATE_UNAVAILABLE
    assert len(calls) == 1


def test_empty_tissue_slice_is_a_failure_not_a_silent_all_absent(monkeypatch):
    """If HPA renames or drops the `bone marrow` label, every gene would look definitively absent —
    a substrate-wide outage disguised as 20,000 individually missing genes. Must be `unavailable`."""
    import io

    import pandas as pd

    tsv = "Gene name\tTissue\tnTPM\nCD33\tliver\t1.0\n"

    class _Body:
        def read(self):
            return tsv.encode()

    class _Client:
        def get_object(self, Bucket, Key):  # noqa: N803 — boto3 kwarg names
            return {"Body": _Body()}

    class _Session:
        def __init__(self, **_kw):
            pass

        def client(self, _name):
            return _Client()

    import boto3

    real_read_csv = pd.read_csv
    monkeypatch.setattr(boto3, "Session", _Session)
    monkeypatch.setattr(
        pd,
        "read_csv",
        lambda *a, **k: real_read_csv(io.StringIO(tsv), sep="\t"),  # noqa: ARG005
    )
    tpm, substrate, note = marrow.primary_marrow_tpm("CD33")
    assert tpm is None
    assert substrate == marrow.SUBSTRATE_UNAVAILABLE
    assert "bone marrow" in note


def test_substrate_provenance_constants_are_declared():
    """The window card emits these verbatim; they are the only record of what the denominator is."""
    assert marrow.MARROW_SUBSTRATE_ID == "hpa-rna-tissue-consensus-v25-1:bone marrow"
    assert marrow.MARROW_ORGAN_LABEL == "BONE_MARROW_PRIMARY"
    # the measured HPA/GTEx offset is DOCUMENTED but NOT applied; pin it so a silent rescale can't
    # be introduced without changing this number and its docstring justification together.
    assert marrow.MARROW_PLATFORM_OFFSET_MEDIAN == pytest.approx(1.19)
