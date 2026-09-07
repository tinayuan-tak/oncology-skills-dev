"""stemness_index — hermetic tests (synthetic per-indication frame, no S3)."""

from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from methods.stemness_index import read as sr  # noqa: E402


def _fake():
    import pandas as pd

    # pan-cancer median 0.37, q3 0.45 (baked into every row, as the build does)
    return pd.DataFrame(
        [
            {
                "indication": "TGCT",
                "n_samples": 140,
                "median_mrnasi": 0.71,
                "p25_mrnasi": 0.6,
                "p75_mrnasi": 0.8,
                "stemness_class": "stem_high",
                "pan_cancer_median_mrnasi": 0.37,
                "pan_cancer_q3_mrnasi": 0.45,
            },
            {
                "indication": "COAD",
                "n_samples": 300,
                "median_mrnasi": 0.51,
                "p25_mrnasi": 0.4,
                "p75_mrnasi": 0.6,
                "stemness_class": "stem_high",
                "pan_cancer_median_mrnasi": 0.37,
                "pan_cancer_q3_mrnasi": 0.45,
            },
            {
                "indication": "READ",
                "n_samples": 100,
                "median_mrnasi": 0.50,
                "p25_mrnasi": 0.4,
                "p75_mrnasi": 0.6,
                "stemness_class": "stem_high",
                "pan_cancer_median_mrnasi": 0.37,
                "pan_cancer_q3_mrnasi": 0.45,
            },
            {
                "indication": "THCA",
                "n_samples": 450,
                "median_mrnasi": 0.25,
                "p25_mrnasi": 0.2,
                "p75_mrnasi": 0.3,
                "stemness_class": "stem_low",
                "pan_cancer_median_mrnasi": 0.37,
                "pan_cancer_q3_mrnasi": 0.45,
            },
        ]
    )


def test_stem_high_low_relative_to_pancancer(monkeypatch):
    monkeypatch.setattr(sr, "_load_product", _fake)
    assert sr.read_stemness_index(indication="TGCT")["stemness_class"] == "stem_high"  # 0.71 >= q3 0.45
    assert sr.read_stemness_index(indication="THCA")["stemness_class"] == "stem_low"  # 0.25 < median 0.37


def test_composite_pooling(monkeypatch):
    monkeypatch.setattr(sr, "_load_product", _fake)
    out = sr.read_stemness_index(indication="COADREAD")
    assert out["pooled_from"] == ["COAD", "READ"]
    assert out["n_samples"] == 400
    # weighted median ~0.5075 → still >= q3 → stem_high
    assert out["stemness_class"] == "stem_high"


def test_unmapped_and_missing(monkeypatch):
    monkeypatch.setattr(sr, "_load_product", _fake)
    assert sr.read_stemness_index(indication="ZZZ")["stemness_class"] == "data_unavailable"
    assert sr.read_stemness_index(indication=None)["stemness_class"] == "data_unavailable"


# --- resolver seam (hard-coded S3 URIs now resolve via catalog_query.s3_uri_for) -------------------


def _patch_resolver(monkeypatch, mapping):
    import methods.catalog_query.read as cq

    monkeypatch.setattr(cq, "s3_uri_for", lambda mid, **kw: mapping[mid])


def test_derived_uri_resolves_via_manifest(monkeypatch):
    _patch_resolver(
        monkeypatch,
        {
            "stemness-mrnasi-per-indication-v1": "s3://b/data-catalog/derived/stemness-mrnasi-per-indication-v1/stemness_per_indication.parquet"
        },
    )
    assert sr._resolve_derived_uri().endswith("/stemness_per_indication.parquet")
    assert sr.DERIVED_MANIFEST_ID == "stemness-mrnasi-per-indication-v1"


def test_sig_uri_appends_filename_to_companions_manifest(monkeypatch):
    """The mRNAsi signature xlsx is documented in gdc-pancanatlas-companions-2018 (its files: block
    lists it; sibling gdc-pancanatlas manifests share the same directory s3_uri)."""
    from methods.stemness_index import cli as sc

    _patch_resolver(
        monkeypatch,
        {"gdc-pancanatlas-companions-2018": "s3://b/data-catalog/sources/gdc-pancanatlas/2018-snapshot-2026-06-27/"},
    )
    assert sc.SIG_SOURCE_MANIFEST_ID == "gdc-pancanatlas-companions-2018"
    uri = sc._resolve_sig_uri()
    assert uri.endswith("/DNAmethylation_and_RNAexpression_Stemness_Signatures.xlsx")
    assert "//DNAmethylation" not in uri.replace("s3://", "")  # no double slash


def test_expr_uri_resolves_via_manifest(monkeypatch):
    from methods.stemness_index import cli as sc

    _patch_resolver(
        monkeypatch,
        {
            "tcga-tumor-tpm-recount3-long-v1": "s3://b/data-catalog/derived/tcga-tumor-tpm-recount3-long-v1/tcga_tpm_long.parquet"
        },
    )
    assert sc._resolve_expr_uri().endswith("/tcga_tpm_long.parquet")


def test_resolver_import_is_call_time():
    import inspect

    assert "from methods.catalog_query.read import s3_uri_for" in inspect.getsource(sr._resolve_derived_uri)
