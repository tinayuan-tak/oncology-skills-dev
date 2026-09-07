"""Shared git-provenance helper for compositional skills.

(2026-08-11): the framework's audit spine leaned on placeholder
provenance — compose-dashboard shipped `SKILL_VERSION = "0a1b2c3"` (a hardcoded stub, never
populated) and stamped method-call `git_sha` with an execution-MODE tag ("phase2_live"), not a
real SHA. So an evidence_package could not answer "which code version produced this."

This module provides ONE reusable git-sha resolver so both placeholder sites (and any future
skill) stamp a real short SHA, falling back to a schema-valid sentinel when git is unavailable
(CI checkout depth, non-repo install, etc.). Modeled on analysis-methods
methods/subgroup_common/manifest.py::_git_sha.
"""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Optional

# Sentinel returned when git can't be reached. 7 hex chars so it satisfies any
# generated_by/git_sha pattern of the form [0-9a-f]{7} (mirrors the analysis-methods sentinel).
UNKNOWN_SHA = "0000000"


@lru_cache(maxsize=16)
def git_sha(repo_path: Optional[str] = None, short: bool = True) -> str:
    """Return the current git SHA of the repo containing `repo_path`.

    `repo_path` — any path inside the target repo (defaults to this file's repo).
    `short` — 7-char abbreviated SHA (default) vs full 40-char.
    Returns UNKNOWN_SHA ("0000000") when git is unavailable. Never raises — provenance is
    best-effort and must never block evidence-package emission. lru_cached because a single
    compose run stamps the same SHA many times.
    """
    cwd = Path(repo_path) if repo_path else Path(__file__).resolve().parent
    if cwd.is_file():
        cwd = cwd.parent
    args = ["git", "-C", str(cwd), "rev-parse"]
    if short:
        args.append("--short=7")
    args.append("HEAD")
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=5)
        sha = out.stdout.strip().lower()
        if sha and all(c in "0123456789abcdef" for c in sha):
            return sha
    except Exception:  # noqa: BLE001 — provenance best-effort; never block emit
        pass
    return UNKNOWN_SHA


def skills_repo_sha() -> str:
    """Short SHA of the claude-oncology-skills repo (this module's repo)."""
    return git_sha(str(Path(__file__).resolve().parent))
