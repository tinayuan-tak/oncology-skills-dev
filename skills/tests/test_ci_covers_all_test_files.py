"""CI-coverage guard — every collectable ``test_*.py`` must live under a root the
``pytest`` job actually invokes.

skills-validate.yml's ``pytest`` job is a branch-protection REQUIRED check, but its
coverage is a set of path globs, and *a path-glob'd job silently un-covers every
directory added after it was written*. That has bitten this repo twice:

  - top-level ``skills/tests/`` was invisible until PR #361 gated it — the
    ``for d in skills/*/tests`` glob matches ``skills/<skill>/tests``, not
    ``skills/tests/``;
  - all of ``eval/`` was invisible until the eval step landed alongside this test —
    six modules, including ``eval/test_subskill_discordance.py`` which sits at the
    *top* of ``eval/``, so even a hardcoded ``pytest eval/tests`` would have missed one.

Both are "the check didn't run" wearing the costume of "the check passed". This guard
closes the family by reading the workflow as the SINGLE SOURCE OF TRUTH: it extracts
the paths the job runs pytest against (explicit args plus the ``skills/*/tests`` glob
it expands), then asserts every git-tracked collectable test file is under one of them.
Add a test directory the workflow doesn't run and this goes RED, rather than the file
going silently unrun.

Deliberately NOT a hardcoded list of covered roots: that would drift from the workflow
and reintroduce exactly the silent-uncover bug one level up. The workflow is parsed.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "skills-validate.yml"

# pytest collects files whose basename matches this (the default python_files); a broader
# shell glob like ``*test_*.py`` also matches scripts such as eval/backtest_per_axis.py that
# pytest never collects, so match pytest's own rule, not the shell's.
_COLLECTABLE = "test_*.py"


def _noncomment_lines(text: str) -> str:
    """Drop whole-line comments — both YAML ``#`` lines and bash ``#`` lines inside a
    ``run:`` block scalar — so a path mentioned in prose (e.g. the comment explaining why
    ``pytest skills/`` in one process was wrong) is never mistaken for an invoked root."""
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def _covered_dirs() -> set[Path]:
    """Directories the workflow actually runs pytest against, resolved against the repo.

    Every candidate must resolve to a real directory to count — this drops quoting/backtick
    debris and any ``"$d"``-style loop variable, and means a stale path in the workflow can
    never *widen* coverage."""
    assert WORKFLOW.is_file(), f"workflow not found at {WORKFLOW}"
    body = _noncomment_lines(WORKFLOW.read_text())

    candidates: set[str] = set()
    # explicit invocations: `pixi run pytest <path> -q ...`
    for tok in re.findall(r"pytest\s+(\S+)", body):
        candidates.add(tok)
    # glob-driven loop: `for d in skills/*/tests; do ... pytest "$d" ...`
    for src in re.findall(r"\bfor\s+\w+\s+in\s+([^\n;]+?)\s*;?\s*do\b", body):
        candidates.update(src.split())

    covered: set[Path] = set()
    for raw in candidates:
        tok = raw.strip().strip("\"'`").rstrip("/")
        if not tok or tok.startswith("-") or "$" in tok:
            continue
        if any(ch in tok for ch in "*?[]"):
            covered.update(p.resolve() for p in REPO_ROOT.glob(tok) if p.is_dir())
        else:
            p = (REPO_ROOT / tok).resolve()
            if p.is_dir():
                covered.add(p)
    return covered


def _collectable_test_files() -> list[str]:
    """Repo-relative paths of every tracked file pytest would collect."""
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "-z"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        files = [f for f in out.split("\0") if f]
    except (subprocess.CalledProcessError, FileNotFoundError):
        # not a git checkout — enumerate the tree, minus obvious noise
        files = [
            str(p.relative_to(REPO_ROOT))
            for p in REPO_ROOT.rglob(_COLLECTABLE)
            if ".git" not in p.parts and "__pycache__" not in p.parts
        ]
    return sorted(f for f in files if fnmatch.fnmatch(Path(f).name, _COLLECTABLE))


def _is_covered(rel: str, covered: set[Path]) -> bool:
    parent = (REPO_ROOT / rel).resolve().parent
    return any(c == parent or c in parent.parents for c in covered)


def test_ci_covered_scope_parses_and_is_not_a_universal_prefix():
    """Anti-vacuity FIRST: the enumeration and the parse both find something, and the
    covered set is not so broad (e.g. the repo root) that every file is trivially covered —
    which would make the real assertion below pass no matter what CI runs."""
    covered = _covered_dirs()
    collectable = _collectable_test_files()

    assert collectable, "git ls-files found no collectable test files — enumeration is broken"
    assert covered, "parsed no invoked pytest roots from skills-validate.yml — the parser is broken"
    assert REPO_ROOT not in covered, (
        "a covered root resolved to the repo root, so every test file is trivially covered "
        "and this guard proves nothing"
    )
    # positive control: a directory the workflow demonstrably runs must read as covered
    assert _is_covered("skills/tests/test_ci_covers_all_test_files.py", covered), (
        "skills/tests/ is a blocking CI step but did not parse as covered — the extractor regressed"
    )
    # negative control: a fabricated file under an un-run directory must NOT read as covered,
    # proving the covered set discriminates rather than swallowing everything
    assert not _is_covered("notebooks/test_FAKE_uncovered.py", covered), (
        "a fabricated test under notebooks/ read as covered — the covered set is a universal "
        "prefix and the guard is vacuous"
    )


def test_every_collectable_test_file_runs_in_ci():
    covered = _covered_dirs()
    uncovered = [f for f in _collectable_test_files() if not _is_covered(f, covered)]
    assert not uncovered, (
        "these test files are tracked but no skills-validate.yml pytest step runs them, so "
        "they are green-by-absence on every PR:\n  "
        + "\n  ".join(uncovered)
        + "\n\nAdd a pytest step that covers the directory (a recursive `pytest <dir>` step), "
        "or move the file under an already-covered root. Do NOT special-case it here — the "
        "workflow is the single source of truth this guard reads."
    )
