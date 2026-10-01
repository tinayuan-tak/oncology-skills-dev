"""Skip-blind ratchet — no test may build a contracts Path from the bare dev-box literal.

The framework's cross-repo guards resolve target-contracts via
``Path(os.environ.get("TARGET_CONTRACTS_ROOT", "<dev default>"))``. CI exports
``TARGET_CONTRACTS_ROOT`` (``.github/workflows/skills-validate.yml``) to the runner's
checkout; the ``/home/sagemaker-user/...`` literal exists only on a developer box. A
test that instead builds the contracts root as a *bare*
``Path("/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")``
— with no env lookup — therefore points at a path that does not exist on CI, so any
``skipif``/``pytest.skip`` gated on "contracts present?" is always TRUE on the runner
and the guard SILENTLY SKIPS. CI runs ``pytest -q`` without ``-rs``, so the skip is
invisible in the log: SKIP != PASS, and the guard is green-blind. This bit ~19 guards,
including the safety-critical pan-essential veto (#1647).

The fix idiom keeps the literal ONLY as the ``os.environ.get`` / ``os.getenv`` default
(inline, or via a module constant that is then passed as that default) — there the
literal is an argument to the env lookup, never a direct argument to ``Path(...)``.
This ratchet enforces exactly that boundary: it flags any ``/home/sagemaker-user`` string
literal passed DIRECTLY to a ``Path(...)`` call. Re-introduce a bare-literal contracts
Path and this goes RED instead of the guard going dark on CI.

Enforcement-layer analog of #1644 for the skip-blind dimension: the defect is a
*missing* env-var edit, so guard the token.

SK#2137 EXTENSION: the sibling defect is a hardcoded ``$HOME/rnd-...`` (or
``Path.home() / "rnd-..."``) DEFAULT in PROD code — not a test skip, but a resolution
default that silently resolves to the ARCHIVED pre-monorepo-merge clones still sitting
at ``$HOME`` on the dev box, instead of this checkout's own contracts/methods trees
(SK#2063 folded target-contracts/analysis-methods IN as contracts/ and methods/).
``test_no_prod_code_hardcodes_the_home_rnd_default`` below ratchets that class shut
across the whole repo's non-test code, mirroring the exact enumeration grep used to
find and fix the original 62 offenders. ``contracts/validators/`` was temporarily
excluded pending #2090 (closed as the /nonexistent-shim retirement, unrelated); #2423
fixed the 5 remaining ``contracts/validators/`` literals and dropped that exclusion,
so the ratchet now covers that subtree too.

SK#2196 EXTENSION — the two blind spots that let this class survive #2137, each
measured as a live local-only RED:

  * that ratchet scans PROD code only, so the same defect in a *test* was invisible;
  * its regex only matches the ``$HOME`` literal and ``Path.home()``, so the
    equivalent **off-by-one upward walk** — ``SKILLS_DIR.parent.parent /
    "rnd-...-target-contracts"``, one level ABOVE the repo root — sailed through.
    (``REPO.parent / "rnd-..."`` from inside ``contracts/`` is the CORRECT form: it
    lands on the repo root, where the temporary geometry symlinks live. The defect is
    purely the extra ``.parent``.)

Why it bites asymmetrically, and only locally: ``analysis-methods`` and
``target-contracts`` were ABSORBED (SK#2063), and the archived clones are still sitting
at ``$HOME`` on the dev box. After the AM re-founding those clones' per-module
directories survive ONLY as untracked ``__pycache__`` shells, so ``$HOME/rnd-...-analysis-
methods`` on ``sys.path`` binds ``methods`` to a package whose submodules are EMPTY
namespace portions → ``ImportError: cannot import name X from methods.Y (unknown
location)``. A fresh CI checkout has no sibling clone at all, so the identical
expression is a silent no-op there and the editable install wins — CI green, local red.
``data-catalog`` is NOT in this class: it is still a genuine separate sibling repo, so
resolving it one level above the repo root is correct.

skills#2237 removed the *methods* half of that shadow at the root: the import package is now
``onc_methods``, so the archived clone's ``methods`` package no longer shares a name with
anything this repo imports and cannot bind it, whatever ends up on ``sys.path``. The rule
below is unchanged and still load-bearing — ``target-contracts`` is absorbed under its own
unchanged name, and a hardcoded path to an absorbed sibling is a defect regardless of which
module names happen to collide today.

``test_no_absorbed_sibling_resolved_outside_this_checkout`` ratchets both blind spots
shut across EVERY tracked ``.py`` (tests included, ``contracts/validators/`` included —
that carve-out does not apply to this narrower absorbed-sibling rule).
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_TOKEN = "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"

# Broader than _TOKEN: any $HOME/rnd-... sibling-repo literal, or a bare Path.home() chained
# straight onto one, regardless of which sibling repo (target-contracts/analysis-methods/
# data-catalog) it names. Mirrors SK#2137's enumeration grep.
_PROD_DEFAULT_RE = re.compile(r'sagemaker-user/rnd-|home\(\)\s*/\s*"rnd-')

# This file itself legitimately carries the literal tokens above (as the detector, and in this
# docstring) — exclude it from its own prod-code scan.
_THIS_FILE = Path(__file__).resolve()


def _tracked_test_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "skills/**/test_*.py", "skills/test_*.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [REPO_ROOT / p for p in out if Path(p).name.startswith("test_")]


def _is_path_call(call: ast.Call) -> bool:
    """True for ``Path(...)`` or ``pathlib.Path(...)``."""
    fn = call.func
    return (isinstance(fn, ast.Name) and fn.id == "Path") or (isinstance(fn, ast.Attribute) and fn.attr == "Path")


def test_no_test_builds_a_contracts_path_from_the_bare_literal() -> None:
    offenders: list[str] = []
    for path in _tracked_test_files():
        src = path.read_text()
        if _TOKEN not in src:
            continue
        tree = ast.parse(src, filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and _is_path_call(node)):
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and _TOKEN in arg.value:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{arg.lineno}")
    assert not offenders, (
        "Bare dev-box target-contracts literal passed directly to Path(...) — that path "
        "does not exist on CI, so any skip gated on it is always TRUE there and the guard "
        "silently skips (SKIP != PASS). Resolve via "
        'Path(os.environ.get("TARGET_CONTRACTS_ROOT", "<dev default>")) instead. '
        f"Offenders: {offenders}"
    )


def _tracked_prod_py_files() -> list[Path]:
    """All tracked .py files EXCLUDING tests. #2423 fixed the 5 contracts/validators/ offenders
    and dropped that subtree's former carve-out (issue #2090, closed, unrelated) — the ratchet
    now covers contracts/validators/ too."""
    out = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    files: list[Path] = []
    for rel in out:
        if Path(rel).name.startswith("test_"):
            continue
        if "/tests/" in rel or rel.startswith("tests/"):
            continue
        path = REPO_ROOT / rel
        if path == _THIS_FILE:
            continue
        files.append(path)
    return files


def test_no_prod_code_hardcodes_the_home_rnd_default() -> None:
    """Ratchet (SK#2137): no prod-code default may resolve to a `$HOME/rnd-...` sibling-clone
    path. Those clones are the ARCHIVED pre-monorepo checkouts — a hardcoded default silently
    reads a STALE tree instead of this checkout's own contracts/ or methods/ (or the genuinely-
    separate data-catalog sibling, which must resolve relative to the CURRENT checkout's own
    location, never a `/home/sagemaker-user` literal). Re-introduce one of these and this test
    goes RED instead of the class silently regrowing."""
    offenders: list[str] = []
    for path in _tracked_prod_py_files():
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if _PROD_DEFAULT_RE.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}")
    assert not offenders, (
        "Hardcoded $HOME/rnd-... sibling-repo default in prod code — that literal names the "
        "ARCHIVED pre-monorepo clone on the dev box, a stale-read hazard (SK#2137). Derive the "
        "default from this checkout's own location instead (repo-root-relative for "
        "contracts/methods via skills/_skills_common/paths.py's *_ROOT_DEFAULT constants, or a "
        "portable sibling-relative default matching methods.dge_deseq2.read.DATA_CATALOG for "
        f"data-catalog, which stays a separate repo). Offenders: {offenders}"
    )


# The two siblings SK#2063 ABSORBED into this repo. Their $HOME clones are archived and, for
# analysis-methods, gutted by the re-founding — resolving either one outside this checkout is
# always wrong. data-catalog is deliberately NOT here: it is still a real separate sibling.
_ABSORBED_SIBLINGS = (
    "rnd-computational-biology-oncology-analysis-methods",
    "rnd-computational-biology-oncology-target-contracts",
)
# The three ways a line can reach OUTSIDE this checkout: the dev-box absolute literal, Path.home(),
# or an upward walk that overshoots the repo root by one level. A SINGLE `.parent` onto the repo root
# — `REPO.parent / "rnd-..."` from inside contracts/, or `parents[N].parent` from inside methods/ —
# lands exactly where the temporary geometry symlinks live and is the CORRECT idiom (~50 live sites),
# so only the doubled `.parent.parent` form is flagged. An over-deep `parents[N]` is NOT statically
# distinguishable from a correct one (the right N depends on the file's own depth), so this ratchet
# does not claim to catch that form; #2144 retires the whole resolution surface.
_ESCAPE_RE = re.compile(r"/home/sagemaker-user|home\(\)|parent\.parent")


def _tracked_py_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [REPO_ROOT / rel for rel in out if (REPO_ROOT / rel).resolve() != _THIS_FILE]


def test_no_absorbed_sibling_resolved_outside_this_checkout() -> None:
    """Ratchet (SK#2196): no tracked .py — prod OR test — may name an ABSORBED sibling repo
    (analysis-methods / target-contracts) on a line that also reaches outside this checkout via the
    `/home/sagemaker-user` literal, `Path.home()`, or an over-deep `.parent.parent` / `parents[...]`
    walk. Such a path names the ARCHIVED pre-merge clone: locally that clone's gutted module tree
    turns `methods.<mod>` into an empty namespace portion (hard ImportError) or feeds STALE cards to
    a cross-check; on a CI runner the clone is absent, so the same expression is a silent no-op and
    the guard either passes for the wrong reason or SKIPS invisibly. That asymmetry is exactly what
    made the local gate diverge from CI. Use the in-tree `contracts/` / `methods/` (via
    `skills/_skills_common/paths.py`'s `*_root()` helpers or `*_ROOT_DEFAULT` constants) instead."""
    offenders: list[str] = []
    for path in _tracked_py_files():
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if not any(name in line for name in _ABSORBED_SIBLINGS):
                continue
            if _ESCAPE_RE.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}")
    assert not offenders, (
        "An ABSORBED sibling repo (analysis-methods / target-contracts) is resolved OUTSIDE this "
        "checkout — that names the archived pre-merge $HOME clone, which is gutted locally and "
        "absent on CI (SK#2196: local RED / CI green, or a silent skip). Resolve it in-tree: "
        "`target_contracts_root()` / `analysis_methods_root()` from skills/_skills_common/paths.py, "
        f"or `<repo root>/contracts` / `<repo root>/methods`. Offenders: {offenders}"
    )
