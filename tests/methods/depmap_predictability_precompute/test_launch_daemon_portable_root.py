"""Portability test for methods/depmap_predictability_precompute/launch_daemon.sh.

The launcher hardcoded `METHODS_REPO=/home/sagemaker-user/rnd-...-analysis-methods` and fed it
to the detached child as PYTHONPATH. That is the last code site of a defect swept five times
(AM#631/632/634/635/637); the ~33 remaining grep hits for the literal are comments describing
those earlier fixes, not live sites.

Why it matters more here than in a normal path default: the value is not consumed by anything
that would reject it. It becomes PYTHONPATH for a `setsid`-detached process that then runs for
days. Launched from a worktree, the daemon would import a DIFFERENT checkout than the one it was
started from and emit valid-looking parquet from it — a wrong tree produces wrong output, never
an error.

Two constraints shaped this file:

  * A LOCAL RUN CANNOT FALSIFY IT. On this dev box $HOME is the checkout parent, so the hardcoded
    literal and the correct derivation are the SAME STRING. A test that runs the real launcher in
    the real checkout therefore passes identically before and after the fix. Every test below
    stages a COPY at a temp root, which is what makes the two answers diverge, and pairs the
    negative assertion with a POSITIVE CONTROL that makes the resolved root MOVE — an invariant
    string is otherwise indistinguishable from a launcher that never reached the line.
    Measured against the pre-fix script: it reports the /home literal and these tests fail.
    HOME is also set to a directory that is neither the staged root nor the real checkout, so a
    future "fix" spelled `$HOME/rnd-...` fails here too rather than passing by coincidence.

  * IT MUST NOT LAUNCH THE REAL DAEMON. `python -m methods.depmap_predictability_precompute.cli`
    is a multi-day, multi-worker DepMap precompute that reads S3. A stub `python` on a PREPENDED
    PATH stands in for it (prepended, never a replacement: the launcher needs real setsid/nohup/
    env/mkdir, and a replaced PATH would fail for the wrong reason). The child's environment is
    observable at all only because the launcher redirects its stdout into <out_dir>/daemon.log.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
LAUNCHER = REPO / "methods" / "depmap_predictability_precompute" / "launch_daemon.sh"

# PREPENDED to, never substituted for, the tools the launcher genuinely needs.
BASE_PATH = "/usr/bin:/bin"


def _stage_launcher(root: Path) -> Path:
    """Copy the launcher into a fake checkout at its real depth (methods/<pkg>/launch_daemon.sh).

    The depth is the whole point: the derivation walks up exactly two directories, so staging it
    at the wrong depth would make a correct launcher look broken.
    """
    pkg_dir = root / "methods" / "depmap_predictability_precompute"
    pkg_dir.mkdir(parents=True)
    staged = pkg_dir / LAUNCHER.name
    shutil.copy2(LAUNCHER, staged)
    return staged


def _write_stub_python(bin_dir: Path) -> None:
    """A `python` that echoes the PYTHONPATH it was handed, then exits immediately."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "python"
    stub.write_text('#!/usr/bin/env bash\nprintf "PYTHONPATH=%s\\n" "${PYTHONPATH:-<unset>}"\nexit 0\n')
    stub.chmod(0o755)


def _pythonpath_handed_to_child(staged: Path, out_dir: Path, bin_dir: Path, home: Path) -> str:
    """Run the staged launcher against the stub and return the PYTHONPATH the child received.

    The launcher's own exit status is deliberately NOT asserted. The stub exits at once, so the
    launcher's 2-second `kill -0` liveness check fails by construction and it reports rc=1 — that
    is a property of the stub, not of the code under test. Keeping the stub alive long enough to
    satisfy the check would leave `setsid`-detached processes behind on a box shared with other
    sessions, which is a real cost for no added coverage.
    """
    _write_stub_python(bin_dir)
    proc = subprocess.run(
        ["bash", str(staged), str(out_dir)],
        env={"PATH": f"{bin_dir}:{BASE_PATH}", "HOME": str(home)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    log = out_dir / "daemon.log"
    # If the launcher never reached the child, say so with its own output rather than failing on
    # a confusing empty-string comparison further down.
    assert log.is_file(), (
        f"launcher produced no daemon.log (rc={proc.returncode}).\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    lines = [ln for ln in log.read_text().splitlines() if ln.startswith("PYTHONPATH=")]
    assert len(lines) == 1, (
        f"expected exactly one PYTHONPATH line from the stub, got {lines!r} "
        f"(launcher rc={proc.returncode}, stderr: {proc.stderr})"
    )
    return lines[0].split("=", 1)[1]


def test_pythonpath_is_the_staged_checkout_not_the_authors_home(tmp_path):
    """The daemon must import the checkout it was launched from."""
    root = tmp_path / "checkout"
    staged = _stage_launcher(root)
    resolved = _pythonpath_handed_to_child(staged, tmp_path / "out", tmp_path / "bin", tmp_path / "fake-home")

    assert Path(resolved) == root.resolve(), (
        f"launcher handed the child PYTHONPATH={resolved!r}, expected the staged checkout {root.resolve()}"
    )
    # This is the assertion that fails on the pre-fix launcher, which reported the author's
    # own checkout regardless of where it was invoked from.
    assert Path(resolved) != REPO, (
        "launcher resolved to the author's real checkout while running from a staged copy — "
        "the repo root is still hardcoded"
    )
    # A $HOME-anchored spelling would land here instead.
    assert Path(resolved) != tmp_path / "fake-home"


def test_resolved_root_moves_with_the_checkout(tmp_path):
    """POSITIVE CONTROL: two staged copies must report their OWN roots.

    Without this, a launcher that emitted any constant string — including one that happened to
    match the first fixture — would pass the test above. Requiring the value to MOVE proves the
    derivation line is actually evaluated per invocation.
    """
    resolved = []
    for name in ("first", "second"):
        root = tmp_path / name
        staged = _stage_launcher(root)
        resolved.append(
            _pythonpath_handed_to_child(
                staged,
                tmp_path / f"out-{name}",
                tmp_path / f"bin-{name}",
                tmp_path / "fake-home",
            )
        )

    assert Path(resolved[0]) == (tmp_path / "first").resolve()
    assert Path(resolved[1]) == (tmp_path / "second").resolve()
    assert resolved[0] != resolved[1], (
        "the resolved repo root did not move between two staged checkouts, so it is a constant rather than a derivation"
    )


def test_this_launcher_carries_no_hardcoded_absolute_home_path():
    """Cheap regression fence, scoped to THIS ONE FILE.

    Named for what it actually covers: it is a property of launch_daemon.sh, not an invariant of
    the repo. A repo-wide sweep is a separate concern and would have to classify comment hits
    (33 of the 34 current matches for the literal are comments describing past fixes).
    """
    text = LAUNCHER.read_text()
    offenders = [ln.strip() for ln in text.splitlines() if "/home/" in ln and not ln.lstrip().startswith("#")]
    assert not offenders, f"hardcoded absolute home path in executable lines: {offenders}"
