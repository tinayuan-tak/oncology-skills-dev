"""Shared test-support helpers for the skills test suites (importable helpers, NOT pytest fixtures).

Tests already put skills/ on sys.path (`sys.path.insert(0, SKILLS_ROOT)`), so this module is importable
as `_test_support`. It deliberately does NOT live under `_skills_common` (that is production code) and is
not itself a test module (pytest never collects it — no `test_` prefix).

It removes the most-copied test boilerplate: the "load a script as an isolated module" triple
    spec = importlib.util.spec_from_file_location(NAME, PATH)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
which was re-declared as a local `_load()` (or an ad-hoc `import run as X`) in ~180 test files.
`load_module()` is that triple; `load_run_py()` is the run.py convenience wrapper.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module(path, name: str | None = None):
    """Load the Python file at `path` as a fresh, isolated module and return it.

    The module is executed but NOT registered in sys.modules, so loading many scripts (e.g. several
    skills' run.py) in one process never cross-contaminates — preserving the isolation the hand-rolled
    `spec_from_file_location(...)` shims relied on. `name` sets the module __name__ (useful in
    tracebacks); it defaults to the file stem and is otherwise cosmetic.
    """
    path = Path(path)
    spec = importlib.util.spec_from_file_location(name or path.stem, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load a module spec from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_run_py(skill_dir, name: str | None = None):
    """Load a skill's scripts/run.py as an isolated module (see `load_module`).

    Ensures skills/ and the skill's scripts/ are on sys.path first so run.py's own imports
    (`_skills_common`, sibling scripts) resolve — replacing the per-file `sys.path.insert(...)` +
    `def _load()` (or `import run as X`) boilerplate. `skill_dir` is the skill root (skills/<skill>/).
    """
    skill_dir = Path(skill_dir)
    for p in (skill_dir.parent, skill_dir / "scripts"):  # skills/ , skills/<skill>/scripts/
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    return load_module(skill_dir / "scripts" / "run.py", name=name)
