"""_skills_common/paths.py — single source for the sibling-repo filesystem roots.

target-contracts and analysis-methods are sibling repos of claude-oncology-skills. Their roots were
resolved by a copy-pasted `os.environ.get("TARGET_CONTRACTS_ROOT" / "ANALYSIS_METHODS_ROOT", "<default>")`
in ~8 / ~4 modules; a default that drifted in one place would silently split the fleet's view of the
contracts repo. This module is the ONE place the env-var names + default paths live.

Two forms per repo:
  - the DEFAULT string constant — for the few call sites that keep their own `os.environ.get(...)`
    because they need a `str` (e.g. a sys.path entry) or their exact prior semantics;
  - a `*_root()` helper returning a `Path` resolved at CALL time (env first, else default), for the
    common module-level `X = _root()` capture.
"""

from __future__ import annotations

import os
from pathlib import Path

TARGET_CONTRACTS_ROOT_DEFAULT = "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"
ANALYSIS_METHODS_ROOT_DEFAULT = "/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods"


def target_contracts_root() -> Path:
    """Filesystem root of the target-contracts sibling repo (env TARGET_CONTRACTS_ROOT, else default)."""
    return Path(os.environ.get("TARGET_CONTRACTS_ROOT", TARGET_CONTRACTS_ROOT_DEFAULT))


def analysis_methods_root() -> Path:
    """Filesystem root of the analysis-methods sibling repo (env ANALYSIS_METHODS_ROOT, else default)."""
    return Path(os.environ.get("ANALYSIS_METHODS_ROOT", ANALYSIS_METHODS_ROOT_DEFAULT))


# Canonical home for the target-contracts root as a module-level Path constant. scope.py historically
# exported this name and still re-exports it from here for back-compat; new code should import it here.
DEFAULT_CONTRACTS_REPO = target_contracts_root()
