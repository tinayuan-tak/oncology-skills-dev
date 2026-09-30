"""onc_methods.roots -- canonical sibling-checkout root resolution.

Consolidates ~65 copy-pasted
``os.environ.get("<VAR>_ROOT") or Path(__file__).resolve().parents[N].parent / "rnd-...-<repo>"``
blocks across ``methods/onc_methods/*/read.py`` and ``cli.py`` (surveyed 2026-09-29, skills#2141) into
two functions. Behavior is UNCHANGED from every migrated call site: env var first (an empty env
value falls through too, via ``or`` rather than ``os.environ.get(K, default)`` -- an empty string
would otherwise resolve ``Path("")`` to the CWD, a plausible-looking wrong root), else the sibling
checkout derived from THIS file's own location. This module does not change resolution semantics or
retire the sibling symlinks -- that is the packaging epic's (#2144) stage 4; this only reduces the
65 copies to one, so that later change becomes a one-file edit.

``N`` used to vary by caller depth (``parents[2]`` for a flat ``<module>/read.py``, ``parents[3]``
for one nested one level deeper, e.g. ``dge_deseq2/read/__init__.py``) -- both walks land on the
SAME directory in practice (the analysis-methods repo root's parent), because they were counting
up from different starting depths to the same target. Anchored here, from ``methods/roots.py``
itself, the walk is fixed at ``parents[1]`` (this package dir's parent, i.e. the analysis-methods
repo root) ``.parent`` (the sibling-checkouts directory) regardless of any given caller's own depth.
"""

from __future__ import annotations

import os
from pathlib import Path

# methods/roots.py -> parents[0] = "methods" (this package dir) -> parents[1] = the
# analysis-methods repo root -> .parent = the directory holding the sibling checkouts
# (rnd-computational-biology-oncology-{data-catalog,target-contracts,...}).
_SIBLING_ROOT = Path(__file__).resolve().parents[1].parent


def data_catalog_root() -> Path:
    """``DATA_CATALOG_ROOT`` env override, else the sibling data-catalog checkout."""
    return Path(
        os.environ.get("DATA_CATALOG_ROOT") or _SIBLING_ROOT / "rnd-computational-biology-oncology-data-catalog"
    )


def contracts_root() -> Path:
    """``TARGET_CONTRACTS_ROOT`` env override, else the sibling target-contracts checkout."""
    return Path(
        os.environ.get("TARGET_CONTRACTS_ROOT") or _SIBLING_ROOT / "rnd-computational-biology-oncology-target-contracts"
    )
