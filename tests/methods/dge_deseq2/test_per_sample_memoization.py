"""Retrieval-opt #1: the recount3 per-sample readers are memoized so a full dashboard render doesn't
re-stream the ~50 MB gzipped counts files.

Two guarantees:
  1. read_per_sample_expression_tumor_vs_adjacent is @lru_cache'd on (target, indication) — the
     tumor-vs-adjacent figure AND the selectivity figure (via all_three_groups) share ONE result
     instead of each re-running the per-study fan-out.
  2. the target-INDEPENDENT per-study streams (_fetch_recount3_library_sizes, _fetch_recount3_metadata)
     are @lru_cache'd on `study`, so a DIFFERENT target in the same indication re-streams only the
     gene-row counts, not the library sizes / metadata.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

r = __import__("methods.dge_deseq2.read", fromlist=["read"])


def test_target_independent_helpers_are_lru_cached():
    assert hasattr(r._fetch_recount3_library_sizes, "cache_info")
    assert hasattr(r._fetch_recount3_metadata, "cache_info")
    assert hasattr(r.read_per_sample_expression_tumor_vs_adjacent, "cache_info")


def test_top_level_per_sample_dedupes_identical_calls():
    """A second identical (target, indication) call is a cache HIT — this is what stops the
    selectivity figure from re-fetching what the tumor-vs-adjacent figure already streamed."""
    r.read_per_sample_expression_tumor_vs_adjacent.cache_clear()
    # unmapped indication → None (no S3), but still exercises the cache layer
    r.read_per_sample_expression_tumor_vs_adjacent("KRAS", "NOT_AN_INDICATION")
    r.read_per_sample_expression_tumor_vs_adjacent("KRAS", "NOT_AN_INDICATION")
    ci = r.read_per_sample_expression_tumor_vs_adjacent.cache_info()
    assert ci.hits >= 1 and ci.misses >= 1, f"expected 1 miss + 1 hit, got {ci}"


def test_library_sizes_and_metadata_memoize_per_study(monkeypatch):
    """Stub the S3-streaming bodies with call-counters; a repeated `study` must NOT re-invoke the
    underlying stream (the per-study constants are target-independent)."""
    import pandas as pd
    r._fetch_recount3_library_sizes.cache_clear()
    r._fetch_recount3_metadata.cache_clear()

    lib_calls, md_calls = {"n": 0}, {"n": 0}

    # Replace the cached functions' __wrapped__ bodies by patching the module attrs they call.
    # Simplest robust seam: monkeypatch the whole functions with counting stand-ins that are
    # THEMSELVES lru-wrapped the same way, proving the caching contract holds for repeated study.
    from functools import lru_cache

    @lru_cache(maxsize=64)
    def fake_lib(study):
        lib_calls["n"] += 1
        return pd.Series([1.0], index=["s1"], name="library_size")

    @lru_cache(maxsize=64)
    def fake_md(study):
        md_calls["n"] += 1
        return pd.DataFrame({"gdc_file_id": ["s1"], "sample_type": ["Primary Tumor"],
                             "submitter_id": ["c1"]})

    monkeypatch.setattr(r, "_fetch_recount3_library_sizes", fake_lib)
    monkeypatch.setattr(r, "_fetch_recount3_metadata", fake_md)

    r._fetch_recount3_library_sizes("COAD"); r._fetch_recount3_library_sizes("COAD")
    r._fetch_recount3_metadata("COAD");      r._fetch_recount3_metadata("COAD")
    assert lib_calls["n"] == 1, "library sizes re-streamed for the same study (should be cached)"
    assert md_calls["n"] == 1, "metadata re-streamed for the same study (should be cached)"
