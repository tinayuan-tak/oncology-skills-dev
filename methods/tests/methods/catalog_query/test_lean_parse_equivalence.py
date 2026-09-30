"""Guard: the lean manifest parse (load_catalog's files-skipping fast path) is BYTE-IDENTICAL
to a full yaml parse + `raw.pop('files')` + the distinct file `category` set, for EVERY manifest
in the catalog.

load_catalog constructs the CatalogIndex once per process; the `files:` array (per-file
path/md5/size, 10k+ rows on the big source releases) is DISCARDED — only the distinct `category`
set is kept. `_lean_load_manifest` text-strips the `files:` block before parsing (so the C scanner
never tokenizes it), cutting the catalog parse ~10x. This test is the safety net that lets that
optimization live in the shared loader: it proves the lean path yields the same document (minus
files) and the same category set as the canonical construction, so the CatalogIndex — and every
consumer, including compose-dashboard's byte-golden evidence-package path — is unchanged.
"""

from __future__ import annotations

import pytest
import yaml

from onc_methods.catalog_query.read import (
    DATA_CATALOG,
    _lean_load_manifest,
    _SafeLoader,
)


def _manifest_paths():
    paths = []
    for sub in ("sources", "derived"):
        d = DATA_CATALOG / "manifests" / sub
        if d.is_dir():
            paths.extend(sorted(d.glob("*.yaml")))
    return paths


_PATHS = _manifest_paths()


@pytest.mark.skipif(not _PATHS, reason="data-catalog not available in this environment")
@pytest.mark.parametrize("path", _PATHS, ids=lambda p: p.name)
def test_lean_parse_matches_full_parse(path):
    full = yaml.load(path.read_text(), Loader=_SafeLoader) or {}
    files = full.pop("files", None) or []
    want_categories = sorted({fe.get("category") for fe in files if isinstance(fe, dict)} - {None})
    want_formats = sorted({fe.get("format") for fe in files if isinstance(fe, dict)} - {None})

    doc, categories, formats = _lean_load_manifest(path)

    assert doc == full, f"{path.name}: lean doc (minus files) differs from full parse"
    assert categories == want_categories, f"{path.name}: lean category set differs from full parse"
    assert formats == want_formats, f"{path.name}: lean format set differs from full parse"


@pytest.mark.skipif(not _PATHS, reason="data-catalog not available in this environment")
def test_catalog_nonempty():
    # Sanity: the parametrized guard above is only meaningful if it actually ran over manifests.
    assert len(_PATHS) > 50, f"expected a populated catalog, found {len(_PATHS)} manifests"
