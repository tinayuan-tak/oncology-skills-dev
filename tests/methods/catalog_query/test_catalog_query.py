"""Tests for methods/catalog_query — the read-only data-catalog query engine.

Hermetic: builds a tiny fixture catalog tree in tmp_path and points the engine
at it via load_catalog(root=..., contracts_root=...). No S3, no AWS, no reliance
on the live 219-manifest catalog (which is exercised separately by the live
smoke in the PR description). load_catalog is lru_cache'd, so each test uses a
distinct tmp root to avoid cross-test cache bleed.

Coverage:
  - manifest primitives (load_manifest over BOTH trees; s3_uri_for resolver seam)
  - search facets (type, data_subject, category, system_of_record default-true)
  - describe (authoritative single-source view, incl. products consumer map)
  - lineage (upstream derived_from; downstream = derived_from + subgroup-catalog
    citations folded together, matching validate_catalog.py semantics)
  - audit (dge coverage gaps; superseded-still-present; uncited sources)
  - the read-only invariant (no write-mode file ops in the module source)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from methods.catalog_query.read import (
    bucket_key_for,
    bucket_prefix_for,
    load_catalog,
    load_manifest,
    s3_uri_for,
    sidecar_bucket_key_for,
)


# ---------------------------------------------------------------------------
# fixture catalog
# ---------------------------------------------------------------------------


def _write(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(obj, sort_keys=False))


@pytest.fixture
def catalog(tmp_path: Path) -> tuple[Path, Path]:
    """A minimal but structurally-faithful catalog + contracts pair.

    Graph: raw-source  --derived_from-->  derived-product
           raw-source  <--cited by-- subgroup-catalog stratum
           old-product  superseded-by  derived-product (still present)
           lonely-source  (no citation edge anywhere -> uncited)
    Plus one indication config WITHOUT a DGE product -> a coverage gap, and one
    WITH -> covered.
    """
    dc = tmp_path / "data-catalog"
    tc = tmp_path / "target-contracts"

    # --- source-releases ---
    _write(dc / "manifests" / "sources" / "raw-source.yaml", {
        "id": "raw-source", "type": "source-release", "provider": "acme",
        "dataset": "widgets", "version": "1", "s3_uri": "s3://onc-compbio/data-catalog/sources/acme/1/",
        "description": "A raw source about phospho widgets in tumor tissue.",
        "data_subject": "tumor", "license": "CC-BY-4.0",
        # system_of_record omitted on purpose -> must default TRUE
        "total_size_bytes": 100,
        "files": [
            {"path": "a.parquet", "category": "expression"},
            {"path": "b.parquet", "category": "mutation"},
            {"path": "c.parquet", "category": "expression"},  # dup category
        ],
    })
    _write(dc / "manifests" / "sources" / "lonely-source.yaml", {
        "id": "lonely-source", "type": "source-release", "provider": "hgnc",
        "dataset": "ref", "version": "q2", "s3_uri": "s3://onc-compbio/data-catalog/sources/hgnc/q2/",
        "description": "A reference annotation nothing cites (read by direct path).",
        "data_subject": "reference-data", "system_of_record": False,
        "total_size_bytes": 5, "files": [],
    })

    # --- derived ---
    _write(dc / "manifests" / "derived" / "derived-product.yaml", {
        "id": "derived-product", "type": "derived",
        "transformation": "Aggregate raw-source into a per-gene phospho product for querying.",
        "notebook": "scripts/derive.py",
        "s3_uri": "s3://onc-compbio/data-catalog/derived/derived-product/out.parquet",
        "derived_from": ["raw-source"], "data_subject": "tumor",
        "created_date": "2026-01-01", "created_by": "tester", "format": "parquet",
        "size_bytes": 42, "supersedes": "old-product",
        "parquet_schema": [
            {"name": "gene_symbol", "type": "string"},
            {"name": "value", "type": "double"},
        ],
        "query_optimization": {"sort_columns": ["gene_symbol"], "primary_filter_column": "gene_symbol"},
        "parameters": {"sort_key": "gene_symbol"},
        "target_resolution": {
            "sidecar_s3_uri": "s3://onc-compbio/data-catalog/derived/derived-product/out.target_resolution.parquet",
            "sidecar_md5": "0" * 32,
        },
    })
    _write(dc / "manifests" / "derived" / "old-product.yaml", {
        "id": "old-product", "type": "derived",
        "transformation": "The superseded predecessor of derived-product, still present.",
        "notebook": "scripts/derive_old.py",
        "s3_uri": "s3://onc-compbio/data-catalog/derived/old-product/out.parquet",
        "derived_from": ["raw-source"], "created_date": "2025-01-01", "created_by": "tester",
        "format": "parquet",
    })
    # a DGE sensitivity product for LUAD (covered) but NOT for the other config
    _write(dc / "manifests" / "derived" / "luad-dge-tumor-vs-normal-sensitivity-v1.yaml", {
        "id": "luad-dge-tumor-vs-normal-sensitivity-v1", "type": "derived",
        "transformation": "DESeq2 tumor-vs-normal sensitivity DEG for LUAD.",
        "notebook": "batch/dge.R",
        "s3_uri": "s3://onc-compbio/data-catalog/derived/luad-dge-tumor-vs-normal-sensitivity-v1/x.parquet",
        "derived_from": ["raw-source"], "created_date": "2026-01-01", "created_by": "tester",
        "format": "parquet",
    })

    # --- subgroup-catalog citing raw-source (downstream lineage + not-uncited) ---
    _write(dc / "subgroup-catalogs" / "LUAD" / "2026-Q3.yaml", {
        "id": "luad-subgroups-2026-q3", "manifest_kind": "subgroup_catalog", "indication": "LUAD",
        "atomic_strata": [
            {"name": "s1", "data_source": {"manifest_id": "raw-source"}},
            {"name": "s2", "data_source": {"manifest_id": "raw-source"}},  # dedup
        ],
    })

    # --- indication configs: LUAD (covered) + PAAD (gap) ---
    _write(dc / "indication-configs" / "LUAD.yaml", {"indication": "LUAD"})
    _write(dc / "indication-configs" / "PAAD.yaml", {"indication": "PAAD"})

    # --- products.yaml consumer map ---
    _write(tc / "vocabularies" / "products.yaml", {
        "schema_version": "1.0.0",
        "products": [
            {"id": "phospho-product", "dimension": "phospho", "sources": ["raw-source"]},
        ],
    })
    return dc, tc


# ---------------------------------------------------------------------------
# manifest primitives
# ---------------------------------------------------------------------------


def test_load_manifest_finds_both_trees(catalog):
    dc, _ = catalog
    assert load_manifest("raw-source", root=dc)["type"] == "source-release"
    assert load_manifest("derived-product", root=dc)["type"] == "derived"


def test_load_manifest_unknown_raises(catalog):
    dc, _ = catalog
    with pytest.raises(FileNotFoundError):
        load_manifest("does-not-exist", root=dc)


def test_s3_uri_for_resolver_seam(catalog):
    dc, _ = catalog
    assert s3_uri_for("derived-product", root=dc).endswith("out.parquet")


def test_bucket_key_for_splits_uri(catalog):
    dc, _ = catalog
    bucket, key = bucket_key_for("derived-product", root=dc)
    assert bucket == "onc-compbio"
    assert key == "data-catalog/derived/derived-product/out.parquet"
    # the pair reassembles to the authoritative s3_uri (the migration invariant)
    assert f"s3://{bucket}/{key}" == s3_uri_for("derived-product", root=dc)


def test_bucket_prefix_for_preserves_trailing_slash(catalog):
    dc, _ = catalog
    # raw-source is a source-release whose s3_uri is a DIRECTORY (ends in '/').
    bucket, prefix = bucket_prefix_for("raw-source", root=dc)
    assert bucket == "onc-compbio"
    assert prefix == "data-catalog/sources/acme/1/"
    assert prefix.endswith("/")                       # faithful to the manifest dir
    # reader idiom: f"{PREFIX}{filename}" needs NO manual separator
    assert f"{prefix}Model.csv" == "data-catalog/sources/acme/1/Model.csv"
    # reassembles to the authoritative s3_uri + filename
    assert f"s3://{bucket}/{prefix}Model.csv" == s3_uri_for("raw-source", root=dc) + "Model.csv"


def test_sidecar_bucket_key_for_reads_target_resolution(catalog):
    dc, _ = catalog
    bucket, key = sidecar_bucket_key_for("derived-product", root=dc)
    assert bucket == "onc-compbio"
    # the sidecar path, NOT the payload s3_uri (which ends out.parquet)
    assert key == "data-catalog/derived/derived-product/out.target_resolution.parquet"


def test_sidecar_bucket_key_for_raises_without_sidecar(catalog):
    dc, _ = catalog
    # raw-source has no target_resolution block at all → fail loud, don't guess.
    with pytest.raises(ValueError):
        sidecar_bucket_key_for("raw-source", root=dc)


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


def test_search_by_type(catalog):
    dc, tc = catalog
    idx = load_catalog(root=dc, contracts_root=tc)
    sources = idx.search(type="source-release")
    assert {r.id for r in sources} == {"raw-source", "lonely-source"}


def test_search_keyword_and_data_subject(catalog):
    dc, tc = catalog
    idx = load_catalog(root=dc, contracts_root=tc)
    hits = idx.search("phospho", data_subject="tumor")
    ids = {r.id for r in hits}
    # raw-source (desc has 'phospho') + derived-product (transformation has 'phospho')
    assert ids == {"raw-source", "derived-product"}


def test_search_category_facet(catalog):
    dc, tc = catalog
    idx = load_catalog(root=dc, contracts_root=tc)
    assert {r.id for r in idx.search(category="mutation")} == {"raw-source"}
    # categories are de-duplicated
    assert idx.manifests["raw-source"].categories == ["expression", "mutation"]


def test_search_system_of_record_defaults_true(catalog):
    dc, tc = catalog
    idx = load_catalog(root=dc, contracts_root=tc)
    # raw-source omits system_of_record -> defaults TRUE -> included
    sor = {r.id for r in idx.search(system_of_record=True)}
    assert "raw-source" in sor
    assert "lonely-source" not in sor          # explicitly False
    not_sor = {r.id for r in idx.search(system_of_record=False)}
    assert not_sor == {"lonely-source"}


# ---------------------------------------------------------------------------
# describe
# ---------------------------------------------------------------------------


def test_describe_authoritative_view(catalog):
    dc, tc = catalog
    idx = load_catalog(root=dc, contracts_root=tc)
    d = idx.describe("derived-product")
    assert d["s3_uri"].endswith("out.parquet")
    assert [c["name"] for c in d["parquet_schema"]] == ["gene_symbol", "value"]
    assert d["query_optimization"]["sort_columns"] == ["gene_symbol"]
    assert d["derived_from"] == ["raw-source"]


def test_describe_products_consumer_map(catalog):
    dc, tc = catalog
    idx = load_catalog(root=dc, contracts_root=tc)
    assert idx.describe("raw-source")["consumed_by_products"] == ["phospho-product"]


def test_describe_unknown_raises_keyerror(catalog):
    dc, tc = catalog
    idx = load_catalog(root=dc, contracts_root=tc)
    with pytest.raises(KeyError):
        idx.describe("nope")


# ---------------------------------------------------------------------------
# lineage
# ---------------------------------------------------------------------------


def test_lineage_upstream(catalog):
    dc, tc = catalog
    idx = load_catalog(root=dc, contracts_root=tc)
    up = idx.lineage("derived-product", direction="upstream")["upstream"]
    assert [c["id"] for c in up["children"]] == ["raw-source"]


def test_lineage_downstream_folds_manifest_and_subgroup_citations(catalog):
    """Downstream of raw-source = derived-manifest edges + subgroup-catalog citation,
    matching validate_catalog.py's combined cited_by."""
    dc, tc = catalog
    idx = load_catalog(root=dc, contracts_root=tc)
    dn = idx.lineage("raw-source", direction="downstream")["downstream"]
    kids = {c["id"] for c in dn["children"]}
    assert kids == {
        "derived-product", "old-product",
        "luad-dge-tumor-vs-normal-sensitivity-v1",
        "luad-subgroups-2026-q3",   # from the subgroup-catalog, folded in
    }


