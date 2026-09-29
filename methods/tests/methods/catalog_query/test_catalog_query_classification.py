"""PR-5: merged classification-view filters in the catalog-query engine.

Hermetic: a tiny catalog with (a) a manifest carrying a curated `classification:` block and
(b) a manifest with NO block but an inferred dataset-intelligence.json profile. Pins that the
scientific facets (indication / measurement_class / grain / sample_type / stage / genome_build /
license_class) match the MERGED view — curated block authoritative, profile as fallback — and
that describe()'s enrichment tags each field manifest|inferred.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from methods.catalog_query.read import load_catalog


def _write(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(obj, sort_keys=False))


@pytest.fixture
def catalog(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("CATALOG_INDEX_CACHE", "0")  # no disk-cache bleed across tmp roots
    dc = tmp_path / "data-catalog"

    # (a) curated: authoritative classification block on the manifest
    _write(
        dc / "manifests" / "derived" / "curated-prod-v1.yaml",
        {
            "id": "curated-prod-v1",
            "type": "derived",
            "s3_uri": "s3://onc-compbio/data-catalog/derived/curated-prod-v1/x.parquet",
            "transformation": "a curated derived product for the merged-view test.",
            "derived_from": ["some-src"],
            "files": [
                {"path": "a.bam", "format": "bam", "category": "expression"},
                {"path": "b.parquet", "format": "parquet", "category": "expression"},
            ],
            "classification": {
                "indications": ["COADREAD"],
                "measurement_class": "bulk_rna",
                "measurement_type": "tumor_vs_normal_selectivity",
                "platform": "Illumina NovaSeq",
                "molecular_grain": "gene",
                "sample_type": ["patient-tumor", "patient-normal"],
                "analytical_stage": "summarized",
                "reference_genome": "GRCh38",
                "license_class": "public-open",
            },
        },
    )
    # (b) inferred: NO block; enrichment comes from the dataset-intelligence profile
    _write(
        dc / "manifests" / "sources" / "inferred-src.yaml",
        {
            "id": "inferred-src",
            "type": "source-release",
            "provider": "geo",
            "dataset": "lung sc",
            "version": "1",
            "s3_uri": "s3://onc-compbio/data-catalog/sources/geo/1/",
            "description": "A single-cell lung dataset with no curated classification block.",
            "data_subject": "tumor",
        },
    )
    profiles = [
        {
            "manifest_id": "inferred-src",
            "measurement": {
                "measurement_class": {"value": "scrna", "source": "inferred"},
                "analytical_stage": {"value": "processed", "source": "inferred"},
                "reference_genome": {"value": None, "source": "n/r"},
            },
            "biology": {
                "indications": {"value": ["NSCLC"], "source": "inferred"},
                "sample_type": {"value": ["patient-tumor"], "source": "inferred"},
            },
            "usage": {"molecular_grain": "single_cell", "aggregation_recommendation": "use_individual"},
            "quality": {"license_class": ""},
        }
    ]
    intel = dc / "inventories" / "dataset-intelligence.json"
    intel.parent.mkdir(parents=True, exist_ok=True)
    intel.write_text(json.dumps(profiles))
    return dc


def test_curated_measurement_class_matches(catalog):
    idx = load_catalog(root=catalog, contracts_root=catalog / "nope")
    hits = {r.id for r in idx.search(measurement_class="bulk_rna")}
    assert hits == {"curated-prod-v1"}


def test_inferred_measurement_class_matches_via_profile(catalog):
    idx = load_catalog(root=catalog, contracts_root=catalog / "nope")
    hits = {r.id for r in idx.search(measurement_class="scrna")}
    assert hits == {"inferred-src"}


def test_indication_membership_both_sources(catalog):
    idx = load_catalog(root=catalog, contracts_root=catalog / "nope")
    assert {r.id for r in idx.search(indication="COADREAD")} == {"curated-prod-v1"}
    assert {r.id for r in idx.search(indication="NSCLC")} == {"inferred-src"}


def test_grain_and_sample_type_and_stage(catalog):
    idx = load_catalog(root=catalog, contracts_root=catalog / "nope")
    assert {r.id for r in idx.search(grain="gene")} == {"curated-prod-v1"}
    assert {r.id for r in idx.search(grain="single_cell")} == {"inferred-src"}
    # both carry patient-tumor (curated list + inferred list)
    assert {r.id for r in idx.search(sample_type="patient-tumor")} == {"curated-prod-v1", "inferred-src"}
    assert {r.id for r in idx.search(stage="summarized")} == {"curated-prod-v1"}
    assert {r.id for r in idx.search(genome_build="GRCh38")} == {"curated-prod-v1"}
    assert {r.id for r in idx.search(license_class="public-open")} == {"curated-prod-v1"}


def test_filters_and_together(catalog):
    idx = load_catalog(root=catalog, contracts_root=catalog / "nope")
    assert {r.id for r in idx.search(indication="COADREAD", measurement_class="bulk_rna")} == {"curated-prod-v1"}
    # contradictory facets -> empty
    assert idx.search(indication="COADREAD", measurement_class="scrna") == []


def test_describe_enrichment_provenance(catalog):
    idx = load_catalog(root=catalog, contracts_root=catalog / "nope")
    cur = idx.describe("curated-prod-v1")["enrichment"]
    # measurement_class is set-capable -> always a list in the merged view
    assert cur["measurement_class"] == {"value": ["bulk_rna"], "source": "manifest"}
    assert cur["indications"]["source"] == "manifest"
    inf = idx.describe("inferred-src")["enrichment"]
    assert inf["measurement_class"] == {"value": ["scrna"], "source": "inferred"}
    assert inf["molecular_grain"]["source"] == "inferred"
    # curated block echoed verbatim under "classification"
    assert idx.describe("curated-prod-v1")["classification"]["measurement_class"] == "bulk_rna"
    assert idx.describe("inferred-src")["classification"] == {}


def test_curated_block_beats_profile(tmp_path: Path, monkeypatch):
    """If a manifest has BOTH a curated field and a (different) inferred profile value, curated wins."""
    monkeypatch.setenv("CATALOG_INDEX_CACHE", "0")
    dc = tmp_path / "dc"
    _write(
        dc / "manifests" / "derived" / "both-v1.yaml",
        {
            "id": "both-v1",
            "type": "derived",
            "s3_uri": "s3://onc-compbio/data-catalog/derived/both-v1/x.parquet",
            "transformation": "curated block plus a conflicting inferred profile.",
            "derived_from": ["s"],
            "classification": {"measurement_class": "bulk_rna"},
        },
    )
    intel = dc / "inventories" / "dataset-intelligence.json"
    intel.parent.mkdir(parents=True, exist_ok=True)
    intel.write_text(json.dumps([{"manifest_id": "both-v1", "measurement": {"measurement_class": {"value": "scrna"}}}]))
    idx = load_catalog(root=dc, contracts_root=dc / "nope")
    assert {r.id for r in idx.search(measurement_class="bulk_rna")} == {"both-v1"}
    assert idx.search(measurement_class="scrna") == []  # curated overrides the inferred scrna


# ---- Tier-1: new facets, multi-value, facet discovery, describe expansion ----


def test_multivalue_or_indication(catalog):
    idx = load_catalog(root=catalog, contracts_root=catalog / "nope")
    assert {r.id for r in idx.search(indication=["COADREAD", "NSCLC"])} == {"curated-prod-v1", "inferred-src"}


def test_measurement_type_and_platform_facets(catalog):
    idx = load_catalog(root=catalog, contracts_root=catalog / "nope")
    assert {r.id for r in idx.search(measurement_type="tumor_vs_normal_selectivity")} == {"curated-prod-v1"}
    assert {r.id for r in idx.search(platform="novaseq")} == {"curated-prod-v1"}  # substring, case-insensitive


def test_file_format_facet(catalog):
    idx = load_catalog(root=catalog, contracts_root=catalog / "nope")
    assert {r.id for r in idx.search(file_format="bam")} == {"curated-prod-v1"}
    assert idx.search(file_format="fastq") == []


def test_aggregation_facet_from_profile(catalog):
    idx = load_catalog(root=catalog, contracts_root=catalog / "nope")
    assert {r.id for r in idx.search(aggregation="use_individual")} == {"inferred-src"}


def test_facet_values_counts(catalog):
    idx = load_catalog(root=catalog, contracts_root=catalog / "nope")
    assert dict(idx.facet_values("measurement_class")) == {"bulk_rna": 1, "scrna": 1}
    assert dict(idx.facet_values("indications")) == {"COADREAD": 1, "NSCLC": 1}


def test_describe_exposes_formats_and_aggregation(catalog):
    idx = load_catalog(root=catalog, contracts_root=catalog / "nope")
    cur = idx.describe("curated-prod-v1")
    assert set(cur["file_formats"]) == {"bam", "parquet"}
    assert idx.describe("inferred-src")["aggregation_recommendation"] == "use_individual"
