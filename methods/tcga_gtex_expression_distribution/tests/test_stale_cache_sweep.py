"""Guard: the CACHE_DIR self-healing sweep keeps ONLY the sidecar and removes stale full-download residue.

The live reader streams the multi-GB long products from S3 via HTTP range requests; the only file it
should ever cache on disk is the ~448 KB sidecar. A prior reader (removed PR #115) full-downloaded the
long products into CACHE_DIR, and a long-lived process still holding that old code in memory can re-bloat
the dir to ~16 GB. _sweep_stale_cache makes the CURRENT code self-healing so such residue never survives
the next run. This pins that invariant. S3-free (filesystem only)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.tcga_gtex_expression_distribution.read import (  # noqa: E402
    _CACHE_ALLOWED_NAMES,
    _SIDECAR_CACHE,
    _sweep_stale_cache,
)

_SIDECAR_NAME = _SIDECAR_CACHE.name


def test_sweep_removes_stale_long_products_keeps_sidecar(tmp_path: Path):
    # The exact 16 GB residue shape observed 2026-08-03: two full products + a boto3 in-progress temp.
    (tmp_path / _SIDECAR_NAME).write_bytes(b"keep-me")
    (tmp_path / "gtex_tpm_long.parquet").write_bytes(b"stale-7GB")
    (tmp_path / "tcga_tpm_long.parquet").write_bytes(b"stale-3GB")
    (tmp_path / "gtex_tpm_long.parquet.6d473823").write_bytes(b"boto3-temp")  # 8-hex in-progress temp

    removed = _sweep_stale_cache(tmp_path, _CACHE_ALLOWED_NAMES)

    assert set(removed) == {
        "gtex_tpm_long.parquet",
        "tcga_tpm_long.parquet",
        "gtex_tpm_long.parquet.6d473823",
    }
    # sidecar survives; everything else is gone
    assert (tmp_path / _SIDECAR_NAME).exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == [_SIDECAR_NAME]


def test_sweep_noop_when_only_sidecar_present(tmp_path: Path):
    (tmp_path / _SIDECAR_NAME).write_bytes(b"keep-me")
    removed = _sweep_stale_cache(tmp_path, _CACHE_ALLOWED_NAMES)
    assert removed == []
    assert (tmp_path / _SIDECAR_NAME).exists()


def test_sweep_silent_on_missing_dir(tmp_path: Path):
    missing = tmp_path / "does-not-exist"
    assert _sweep_stale_cache(missing, _CACHE_ALLOWED_NAMES) == []


def test_sidecar_is_the_only_allowed_name():
    # If a second legitimately-cached file is ever added, the allowlist AND this test must be updated
    # together — otherwise the sweep would silently delete it on the next run.
    assert _CACHE_ALLOWED_NAMES == frozenset({_SIDECAR_NAME})