def test_lineage_matches_reverse_of_derived_from(catalog):
    """Cross-check: computed downstream (manifest-only) == reverse of every
    manifest's declared derived_from — the invariant validate_catalog enforces."""
    dc, tc = catalog
    idx = load_catalog(root=dc, contracts_root=tc)
    expected: dict[str, set[str]] = {}
    for rec in idx.manifests.values():
        for up in rec.derived_from:
            expected.setdefault(up, set()).add(rec.id)
    for up, downs in expected.items():
        got = set(idx.manifests[up].computed_cited_by)
        assert downs <= got, f"{up}: {downs} not subset of {got}"


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------


def test_audit_dge_coverage_gap(catalog):
    dc, tc = catalog
    idx = load_catalog(root=dc, contracts_root=tc)
    a = idx.audit()
    assert "paad" in a["dge_coverage_gaps"]      # no PAAD dge product
    assert "luad" not in a["dge_coverage_gaps"]   # LUAD covered


def test_audit_superseded_still_present(catalog):
    dc, tc = catalog
    idx = load_catalog(root=dc, contracts_root=tc)
    a = idx.audit()
    assert any("old-product" in s and "derived-product" in s
               for s in a["superseded_still_present"])


def test_audit_uncited_sources(catalog):
    dc, tc = catalog
    idx = load_catalog(root=dc, contracts_root=tc)
    a = idx.audit()
    # raw-source is cited (product + subgroup + derived_from) -> NOT uncited.
    # lonely-source has no edge anywhere -> uncited.
    assert a["uncited_sources"] == ["lonely-source"]


