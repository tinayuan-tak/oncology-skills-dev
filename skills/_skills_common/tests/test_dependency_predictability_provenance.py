"""The E5 dependency-predictability emitter stamps the manifest with the pin the
DATA carries, not a hardcoded literal.

Regression guard for the cross-repo defect that motivated analysis-methods #672:
this emitter hardcoded release pin "26q1-v2" into the evidence manifest, so once
read_predictability's default moved to 26q1-v4 the manifest mis-labeled the data
beside it. The reader now stamps `_release_pin` / `_derived_product_uri` onto the
summary; this test pins that the emitter READS those rather than a literal — and
that it degrades to the reader's default for a stale summary that predates the
stamp.

No figures are rendered and no S3 is touched: the resolving namespace
(methods.depmap_predictability.cli) is monkeypatched, so we exercise the
emitter's own manifest-provenance control flow.
"""

from __future__ import annotations

from _skills_common._figure_emitters import _dependency


def _patch_cli(monkeypatch, captured, pin_map):
    """Put methods on path, then neutralise every emit helper except manifest,
    which we capture. Returns the real cli module for the caller to assert on."""
    _dependency._ensure_methods_path()
    from methods.depmap_predictability import cli as realcli

    monkeypatch.setattr(realcli, "emit_feature_importance_bar", lambda *a, **k: None)
    monkeypatch.setattr(realcli, "emit_lineage_conditional_panel", lambda *a, **k: None)
    monkeypatch.setattr(realcli, "RELEASE_PIN_TO_PARQUET", pin_map)

    def _capture(target, release_pin, summary, out_dir, parquet_uri):
        captured["release_pin"] = release_pin
        captured["parquet_uri"] = parquet_uri
        return out_dir / "manifest.json"

    monkeypatch.setattr(realcli, "emit_manifest", _capture)
    return realcli


def test_emitter_stamps_the_pin_the_summary_carries(monkeypatch, tmp_path):
    captured = {}
    _patch_cli(monkeypatch, captured, {"26q1-v4": "s3://bucket/v4.parquet"})

    summary = {
        "predictability_class": "own_omics_driven",
        "_release_pin": "26q1-v4",
        "_derived_product_uri": "s3://bucket/v4.parquet",
    }
    _dependency._emit_dependency_predictability(summary, tmp_path, "KRAS", "PANCAN")

    assert captured["release_pin"] == "26q1-v4"
    assert captured["parquet_uri"] == "s3://bucket/v4.parquet"


def test_emitter_reads_a_non_default_pin_from_the_summary(monkeypatch, tmp_path):
    # A reproducibility read pinned to v3 must be stamped as v3, not the default.
    captured = {}
    _patch_cli(monkeypatch, captured, {"26q1-v3": "s3://bucket/v3.parquet"})

    summary = {
        "predictability_class": "unpredictable",
        "_release_pin": "26q1-v3",
        "_derived_product_uri": "s3://bucket/v3.parquet",
    }
    _dependency._emit_dependency_predictability(summary, tmp_path, "RPL5", "PANCAN")

    assert captured["release_pin"] == "26q1-v3"
    assert captured["parquet_uri"] == "s3://bucket/v3.parquet"


def test_emitter_falls_back_to_reader_default_for_a_pre_stamp_summary(monkeypatch, tmp_path):
    # A summary produced before the provenance stamp existed carries neither key;
    # the emitter degrades to the reader's DEFAULT_RELEASE_PIN and re-resolves the
    # URI, rather than emitting a stale hardcoded pin. The default depends on which
    # analysis-methods the caller resolves (skills CI pins an OLDER sibling whose
    # default is still 26q1-v3), so key the fixture map by the ACTUAL default rather
    # than a hardcoded literal — the fallback contract is "the co-located reader's
    # default", whatever version that happens to be.
    _dependency._ensure_methods_path()
    from methods.depmap_predictability.read import DEFAULT_RELEASE_PIN

    default_uri = f"s3://bucket/{DEFAULT_RELEASE_PIN}.parquet"
    captured = {}
    _patch_cli(monkeypatch, captured, {DEFAULT_RELEASE_PIN: default_uri})

    summary = {"predictability_class": "own_omics_driven"}  # no provenance keys
    _dependency._emit_dependency_predictability(summary, tmp_path, "KRAS", "PANCAN")

    assert captured["release_pin"] == DEFAULT_RELEASE_PIN
    assert captured["parquet_uri"] == default_uri
