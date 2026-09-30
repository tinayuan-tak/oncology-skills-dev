"""Every steps/ script must import the way DERIVE runs it, not the way the tests load it.

THE HAZARD, measured 2026-09-16. derive.py::stage_03 runs

    [PIXI, "run", "python", str(STEPS_DIR / "03_pool_and_write.py"), ...]

as a SUBPROCESS with no PYTHONPATH and no cwd, so `sys.path[0]` is the steps/ directory and the repo
root is absent. But every unit test loads these files with `spec_from_file_location` AFTER inserting
the repo root on `sys.path`. So an import inside a step that only resolves via the repo root is:

  - GREEN in every unit test, because the test already put the repo root on sys.path, and
  - ModuleNotFoundError at PRODUCT-BUILD time, when derive.py actually runs the step.

And `byte-identity-live-s3` — the only job that exercises the real pipeline — is skipped on pull
requests (`if: github.event_name != 'pull_request'`, no OIDC token for PR-authored code). So nothing
in the PR gate would have caught it. Measured directly before writing this file: injecting a bare
`from methods import cell_absence` into 03_pool_and_write.py and invoking it the production way gave
`ModuleNotFoundError: No module named 'methods'` (rc 1), while the unit tests stayed green. (`methods`
was the import package's name then; skills#2237 renamed it `onc_methods` — see below.)

This test closes that gap for EVERY step in the directory, including the two that import nothing from
the repo today — the point is that adding such an import later must not be silently safe.

⚠️ Updated for SK#2145 (one pixi workspace) and skills#2237 (the rename). The measured claim in the
paragraph above — that a bare `from methods import ...` inside a step gives `ModuleNotFoundError`
under the production launch — was true of the DELETED `methods/pixi.toml` env, which never installed
this package into the env its own suite ran under. There is now one workspace, `pixi run python`
resolves it, and it editable-installs the package (named `onc_methods` since skills#2237), so
`from onc_methods import ...` is production-safe today. The hazard class is NOT gone and this file
still guards it: anything reachable only via the REPO ROOT on `sys.path` (the `tests/` tree, a
scratch module beside `pyproject.toml`) is still absent at product-build time. See
`test_the_check_can_actually_fail` for the full reconstruction.

Why `--help`: module-level imports run before argparse, so a successful `--help` (which argparse
exits 0 on) is exactly the observation "this file imports cleanly under the production sys.path".
No S3, no data, no R.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
STEPS_DIR = REPO / "onc_methods" / "cptac_protein_deg" / "steps"

# Only .py steps — 02_msstats_deg.R is R and is invoked through Rscript.
STEP_SCRIPTS = sorted(p.name for p in STEPS_DIR.glob("*.py") if not p.name.startswith("_"))


def test_there_are_steps_to_check():
    """Guard against this file silently passing because the glob found nothing."""
    assert STEP_SCRIPTS, f"no step scripts found under {STEPS_DIR}"
    assert "03_pool_and_write.py" in STEP_SCRIPTS, STEP_SCRIPTS


@pytest.mark.parametrize("script", STEP_SCRIPTS)
def test_step_imports_under_the_production_sys_path(script, tmp_path):
    """Invoke the step the way derive.py does: bare interpreter, no PYTHONPATH, cwd elsewhere.

    Deliberately NOT `pixi run` — that would make the test depend on a pixi binary and on network for
    a first-time env solve. Running the CURRENT interpreter reproduces the property under test
    (sys.path[0] == the script's own directory, repo root absent), because pytest's own sys.path
    entries are not inherited: a fresh `python <path>` builds sys.path from scratch.
    """
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    # -I would also drop site-packages (pandas/pyarrow live there), so isolate only what matters:
    # the repo root must not arrive via PYTHONPATH or the inherited cwd.
    proc = subprocess.run(
        [sys.executable, str(STEPS_DIR / script), "--help"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
        timeout=180,
    )
    combined = proc.stdout + proc.stderr
    assert "ModuleNotFoundError" not in combined, (
        f"{script} cannot import itself the way derive.py runs it — this is the CI-green/"
        f"production-broken case:\n{combined[-2000:]}"
    )
    assert proc.returncode == 0, f"{script} --help exited {proc.returncode}:\n{combined[-2000:]}"


def test_the_check_can_actually_fail(tmp_path):
    """Mutation guard: the assertion above is only evidence if the repo root is really unreachable.

    Writes a throwaway module at the repo root and a throwaway script INTO steps/ that imports it
    without a bootstrap, and asserts the import fails. Without this, a change to how the subprocess
    is launched (an inherited PYTHONPATH, say) would make the test above vacuous and nothing would
    say so.

    ⚠️ SK#2145 changed this guard's SUBJECT, and the reason is worth recording, because it is the
    dual-runtime drift that issue deleted showing its teeth. The probe used to be
    `from methods import cell_absence`, asserted to FAIL. But that never tested the repo root's
    absence — it tested "no interpreter here can import `methods`", which was true ONLY in the old
    `methods/pixi.toml` env, whose `[pypi-dependencies]` was empty, so this package was never
    installed into the env its OWN suite ran under. The repo-root env editable-installed it all
    along. So on `main`, same tree and same commit, this test PASSED under `methods/pixi.toml` and
    FAILED under the root `pixi.toml` — a green that was an artifact of which of two environments
    happened to run it. With one workspace there is one answer: the package (`onc_methods` since
    skills#2237) IS importable from a bare interpreter, because `pixi run python` — exactly how
    `derive.py` launches every step — now resolves the one env that installs it.

    That makes the parametrized test above STRONGER, not weaker. Production and tests now share one
    interpreter, so "this step imports cleanly here" means "it imports cleanly there" by
    construction, instead of depending on every step hand-rolling its own sys.path bootstrap.

    The ORIGINAL hazard is untouched and is what this guard now probes: a step reaching something
    importable only because the REPO ROOT is on sys.path — the `tests/` tree, a scratch module
    beside `pyproject.toml`, anything outside the installed `onc_methods*` packages. Two independent
    channels, because each catches what the other misses: an explicit assertion on the subprocess's
    own `sys.path` (catches a PYTHONPATH/`.pth` leak of this exact path, and names it), and an
    import of a repo-root-only module (catches a leak in any other spelling — a symlink, a relative
    entry — that the string comparison would miss).
    """
    probe = STEPS_DIR / "_import_path_probe.py"
    # NOT under methods/onc_methods/ — the point is that this module is outside the installed
    # `onc_methods*` packages, so it is reachable ONLY if the repo root is on the subprocess's path.
    sentinel = REPO / "_repo_root_reachability_sentinel.py"
    probe.write_text(
        "import sys\n"
        f"assert {str(REPO)!r} not in sys.path, 'repo root LEAKED into the production sys.path: ' + repr(sys.path)\n"
        "import _repo_root_reachability_sentinel  # repo-root-only; no sys.path bootstrap\n"
        "print('imported')\n"
    )
    sentinel.write_text("SENTINEL = 1  # written by test_the_check_can_actually_fail; unlinked below\n")
    try:
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        proc = subprocess.run(
            [sys.executable, str(probe)],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(tmp_path),
            timeout=180,
        )
        combined = proc.stdout + proc.stderr
        assert proc.returncode != 0, (
            f"a repo-root-only import from steps/ SUCCEEDED — the test above is vacuous:\n{combined[-2000:]}"
        )
        assert "ModuleNotFoundError" in combined, combined
    finally:
        probe.unlink(missing_ok=True)
        sentinel.unlink(missing_ok=True)