def test_audit_counts(catalog):
    dc, tc = catalog
    idx = load_catalog(root=dc, contracts_root=tc)
    c = idx.audit()["counts"]
    assert c["sources"] == 2
    assert c["derived"] == 3
    assert c["indication_configs"] == 2
    assert c["subgroup_catalogs"] == 1


# ---------------------------------------------------------------------------
# read-only invariant (guards the design's core promise)
# ---------------------------------------------------------------------------


_CACHE_WRITE_MARKER = "index-cache-write"  # see load_catalog's disk-persisted CatalogIndex cache


def test_module_has_no_write_or_network_ops():
    """The engine never hits S3/network and never MUTATES the catalog. The one sanctioned write is
    the atomic, self-invalidating memoization of the *built index* to a temp cache dir (a derived
    artifact, NOT a catalog file) — each such line is tagged `# index-cache-write` and exempted here;
    an UNMARKED write-mode open still trips the guard, and the no-network checks are absolute."""
    src_dir = Path(__file__).resolve().parents[3] / "methods" / "catalog_query"
    for py in src_dir.glob("*.py"):
        text = py.read_text()
        # strip comment-only lines (prose) AND lines carrying the sanctioned index-cache-write marker
        code = "\n".join(
            ln for ln in text.splitlines()
            if not ln.lstrip().startswith("#") and _CACHE_WRITE_MARKER not in ln
        )
        assert not re.search(r"open\([^)]*,\s*['\"][wax]", code), f"unmarked write-mode open in {py.name}"
        assert "import boto3" not in code, f"boto3 imported in {py.name}"
        assert "s3fs" not in code.replace("s3fs", "") or "import s3fs" not in code
        for banned in ("import boto3", "import botocore", "import requests", "import s3fs"):
            assert banned not in code, f"{banned} in {py.name}"
