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

A STEP'S PATHS ARE RELATIVE TO ITS OWN ``working-directory`` (skills#2237)
-------------------------------------------------------------------------
The first version of this parser resolved every pytest path argument against the REPO
ROOT, regardless of which step it came from. That was wrong, and it read green for a
coincidental reason: the methods leg runs ``working-directory: <checkout>/methods`` with
``pytest methods/ tests/``, and the token ``methods/`` *also happened to name a real
directory at the repo root*, so the whole distribution was credited by accident while
the sibling token ``tests/`` was silently discarded (there is no ``<root>/tests``).
skills#2237 renamed the import package to ``onc_methods``, the accident stopped holding,
and 100+ methods test files went from "covered by luck" to visibly uncovered — the guard
finding its own blind spot.

So each step is now resolved against its own base directory: the step's (or the job's
``defaults.run``) ``working-directory``, with the runner's checkout-path component
stripped so ``<checkout-dir>/methods`` lands on this repo's ``methods/``. A step whose
base cannot be resolved to a real directory contributes nothing — a stale workflow path
can never *widen* coverage.

``test_working_directory_resolution_is_load_bearing`` re-runs the extraction with the old
repo-root-relative behaviour and requires that it LOSE coverage: without that control,
the cwd-aware resolution could rot into dead code and the next rename would look green.

A BARE ``pytest`` CREDITS ITS WHOLE WORKING DIRECTORY — AND ONLY A BARE ONE
--------------------------------------------------------------------------
``contracts-pytest`` pins ``working-directory: contracts`` and runs ``python -m pytest``
with no path arguments, collecting that package's entire tree (the whole-repo safety net
the old target-contracts CI ran, relocated in SK#2063). That shape is recognised
explicitly. It is *only* credited when the invocation really has no path arguments, and
only when the token is a pytest COMMAND — ``pip install ... pytest pytest-xdist`` names
pytest as a dependency and must never be read as running it.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "skills-validate.yml"

# pytest collects files whose basename matches this (the default python_files); a broader
# shell glob like ``*test_*.py`` also matches scripts such as eval/backtest_per_axis.py that
# pytest never collects, so match pytest's own rule, not the shell's.
_COLLECTABLE = "test_*.py"

# shell command separators — a run: block is many commands, and only the token that starts
# a command can be the pytest invocation.
_SEP = re.compile(r"[;|&\n]+")

# tokens that may legitimately precede `pytest` and still leave it the command being run
_PYTEST_PREFIXES = (None, "run", "-m", "exec", "then", "do", "&&", "||")


def _noncomment_lines(text: str) -> str:
    """Drop whole-line comments — both YAML ``#`` lines and bash ``#`` lines inside a
    ``run:`` block scalar — so a path mentioned in prose (e.g. the comment explaining why
    ``pytest skills/`` in one process was wrong) is never mistaken for an invoked root."""
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def _resolve_base(working_directory: str | None) -> Path | None:
    """The directory a step's relative paths are resolved against, or None if unresolvable.

    ``working-directory`` is relative to the RUNNER WORKSPACE, not to this repo: the
    checkout steps place this repo in a named subdirectory, so the methods leg says
    ``<checkout-dir>/methods``. Try the token as-is first (jobs that check out at the
    workspace root, e.g. ``working-directory: contracts``), then with its leading
    component stripped. A token that names only the checkout dir resolves to the repo root
    itself, which is correct — that job's cwd IS the repo root.
    """
    if not working_directory:
        return REPO_ROOT
    tok = working_directory.strip().strip("\"'").rstrip("/")
    if not tok or "$" in tok or "{{" in tok:
        return None
    parts = Path(tok).parts
    candidates = [REPO_ROOT / tok, REPO_ROOT.joinpath(*parts[1:])]  # as-is, then checkout-dir stripped
    for cand in candidates:
        if cand.is_dir():
            return cand.resolve()
    return None


