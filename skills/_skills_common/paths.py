"""_skills_common/paths.py — single source for the contracts/methods package roots.

target-contracts and analysis-methods live IN THIS REPO as the contracts/ and methods/ packages
(SK#2063 consolidation, 2026-09-29); the defaults below derive from the repo root so every checkout
(CI, primary clone, /tmp worktrees) resolves its OWN tree, never a stale sibling clone. The env-var
overrides are unchanged. Historically these were sibling repos resolved by a copy-pasted
`os.environ.get("TARGET_CONTRACTS_ROOT" / "ANALYSIS_METHODS_ROOT", "<default>")` in ~8 / ~4 modules;
this module is the ONE place the env-var names + default paths live.

Two forms per repo:
  - the DEFAULT string constant — for the few call sites that keep their own `os.environ.get(...)`
    because they need a `str` (e.g. a sys.path entry) or their exact prior semantics;
  - a `*_root()` helper returning a `Path` resolved at CALL time (env first, else default), for the
    common module-level `X = _root()` capture.
"""

from __future__ import annotations

import os
from pathlib import Path

# Repo root: this file is skills/_skills_common/paths.py → parents[2] is the checkout root.
_REPO_ROOT = Path(__file__).resolve().parents[2]

TARGET_CONTRACTS_ROOT_DEFAULT = str(_REPO_ROOT / "contracts")
ANALYSIS_METHODS_ROOT_DEFAULT = str(_REPO_ROOT / "methods")

# data-catalog STAYS a separate sibling repo (SK#2063 consolidation only folded
# target-contracts/analysis-methods into this monorepo) — so its default is genuinely
# sibling-relative, not repo-root-relative: the checkout's PARENT directory (whatever
# that is on a given box — $HOME on the dev box, the worktree/CI parent elsewhere),
# never a hardcoded /home/sagemaker-user literal. Mirrors the existing
# methods.dge_deseq2.read.DATA_CATALOG idiom.
DATA_CATALOG_ROOT_DEFAULT = str(_REPO_ROOT.parent / "rnd-computational-biology-oncology-data-catalog")


def target_contracts_root() -> Path:
    """Filesystem root of the target-contracts sibling repo (env TARGET_CONTRACTS_ROOT, else default)."""
    return Path(os.environ.get("TARGET_CONTRACTS_ROOT", TARGET_CONTRACTS_ROOT_DEFAULT))


def analysis_methods_root() -> Path:
    """Filesystem root of the analysis-methods sibling repo (env ANALYSIS_METHODS_ROOT, else default)."""
    return Path(os.environ.get("ANALYSIS_METHODS_ROOT", ANALYSIS_METHODS_ROOT_DEFAULT))


def data_catalog_root() -> Path:
    """Filesystem root of the data-catalog sibling repo (env DATA_CATALOG_ROOT, else portable default)."""
    return Path(os.environ.get("DATA_CATALOG_ROOT", DATA_CATALOG_ROOT_DEFAULT))


# Canonical home for the target-contracts root as a module-level Path constant. scope.py historically
# exported this name and still re-exports it from here for back-compat; new code should import it here.
DEFAULT_CONTRACTS_REPO = target_contracts_root()
