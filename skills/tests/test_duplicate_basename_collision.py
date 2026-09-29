"""Duplicate-basename collision guard — the gap ``test_ci_covers_all_test_files`` misses.

That sibling guard proves every tracked ``test_*.py`` lives under a root the workflow
invokes. It does NOT prove that two files sharing a basename won't collide when pytest
collects them in the *same* process: without ``--import-mode=importlib``, pytest requires
unique basenames within one invocation's collected tree (absent ``__init__.py`` files) and
raises ``import file mismatch``, silently dropping one file's tests rather than merely
warning. CLAUDE.md already warns never to run a whole-tree ``pytest`` from repo root for
exactly this reason. A future consolidation that adds a root-level pytest invocation (or
drops an existing ``--import-mode=importlib`` flag) would reintroduce that failure mode and
neither this guard's sibling nor CI's own green would catch it — hence this guard.

MODEL: read ``skills-validate.yml`` (the single source of truth — see the sibling guard's
docstring for why a hardcoded root list drifts) for every ``pytest`` invocation, and for
each, record:
  - its *root(s)*: the directory arguments passed (resolved against that step's
    ``working-directory``), or the step's working directory itself when no path argument is
    given (a bare ``python -m pytest`` collects its whole cwd tree);
  - whether ``--import-mode=importlib`` is present on that invocation.

``--import-mode=importlib`` disambiguates same-basename files EVEN WITHIN one invocation
(pytest derives a unique module name from the full path, not the basename) — that is the
whole point of every per-skill / per-package suite in this repo running with it. So this
guard flags a colliding basename set only when two-or-more of its files fall under the SAME
importlib-less invocation root. A colliding set that splits across DISTINCT invocation
roots (whether or not those roots use importlib) is fine — each file runs in its own pytest
process and pytest never sees the other's basename.

Deliberately NOT a hardcoded invocation-root list, for the same reason as the sibling
guard: hardcoding drifts from the workflow and hides exactly the change this guard exists
to catch.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "skills-validate.yml"

# Deliberately duplicated (in miniature) from test_ci_covers_all_test_files rather than
# imported: under --import-mode=importlib the sibling module is not reliably importable
# by name (no sys.path insertion), and this guard's own docstring above explains why a
# cross-invocation import dependency between the two collection-integrity guards is a
# trap to avoid, not a DRY opportunity.
_COLLECTABLE = "test_*.py"


def _noncomment_lines(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def _collectable_test_files() -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    files = [f for f in out.split("\0") if f]
    return sorted(f for f in files if fnmatch.fnmatch(Path(f).name, _COLLECTABLE))


# Non-flag, non-numeric, non-`$`-containing tokens that resolve to a real path once
# offset by the invocation's working directory are treated as path arguments; everything
# else (xdist worker counts, `-n auto`, `-q`, `--splits 4`, …) is pytest-CLI noise.
_PYTEST_INVOCATION = re.compile(r"(?:pixi run pytest|python -m pytest)\s+([^\n]*)")
_WORKDIR = re.compile(r"working-directory:\s*(\S+)")


def _resolve_root(token: str, workdir: str) -> Path | None:
    """Resolve a `workdir`-relative token against the repo, tolerating the CI-only
    checkout-path PREFIX that never exists on a local checkout (e.g. the pytest-shards
    step's own `working-directory: rnd-…-claude-oncology-skills`, or the methods-pytest
    step's `rnd-…-claude-oncology-skills/methods` — that leading segment is the name CI
    gives the checkout dir, which is not this worktree's directory name). Strip leading
    path segments one at a time until the remainder (possibly empty) + token resolves."""
    segments = [s for s in workdir.split("/") if s]
    for start in range(len(segments) + 1):
        wd = "/".join(segments[start:])
        candidate = (REPO_ROOT / wd / token).resolve() if wd else (REPO_ROOT / token).resolve()
        if candidate.is_dir():
            return candidate
    return None


def _invocation_roots() -> list[tuple[Path, bool]]:
    """[(root, uses_importlib), …] for every literal `pytest`/`pixi run pytest` invocation
    in the workflow, plus the per-skill `for d in skills/*/tests` loop (always importlib —
    see run_suite's call site)."""
    assert WORKFLOW.is_file(), f"workflow not found at {WORKFLOW}"
    body = _noncomment_lines(WORKFLOW.read_text())

    # Track the most recently seen `working-directory:` as we scan top-to-bottom — good
    # enough for this file's structure (each job's steps appear together, and a step-level
    # working-directory always precedes the run: line it governs).
    roots: list[tuple[Path, bool]] = []
    workdir = ""
    for line in body.splitlines():
        wd_match = _WORKDIR.search(line)
        if wd_match:
            workdir = wd_match.group(1).strip("\"'`").rstrip("/")

        inv_match = _PYTEST_INVOCATION.search(line)
        if not inv_match:
            continue
        args = inv_match.group(1)
        importlib_used = "--import-mode=importlib" in args

        all_tokens = args.split()
        is_templated = any("$" in tok for tok in all_tokens)
        path_tokens = [
            tok.strip("\"'`").rstrip("/")
            for tok in all_tokens
            if tok and not tok.startswith("-") and "$" not in tok and not tok.isdigit()
        ]
        resolved = [r for r in (_resolve_root(t, workdir) for t in path_tokens) if r is not None]
        if resolved:
            roots.extend((r, importlib_used) for r in resolved)
        elif not is_templated:
            # a genuine bare `python -m pytest [flags]` with no path arg at all — collects its
            # cwd tree. A line containing a shell variable (e.g. `pixi run pytest $2` inside
            # run_suite's function body) is a TEMPLATE whose real args come from its call
            # sites, which are captured as their own literal matches elsewhere — falling back
            # to "covers the whole working dir" for the template itself would make every other
            # root a trivial subset of it and the guard vacuous (the same universal-prefix trap
            # the sibling guard's anti-vacuity test checks for).
            wd_root = _resolve_root(".", workdir) or REPO_ROOT
            roots.append((wd_root, importlib_used))

    # The per-skill loop: `for d in skills/*/tests` → run_suite "$skill" "$d ... --import-mode=importlib".
    # Always importlib per that call site (grep-verified below is redundant insurance).
    assert "--import-mode=importlib" in body.split("for d in skills/*/tests", 1)[-1][:400], (
        "the per-skill loop no longer threads --import-mode=importlib immediately after the "
        "glob — re-check run_suite's call site; this guard assumed it always does"
    )
    for d in REPO_ROOT.glob("skills/*/tests"):
        if d.is_dir():
            roots.append((d.resolve(), True))

    return roots


def test_duplicate_basename_guard_parses_and_is_not_vacuous():
    """Anti-vacuity: enumeration finds files, the parser finds invocation roots, and at
    least one importlib-less root exists (else the "same-root collision" check below can
    never fire and the guard proves nothing)."""
    collectable = _collectable_test_files()
    roots = _invocation_roots()
    assert collectable, "git ls-files found no collectable test files — enumeration is broken"
    assert roots, "parsed no pytest invocations from skills-validate.yml — the parser is broken"
    non_importlib = [r for r, uses_il in roots if not uses_il]
    assert non_importlib, (
        "every parsed invocation uses --import-mode=importlib — the same-invocation "
        "collision check below is vacuously satisfied; re-verify the parser against the "
        "current workflow (this repo does have importlib-less shards: core-common, "
        "core-profile, the contracts whole-package suite)"
    )


def test_no_duplicate_basename_collides_within_one_invocation():
    collectable = _collectable_test_files()
    assert len(collectable) > 0  # cardinality floor

    by_basename: dict[str, list[Path]] = defaultdict(list)
    for rel in collectable:
        by_basename[Path(rel).name].append((REPO_ROOT / rel).resolve())

    roots = _invocation_roots()
    non_importlib_roots = [r for r, uses_il in roots if not uses_il]

    violations: list[str] = []
    for basename, paths in by_basename.items():
        if len(paths) < 2:
            continue
        for root in non_importlib_roots:
            hit = [p for p in paths if root == p.parent or root in p.parents]
            if len(hit) > 1:
                violations.append(
                    f"{basename} collides under importlib-less root {root}: "
                    + ", ".join(str(p.relative_to(REPO_ROOT)) for p in hit)
                )

    assert not violations, (
        "these duplicate basenames would collide in a single pytest collection (no "
        "--import-mode=importlib to disambiguate them), silently dropping one file's tests:\n  "
        + "\n  ".join(violations)
        + "\n\nEither rename one file, or add --import-mode=importlib to that invocation."
    )