def _pytest_arg_lists(script: str) -> list[list[str]]:
    """Every pytest invocation in a run: block, as its argument list.

    Requires the token before ``pytest`` to be one that leaves pytest the command being
    executed (``pixi run pytest``, ``python -m pytest``, or a command start). This is what
    keeps ``pip install --upgrade ... pytest pytest-xdist`` from reading as a test run —
    the previous regex-only extractor would have treated it as a BARE pytest had the
    dependency list happened to end with ``pytest``, silently crediting the whole package.
    """
    out: list[list[str]] = []
    for seg in _SEP.split(_noncomment_lines(script)):
        toks = seg.split()
        for i, tok in enumerate(toks):
            if tok != "pytest":
                continue
            if (toks[i - 1] if i else None) not in _PYTEST_PREFIXES:
                continue
            out.append(toks[i + 1 :])
    return out


def _path_args(args: list[str]) -> list[str]:
    """Leading path arguments — everything up to the first flag (the methods leg passes two)."""
    paths: list[str] = []
    for a in args:
        if a.startswith("-"):
            break
        paths.append(a)
    return paths


def _steps() -> list[tuple[Path | None, str]]:
    """(base_dir, run_script) for every workflow step that runs a shell command."""
    assert WORKFLOW.is_file(), f"workflow not found at {WORKFLOW}"
    doc = yaml.safe_load(WORKFLOW.read_text())
    steps: list[tuple[Path | None, str]] = []
    for job in (doc.get("jobs") or {}).values():
        job_wd = ((job.get("defaults") or {}).get("run") or {}).get("working-directory")
        for step in job.get("steps") or []:
            script = step.get("run")
            if not script:
                continue
            steps.append((_resolve_base(step.get("working-directory") or job_wd), script))
    return steps


def _covered_dirs(cwd_aware: bool = True) -> set[Path]:
    """Directories the workflow actually runs pytest against.

    Every candidate must resolve to a real directory to count — this drops quoting/backtick
    debris and any ``"$d"``-style loop variable, and means a stale path in the workflow can
    never *widen* coverage. Pass ``cwd_aware=False`` to resolve PATH ARGUMENTS against the
    repo root instead — the pre-#2237 behaviour. That mode exists only so
    ``test_working_directory_resolution_is_load_bearing`` can prove this argument matters;
    note it mutates only the path-argument base, because a bare ``pytest`` re-based on the
    repo root would credit the entire tree and make every comparison vacuously equal.
    """
    covered: set[Path] = set()
    for base, script in _steps():
        if base is None:
            continue
        arg_base = base if cwd_aware else REPO_ROOT
        candidates: set[str] = set()
        for args in _pytest_arg_lists(script):
            paths = _path_args(args)
            if not paths:
                # bare `pytest` collects the whole working directory (contracts-pytest)
                covered.add(base)
                continue
            candidates.update(paths)
        # glob-driven loop: `for d in skills/*/tests; do ... pytest "$d" ...`
        for src in re.findall(r"\bfor\s+\w+\s+in\s+([^\n;]+?)\s*;?\s*do\b", _noncomment_lines(script)):
            candidates.update(src.split())

        for raw in candidates:
            tok = raw.strip().strip("\"'`").rstrip("/")
            if not tok or tok.startswith("-") or "$" in tok:
                continue
            if any(ch in tok for ch in "*?[]"):
                covered.update(p.resolve() for p in arg_base.glob(tok) if p.is_dir())
            else:
                p = (arg_base / tok).resolve()
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


def test_working_directory_resolution_is_load_bearing():
    """Resolving a step's path arguments against its own working-directory must MATTER.

    Re-runs the extraction with the pre-#2237 behaviour (path arguments relative to the repo
    root) and requires that it lose coverage. If both give the same answer, the cwd-aware
    resolution is dead code — and the next time a path arg stops coinciding with a
    repo-root directory name, the real assertion below would report a false RED (or, worse,
    a token that coincides again would restore a false GREEN, which is precisely how the
    methods leg read as covered before skills#2237).
    """
    real = _covered_dirs()
    naive = _covered_dirs(cwd_aware=False)
    lost = [f for f in _collectable_test_files() if _is_covered(f, real) and not _is_covered(f, naive)]
    assert lost, (
        "resolving every pytest path against the repo root covers exactly as much as "
        "resolving it against each step's working-directory, so the cwd-aware code path is "
        "untested dead weight — delete it or fix the extractor"
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
