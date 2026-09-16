"""Every steps/ script must import the way DERIVE runs it, not the way the tests load it.

THE HAZARD, measured 2026-09-16. derive.py::stage_03 runs

    [PIXI, "run", "python", str(STEPS_DIR / "03_pool_and_write.py"), ...]

as a SUBPROCESS with no PYTHONPATH and no cwd, so `sys.path[0]` is the steps/ directory and the repo
root is absent. But every unit test loads these files with `spec_from_file_location` AFTER inserting
the repo root on `sys.path`. So a bare `from methods import <anything>` inside a step is:

  - GREEN in every unit test, because the test already put the repo root on sys.path, and
  - ModuleNotFoundError at PRODUCT-BUILD time, when derive.py actually runs the step.

And `byte-identity-live-s3` — the only job that exercises the real pipeline — is skipped on pull
requests (`if: github.event_name != 'pull_request'`, no OIDC token for PR-authored code). So nothing
in the PR gate would have caught it. Measured directly before writing this file: injecting a bare
`from methods import cell_absence` into 03_pool_and_write.py and invoking it the production way gave
`ModuleNotFoundError: No module named 'methods'` (rc 1), while the unit tests stayed green.

This test closes that gap for EVERY step in the directory, including the two that import nothing from
the repo today — the point is that adding such an import later must not be silently safe.

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
STEPS_DIR = REPO / "methods" / "cptac_protein_deg" / "steps"

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
    """Mutation guard: the assertion above is only evidence if a bare repo import really breaks.

    Writes a throwaway script INTO steps/ that imports a repo module without the bootstrap, and
    asserts it fails the same way. Without this, a change to how the subprocess is launched (an
    inherited PYTHONPATH, say) would make the test above vacuous and nothing would say so.
    """
    probe = STEPS_DIR / "_import_path_probe.py"
    probe.write_text("from methods import cell_absence  # no sys.path bootstrap\nprint('imported')\n")
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
        assert proc.returncode != 0, "a bare repo import from steps/ SUCCEEDED — the test above is vacuous"
        assert "ModuleNotFoundError" in proc.stdout + proc.stderr, proc.stdout + proc.stderr
    finally:
        probe.unlink(missing_ok=True)
