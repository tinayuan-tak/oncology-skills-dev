"""Guard: the disk-persisted CatalogIndex cache is BYTE-EQUIVALENT to a fresh build, invalidates on
any input-file change, and NEVER breaks correctness (kill-switch, fail-open, atomic prune).

load_catalog parses ~442 manifest YAMLs on a cold build (~0.85s), which dominates the fixed
post-read pipeline of every skill run. To avoid re-paying that in each fresh process, load_catalog
persists the built index to a pickle keyed by _catalog_signature (a fingerprint over every input
file's path/size/mtime_ns). This test is the safety net that lets that live in the shared loader:
the served index must equal a fresh build, and a stale index must never be served.
"""

from __future__ import annotations

import hashlib
import os

import pytest

from onc_methods.catalog_query.read import (
    DATA_CATALOG,
    TARGET_CONTRACTS,
    _build_catalog_index,
    _catalog_input_files,
    _catalog_signature,
    load_catalog,
)


def _norm(idx):
    """A deep, order-stable projection of a CatalogIndex for equality comparison."""
    return (
        sorted(idx.manifests),
        {
            k: (
                v.id,
                v.type,
                str(v.path),
                tuple(v.derived_from),
                tuple(v.declared_cited_by),
                tuple(v.computed_cited_by),
                tuple(sorted((v.raw or {}).get("_categories", []))),
            )
            for k, v in idx.manifests.items()
        },
        idx.consumers,
        idx.subgroup_citations,
        sorted(idx.indication_configs),
    )


@pytest.fixture()
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALOG_INDEX_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("CATALOG_INDEX_CACHE", raising=False)
    load_catalog.cache_clear()
    yield tmp_path
    load_catalog.cache_clear()


def test_disk_cache_equivalent_to_fresh_build(cache_dir):
    """The index served from the disk pickle equals a fresh (uncached) build, field-for-field."""
    fresh = _build_catalog_index(DATA_CATALOG, TARGET_CONTRACTS)
    load_catalog.cache_clear()
    built = load_catalog(root=DATA_CATALOG, contracts_root=TARGET_CONTRACTS)  # builds + persists
    load_catalog.cache_clear()
    from_disk = load_catalog(root=DATA_CATALOG, contracts_root=TARGET_CONTRACTS)  # unpickles
    assert _norm(built) == _norm(fresh)
    assert _norm(from_disk) == _norm(fresh)
    # exactly one persisted file for this (root, contracts_root)
    assert len(list(cache_dir.glob("catalog-*.pkl"))) == 1


def test_signature_invalidates_on_input_change(cache_dir):
    """Touching any catalog input file (mtime) changes the signature — so a stale index is never
    served — and restoring the mtime restores the signature."""
    sig0 = _catalog_signature(DATA_CATALOG, TARGET_CONTRACTS)
    victim = _catalog_input_files(DATA_CATALOG, TARGET_CONTRACTS)[0]
    orig = victim.stat().st_mtime_ns
    try:
        os.utime(victim, ns=(orig + 1_000_000, orig + 1_000_000))
        assert _catalog_signature(DATA_CATALOG, TARGET_CONTRACTS) != sig0
    finally:
        os.utime(victim, ns=(orig, orig))
    assert _catalog_signature(DATA_CATALOG, TARGET_CONTRACTS) == sig0


def test_stale_pickle_pruned_on_resignature(cache_dir):
    """A signature change persists a new pickle and prunes the stale one — the cache never grows
    unbounded for a single root."""
    load_catalog.cache_clear()
    load_catalog(root=DATA_CATALOG, contracts_root=TARGET_CONTRACTS)
    victim = _catalog_input_files(DATA_CATALOG, TARGET_CONTRACTS)[0]
    orig = victim.stat().st_mtime_ns
    try:
        os.utime(victim, ns=(orig + 2_000_000, orig + 2_000_000))
        load_catalog.cache_clear()
        load_catalog(root=DATA_CATALOG, contracts_root=TARGET_CONTRACTS)
    finally:
        os.utime(victim, ns=(orig, orig))
    assert len(list(cache_dir.glob("catalog-*.pkl"))) == 1


def test_kill_switch_bypasses_disk_cache(cache_dir, monkeypatch):
    """CATALOG_INDEX_CACHE=0 builds fresh and writes NO pickle, still correct."""
    monkeypatch.setenv("CATALOG_INDEX_CACHE", "0")
    load_catalog.cache_clear()
    idx = load_catalog(root=DATA_CATALOG, contracts_root=TARGET_CONTRACTS)
    assert _norm(idx) == _norm(_build_catalog_index(DATA_CATALOG, TARGET_CONTRACTS))
    assert list(cache_dir.glob("catalog-*.pkl")) == []


def test_fail_open_on_corrupt_pickle(cache_dir):
    """A corrupt/incompatible cache file must NOT crash — load_catalog rebuilds from source."""
    sig = _catalog_signature(DATA_CATALOG, TARGET_CONTRACTS)
    rh = hashlib.sha256(f"{DATA_CATALOG}\0{TARGET_CONTRACTS}".encode()).hexdigest()[:8]
    (cache_dir / f"catalog-{rh}-{sig}.pkl").write_bytes(b"not a pickle")
    load_catalog.cache_clear()
    idx = load_catalog(root=DATA_CATALOG, contracts_root=TARGET_CONTRACTS)
    assert _norm(idx) == _norm(_build_catalog_index(DATA_CATALOG, TARGET_CONTRACTS))
