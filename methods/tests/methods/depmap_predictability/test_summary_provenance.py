"""read_predictability stamps provenance (_release_pin + _derived_product_uri) on
EVERY return path.

Regression guard for a cross-repo defect: the skills figure emitter hardcoded a
release pin ("26q1-v2") into the evidence manifest it stamps, so once the reader's
default moved to v4 the manifest claimed the wrong provenance for the data beside
it. The fix is that the reader carries provenance, so a consumer reads it from the
summary instead of hardcoding. These tests pin that the reader actually does so —
on the success path AND both graceful-degradation paths.

No S3: the resolving namespace (methods.depmap_predictability.cli) is monkeypatched,
so the test exercises read.py's own control flow, not the data platform.
"""

from __future__ import annotations

import onc_methods.depmap_predictability.read as rd


def _no_aws(monkeypatch):
    monkeypatch.setattr(rd, "ensure_aws_profile", lambda: None)


def test_success_path_stamps_the_pin_actually_used(monkeypatch):
    _no_aws(monkeypatch)
    # A pin that resolves to a sentinel URI, a fake row, and a summary that does
    # NOT itself carry provenance (proving read.py is what adds it).
    monkeypatch.setattr(rd._cli, "RELEASE_PIN_TO_PARQUET", {"26q1-v4": "s3://bucket/v4.parquet"})
    monkeypatch.setattr(rd._cli, "fetch_predictability_row", lambda uri, tgt: {"gene_symbol": tgt})
    monkeypatch.setattr(rd._cli, "compute_summary", lambda row, tgt: {"predictability_class": "own_omics_driven"})

    out = rd.read_predictability("KRAS", release_pin="26q1-v4")

    assert out["_release_pin"] == "26q1-v4"
    assert out["_derived_product_uri"] == "s3://bucket/v4.parquet"
    # provenance is ADDITIVE — it does not clobber the summary payload
    assert out["predictability_class"] == "own_omics_driven"


def test_non_default_pin_is_reported_not_the_default(monkeypatch):
    # The stamp must reflect the pin the caller PASSED, not DEFAULT_RELEASE_PIN —
    # otherwise a v3 reproducibility read would be mis-stamped as v4.
    _no_aws(monkeypatch)
    monkeypatch.setattr(rd._cli, "RELEASE_PIN_TO_PARQUET", {"26q1-v3": "s3://bucket/v3.parquet"})
    monkeypatch.setattr(rd._cli, "fetch_predictability_row", lambda uri, tgt: {"gene_symbol": tgt})
    monkeypatch.setattr(rd._cli, "compute_summary", lambda row, tgt: {"predictability_class": "unpredictable"})

    out = rd.read_predictability("RPL5", release_pin="26q1-v3")

    assert out["_release_pin"] == "26q1-v3"
    assert out["_derived_product_uri"] == "s3://bucket/v3.parquet"


def test_unknown_pin_path_stamps_pin_and_null_uri(monkeypatch):
    _no_aws(monkeypatch)
    monkeypatch.setattr(rd._cli, "RELEASE_PIN_TO_PARQUET", {"26q1-v4": "s3://bucket/v4.parquet"})

    out = rd.read_predictability("KRAS", release_pin="does-not-exist")

    assert out["_live_read_error"] == "unknown_release_pin"
    assert out["_release_pin"] == "does-not-exist"  # the bad pin the caller asked for
    assert out["_derived_product_uri"] is None  # nothing resolved
    assert out["predictability_class"] == "data_unavailable"


def test_s3_failure_path_stamps_resolved_uri(monkeypatch):
    _no_aws(monkeypatch)
    monkeypatch.setattr(rd._cli, "RELEASE_PIN_TO_PARQUET", {"26q1-v4": "s3://bucket/v4.parquet"})

    def _boom(uri, tgt):
        raise RuntimeError("network down")

    monkeypatch.setattr(rd._cli, "fetch_predictability_row", _boom)

    out = rd.read_predictability("KRAS", release_pin="26q1-v4")

    assert out["_live_read_error"] == "s3_read_failed"
    assert out["_release_pin"] == "26q1-v4"
    assert out["_derived_product_uri"] == "s3://bucket/v4.parquet"  # the pin resolved; the READ failed
