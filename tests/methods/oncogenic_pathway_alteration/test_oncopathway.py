"""oncogenic_pathway_alteration — hermetic tests (synthetic per-(pathway x indication) frame, no S3)."""

from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from methods.oncogenic_pathway_alteration import read as opa  # noqa: E402


def _fake():
    import pandas as pd

    return pd.DataFrame(
        [
            {
                "indication": "COAD",
                "pathway": "WNT",
                "n_samples": 300,
                "frac_altered": 0.90,
                "pathway_alteration_class": "frequently_altered",
            },
            {
                "indication": "READ",
                "pathway": "WNT",
                "n_samples": 100,
                "frac_altered": 0.86,
                "pathway_alteration_class": "frequently_altered",
            },
            {
                "indication": "COAD",
                "pathway": "RTK RAS",
                "n_samples": 300,
                "frac_altered": 0.75,
                "pathway_alteration_class": "frequently_altered",
            },
            {
                "indication": "READ",
                "pathway": "RTK RAS",
                "n_samples": 100,
                "frac_altered": 0.70,
                "pathway_alteration_class": "frequently_altered",
            },
            {
                "indication": "COAD",
                "pathway": "NOTCH",
                "n_samples": 300,
                "frac_altered": 0.05,
                "pathway_alteration_class": "rarely_altered",
            },
            {
                "indication": "READ",
                "pathway": "NOTCH",
                "n_samples": 100,
                "frac_altered": 0.04,
                "pathway_alteration_class": "rarely_altered",
            },
        ]
    )


def test_composite_pooling_and_class(monkeypatch):
    monkeypatch.setattr(opa, "_load_product", _fake)
    monkeypatch.setattr(opa, "_gene_pathways", lambda t: ["RTK RAS"] if t == "KRAS" else [])
    out = opa.read_oncogenic_pathway_alteration(target="KRAS", indication="COADREAD")
    assert "WNT" in out["frequently_altered_pathways"]  # pooled 0.90/0.86 → still frequent
    assert "RTK RAS" in out["frequently_altered_pathways"]
    assert "NOTCH" not in out["frequently_altered_pathways"]  # 0.05 → rarely
    assert out["pooled_from"] == ["COAD", "READ"]
    assert out["target_pathway_membership"] == ["RTK RAS"]
    # target's pathway alteration frequency surfaced
    assert any(r["pathway"] == "RTK RAS" for r in out["target_pathway_alteration"])


def test_unmapped_indication(monkeypatch):
    monkeypatch.setattr(opa, "_load_product", _fake)
    assert opa.read_oncogenic_pathway_alteration(indication="ZZZ")["oncogenic_pathway_class"] == "data_unavailable"


def test_missing_indication():
    assert opa.read_oncogenic_pathway_alteration(indication=None)["oncogenic_pathway_class"] == "data_unavailable"


# --- resolver seam (hard-coded S3 URIs now resolve via catalog_query.s3_uri_for) -------------------


def _patch_resolver(monkeypatch, mapping):
    import methods.catalog_query.read as cq

    monkeypatch.setattr(cq, "s3_uri_for", lambda mid, **kw: mapping[mid])


def test_derived_uri_resolves_via_manifest(monkeypatch):
    _patch_resolver(
        monkeypatch,
        {
            "oncogenic-pathway-alteration-per-indication-v1": "s3://b/data-catalog/derived/oncogenic-pathway-alteration-per-indication-v1/oncopathway_per_indication.parquet"
        },
    )
    assert opa._resolve_derived_uri().endswith("/oncopathway_per_indication.parquet")
    assert opa.DERIVED_MANIFEST_ID == "oncogenic-pathway-alteration-per-indication-v1"


def test_source_mmc_uris_append_filename_to_directory(monkeypatch):
    from methods.oncogenic_pathway_alteration import cli as opc

    _patch_resolver(
        monkeypatch,
        {
            "sanchez-vega-oncogenic-pathways-2018": "s3://b/data-catalog/sources/sanchez-vega-oncogenic-pathways-2018/snapshot-2026-08-10/"
        },
    )
    mmc4 = opc._join(opc._resolve_src_dir(), opc._MMC4_FILE)
    assert mmc4.endswith("/snapshot-2026-08-10/Sanchez-Vega_2018_mmc4_genomic_alteration_matrices.xlsx")
    assert "//Sanchez" not in mmc4.replace("s3://", "")  # no double slash


def test_bridge_uri_resolves_to_clinical_manifest(monkeypatch):
    """The barcode->cancer-type bridge file is documented in gdc-pancanatlas-clinical-2018
    (four gdc-pancanatlas manifests share the dir; clinical is the one that lists this file)."""
    from methods.oncogenic_pathway_alteration import cli as opc

    _patch_resolver(
        monkeypatch,
        {"gdc-pancanatlas-clinical-2018": "s3://b/data-catalog/sources/gdc-pancanatlas/2018-snapshot-2026-06-27/"},
    )
    assert opc.BRIDGE_SOURCE_MANIFEST_ID == "gdc-pancanatlas-clinical-2018"
    assert opc._resolve_bridge_uri().endswith("/merged_sample_quality_annotations.tsv")


def test_resolver_import_is_call_time(monkeypatch):
    import inspect

    assert "from methods.catalog_query.read import s3_uri_for" in inspect.getsource(opa._resolve_derived_uri)
