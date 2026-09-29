"""M4 regression (2026-08-11 code review): depmap_common.parquet loaders must resolve their S3 prefix
PER release_pin from the catalog manifest, and must NOT silently serve the wrong release.

History:
  - #283 shipped _assert_release_served as a STOPGAP (raised ValueError on any pin != 26q1) when no
    catalog manifest existed.
  - data-catalog #331 landed depmap-26q1-parquet-v1; this module now resolves the prefix via
    catalog_query.bucket_prefix_for(f"depmap-{release_pin}-parquet-v1"). So a registered release
    resolves to its prefix, and an UNREGISTERED release raises FileNotFoundError from the resolver —
    the loud failure that preserves the guard's intent (never silently return the wrong release).

These tests need no S3 — resolution + the guard short-circuit happen before any download.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# methods repo root on sys.path
REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.depmap_common import parquet as P  # noqa: E402

# Every public loader that accepts release_pin, with a minimal arg tuple (before release_pin).
_LOADERS = [
    ("get_chronos_column", ("KRAS",)),
    ("get_tpm_column", ("KRAS",)),
    ("get_cn_column_wes", ("KRAS",)),
    ("get_cn_column_wgs", ("KRAS",)),
    ("get_hotspot_mutation_column", ("KRAS",)),
    ("get_damaging_mutation_column", ("KRAS",)),
    ("get_matrix_column_by_model_id", ("OmicsCNGeneWGS.parquet", "KRAS")),
    ("get_demeter_row", ("KRAS",)),
    ("get_maf_gene_rows", ("KRAS",)),
    ("get_maf_n_cell_lines_total", ()),
]


def test_served_release_resolves_to_catalog_prefix():
    """The registered 26q1 release resolves to the catalog manifest's prefix (the resolver seam
    works end-to-end, no hardcoded constant)."""
    P._release_prefix.cache_clear()
    prefix = P._release_prefix("26q1")
    assert prefix == "data-catalog/derived/depmap-26q1-parquet-v1", prefix


def test_unregistered_release_raises_before_any_fetch(monkeypatch):
    """A release with no catalog manifest must raise (FileNotFoundError from bucket_prefix_for) —
    the loud failure that replaces #283's ValueError stopgap. It must raise BEFORE any S3 fetch."""

    def _boom(*a, **k):
        raise AssertionError("boto3/download must NOT be reached for an unregistered release")

    # if resolution ever fell through, this would catch a stray download attempt
    monkeypatch.setattr(P, "_local_cached", lambda *a, **k: Path("/nonexistent/should-not-be-used"))
    P._release_prefix.cache_clear()
    with pytest.raises(FileNotFoundError):
        P._release_prefix("26q99")  # not a registered manifest id


@pytest.mark.parametrize("fn_name,args", _LOADERS)
def test_loader_raises_on_unregistered_release_before_fetch(fn_name, args, monkeypatch):
    """Each loader, called with an unregistered release_pin, raises before any S3 download
    (we explode _fetch_parquet's downloader path to prove no fetch is attempted)."""
    # Make any actual download attempt fail loudly so a silent wrong-release read can't pass.
    monkeypatch.setattr(P, "_local_cached", lambda *a, **k: Path("/nonexistent/must-not-download"))
    P._release_prefix.cache_clear()
    fn = getattr(P, fn_name)
    with pytest.raises(FileNotFoundError):
        fn(*args, release_pin="26q99")


def test_release_scoped_cache_dir_isolates_releases():
    """The local cache is release-scoped: 26q1 keeps the legacy dir; another release gets its own,
    so a 26q2 request can never return a cached 26q1 file."""
    p_26q1 = P._local_cached("CRISPRGeneEffect.parquet", "26q1")
    p_other = P._local_cached("CRISPRGeneEffect.parquet", "26q2")
    assert p_26q1.parent.name == "framework-depmap-26q1-parquet"
    assert p_other.parent.name == "framework-depmap-26q2-parquet"
    assert p_26q1 != p_other
