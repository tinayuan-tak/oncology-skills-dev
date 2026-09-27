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
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_TOKEN = "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"


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
