"""onc_methods.roots -- canonical sibling-checkout root resolution.

Consolidates ~65 copy-pasted
``os.environ.get("<VAR>_ROOT") or Path(__file__).resolve().parents[N].parent / "rnd-...-<repo>"``
blocks across ``methods/onc_methods/*/read.py`` and ``cli.py`` (surveyed 2026-09-29, skills#2141) into
two functions. Behavior is UNCHANGED from every migrated call site: env var first (an empty env
value falls through too, via ``or`` rather than ``os.environ.get(K, default)`` -- an empty string
would otherwise resolve ``Path("")`` to the CWD, a plausible-looking wrong root), else the sibling
in-tree / sibling tree derived from THIS file's own location.

N3-1 stage 4 (#2144): since the SK#2063 monorepo consolidation ``contracts/`` lives IN-TREE beside
``methods/``, so ``contracts_root()`` now resolves to ``<repo-root>/contracts`` directly and no
longer depends on the retired ``rnd-...-target-contracts`` geometry symlink. ``data-catalog`` stays
a genuinely separate sibling repo, so ``data_catalog_root()`` keeps a sibling-relative default (one
level above the monorepo root, where the kept ``rnd-...-data-catalog`` symlink points). Both still
honour their ``*_ROOT`` env override first. Anchored from ``onc_methods/roots.py``, the repo root is
``parents[1].parent`` regardless of any caller's own depth, so the ~48 call sites that only call
these functions inherit the in-tree resolution with no change.
"""

from __future__ import annotations

import os
from pathlib import Path

# onc_methods/roots.py -> parents[1] = "methods" (this package's parent) ->
# parents[1].parent = the monorepo root, which holds contracts/ IN-TREE (SK#2063) and sits one
# level below the data-catalog sibling clone. N3-1 stage 4 (#2144): contracts now resolves to the
# in-tree tree directly, NOT via the retired rnd-...-target-contracts geometry symlink.
_REPO_ROOT = Path(__file__).resolve().parents[1].parent


def data_catalog_root() -> Path:
    """``DATA_CATALOG_ROOT`` env override, else the data-catalog sibling clone.

    data-catalog is the one genuinely-separate repo (stable manifest-ID interface), so its default
    is resolved one level above the monorepo root -- where the kept rnd-...-data-catalog symlink
    points -- NOT inside this tree.
    """
    return Path(
        os.environ.get("DATA_CATALOG_ROOT") or _REPO_ROOT.parent / "rnd-computational-biology-oncology-data-catalog"
    )


def contracts_root() -> Path:
    """``TARGET_CONTRACTS_ROOT`` env override, else the IN-TREE ``contracts/`` (monorepo, SK#2063)."""
    return Path(os.environ.get("TARGET_CONTRACTS_ROOT") or _REPO_ROOT / "contracts")
