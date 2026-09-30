"""Hermetic pin on the dge_deseq2 reader's data-catalog resolution (analysis-methods#728).

`methods/dge_deseq2/read` is a *package* (`read/__init__.py`), one directory deeper than the flat
sibling readers (`methods/<name>/read.py`, e.g. `catalog_query`). Its `DATA_CATALOG` therefore needs
one extra `parents[...]` level to reach the sibling-clone directory. The S0 reorg (#692) added the
package level but left the flat-reader `parents[2].parent` in place, so `DATA_CATALOG` pointed one
level too shallow — *inside* the analysis-methods repo — and every catalog access raised
FileNotFoundError.

Why this needs a hermetic test at all: the failure was *masked in CI*. The only test that exercised
this path (a live reader chain in claude-oncology-skills) runs behind `skip_if_no_data`, which in CI
hits an S3-access error (no creds) BEFORE the catalog lookup and skips — a green-for-the-wrong-reason
skip. These tests touch no S3, so they gate in CI's sibling checkout (where `DATA_CATALOG_ROOT` is
deliberately unset, exercising the portable-sibling fallback that regressed).

The load-bearing invariant is `test_matches_sibling_reader_anchor`: the two readers must resolve the
catalog to the SAME clone. It is fully hermetic (both constants derive from `__file__`), always runs,
and cannot be skipped. The two catalog-present tests additionally exercise the exact read that
misfired; they gate their skip on the *flat sibling* reader's anchor (an independent oracle that is
correct regardless of this bug), so a resolution regression FAILS here — it is never skipped away.
"""

from __future__ import annotations

import pytest

from onc_methods.catalog_query import read as cq_read
from onc_methods.dge_deseq2 import read as dge_read


def test_matches_sibling_reader_anchor():
    """Both readers must resolve the data-catalog identically (issue #728 acceptance).

    Fully hermetic — no filesystem or S3 needed. Under the pre-fix `parents[2].parent` this is False
    (dge points inside the AM repo, catalog_query points at the sibling clone).
    """
    assert dge_read.DATA_CATALOG == cq_read.DATA_CATALOG, (
        f"dge_deseq2.read.DATA_CATALOG={dge_read.DATA_CATALOG!r} must equal "
        f"catalog_query.read.DATA_CATALOG={cq_read.DATA_CATALOG!r}"
    )


def _known_good_catalog_present() -> bool:
    """Independent oracle: does the FLAT sibling reader see a data-catalog clone?

    The flat reader's anchor is correct regardless of #728, so gating the skip on it (never on the
    dge reader's own possibly-broken anchor) guarantees a resolution regression FAILS rather than
    skips: pre-fix the good anchor's catalog exists, so we do not skip, and the dge assertions below
    fire on the broken path.
    """
    return (cq_read.DATA_CATALOG / "manifests" / "derived").is_dir()


def test_resolves_to_existing_derived_dir():
    """Issue #728 guardrail (a): `DATA_CATALOG` resolves to a real `manifests/derived` dir."""
    if not _known_good_catalog_present():
        pytest.skip("no data-catalog clone beside the repo")
    assert (dge_read.DATA_CATALOG / "manifests" / "derived").is_dir(), dge_read.DATA_CATALOG


def test_load_manifest_reaches_real_catalog():
    """The exact read that misfired (#728): `_load_manifest` globs under `DATA_CATALOG`.

    Pre-fix this raises FileNotFoundError because the glob runs under the bogus nested path. We load
    the first `coadread-dge-*` derived manifest present rather than pinning one id, so the test stays
    a resolution check and does not couple to any single manifest's lifecycle.
    """
    if not _known_good_catalog_present():
        pytest.skip("no data-catalog clone beside the repo")
    derived = cq_read.DATA_CATALOG / "manifests" / "derived"
    candidates = sorted(derived.glob("coadread-dge-*.yaml"))
    if not candidates:
        pytest.skip("no coadread-dge derived manifest in this catalog checkout")
    manifest_id = candidates[0].stem
    loaded = dge_read._load_manifest(manifest_id)
    assert isinstance(loaded, dict) and loaded.get("id") == manifest_id
