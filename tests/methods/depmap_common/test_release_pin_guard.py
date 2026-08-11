"""M4 regression (2026-08-11 code review): depmap_common.parquet loaders must not SILENTLY IGNORE
a release_pin they cannot serve.

Prior bug: every loader accepted `release_pin` but built the S3 key purely from the module constant
PARQUET_S3_PREFIX (which encodes 26q1), so a caller passing release_pin="26q2" unknowingly read 26q1
data. Multi-release support is blocked on per-release catalog manifests; until then the honest
behavior is to REFUSE a pin we cannot honor. These tests need no S3 — the guard raises before any
fetch.
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


def test_served_release_matches_prefix():
    """The served-release constant must match the release encoded in the S3 prefix (no drift)."""
    assert P._SERVED_RELEASE in P.PARQUET_S3_PREFIX, (
        f"_SERVED_RELEASE={P._SERVED_RELEASE!r} not found in PARQUET_S3_PREFIX={P.PARQUET_S3_PREFIX!r}"
    )


@pytest.mark.parametrize("fn_name,args", _LOADERS)
def test_unservable_release_pin_raises_before_any_fetch(fn_name, args, monkeypatch):
    """Passing a release_pin the loaders can't serve raises ValueError — and does so BEFORE any S3
    fetch (we monkeypatch _fetch_parquet to explode, proving the guard short-circuits first)."""
    def _boom(*a, **k):
        raise AssertionError("_fetch_parquet must NOT be reached when release_pin is unservable")
    monkeypatch.setattr(P, "_fetch_parquet", _boom)

    fn = getattr(P, fn_name)
    with pytest.raises(ValueError, match="serves only release"):
        fn(*args, release_pin="26q2")


def test_assert_release_served_accepts_the_served_release():
    """The served release passes the guard (sanity — no false positive)."""
    P._assert_release_served(P._SERVED_RELEASE)  # must not raise
