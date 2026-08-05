"""Reader manifest-resolution (2026-08-05): the MC3 products resolve LOCAL-CACHE-FIRST,
then the registered S3 derived manifests (tcga-mc3-hotspot-frequency-v1 /
tcga-mc3-per-sample-maf-v1). This makes ALT-2/ALT-3 portable to a fresh environment instead
of dying on a machine-local cache file.

These test the resolution LOGIC without S3 — a synthetic local parquet (local-first wins) +
an empty catalog (no S3 fallback → data_unavailable). Live S3 resolution is exercised
separately (verified: KRAS/COADREAD byte-identical local vs S3).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from methods.gdc_somatic_hotspot import read as r  # noqa: E402


def _local_aggregate(tmp_path):
    """A minimal local hotspot aggregate (one gene-summary row) so local-first wins."""
    df = pd.DataFrame([{
        "indication": "COADREAD", "gene_symbol": "KRAS",
        "n_samples_in_indication": 100, "n_samples_mutated": 42,
        "overall_mutation_frequency": 0.42,
        "hotspot_protein_change": None, "hotspot_n_samples": None, "hotspot_frequency": None,
    }])
    p = tmp_path / "coadread_mc3_hotspots.parquet"
    df.to_parquet(p)
    return p


def test_local_cache_first_wins(tmp_path, monkeypatch):
    """When the local file exists, the reader uses it (fast path) — never touches S3."""
    # empty catalog so any S3 attempt would fail; local must win so it doesn't matter
    monkeypatch.setattr(r, "DATA_CATALOG", tmp_path / "empty")
    r._allgene_mutation_frequency_null.cache_clear()
    p = _local_aggregate(tmp_path)
    s = r.read_hotspot_summary("KRAS", "COADREAD", aggregate_path=p)
    assert s["overall_mutation_frequency"] == 0.42
    assert s["driver_recurrence_class"] in ("top_1pct", "top_decile", "mid", "bottom_decile")


def test_no_local_no_manifest_is_data_unavailable(tmp_path, monkeypatch):
    """Neither local file NOR a resolvable manifest → data_unavailable (genuinely nowhere)."""
    monkeypatch.setattr(r, "DATA_CATALOG", tmp_path / "empty")   # manifest glob → [] → no S3
    r._allgene_mutation_frequency_null.cache_clear()
    s = r.read_hotspot_summary("KRAS", "COADREAD", aggregate_path=tmp_path / "nope.parquet")
    assert s["driver_recurrence_class"] == "data_unavailable"
    assert s["overall_mutation_frequency"] is None


def test_manifest_s3_path_none_when_manifest_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(r, "DATA_CATALOG", tmp_path / "empty")
    assert r._manifest_s3_path(r._HOTSPOT_FREQUENCY_MANIFEST) is None
    assert r._manifest_s3_path(r._PER_SAMPLE_MAF_MANIFEST) is None


def test_read_product_table_returns_none_when_unresolvable(tmp_path, monkeypatch):
    """The core helper returns None (not raise) when neither local nor S3 is available —
    so every caller degrades gracefully to data_unavailable."""
    monkeypatch.setattr(r, "DATA_CATALOG", tmp_path / "empty")
    out = r._read_product_table(tmp_path / "nope.parquet", r._HOTSPOT_FREQUENCY_MANIFEST,
                                filters=[("indication", "=", "COADREAD")])
    assert out is None
