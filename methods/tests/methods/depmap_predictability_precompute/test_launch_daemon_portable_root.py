"""Portability + interpreter-pinning tests for launch_daemon.sh.

THE SECOND HALF OF THE SAME DEFECT (added 2026-09-17). The tests below pinned the TREE the
daemon imports. They did not pin the INTERPRETER that imports it, and the launcher resolved
`python` from PATH. On this box that is /opt/conda/bin/python3.12 — no `shap`, `xgboost 2.1.4`.
Because cli.py probes `import shap` at runtime inside the worker and swallows the ImportError
(`_has_shap`), a run under that interpreter DEGRADES to a non-SHAP ranking instead of failing:
it is the exact runtime that made the v3 vintage publish RF importances under an XGB label for
all 9,240 genes, over an ~11-day run that reported success throughout.

So the same sentence that justifies the PYTHONPATH derivation — "a wrong tree produces
valid-looking output, not an error" — applies verbatim to the interpreter, and a tree cannot
supply a dependency. `DEPMAP_PRECOMPUTE_PYTHON` exists ONLY as a test seam; the launcher never
falls back to PATH, and refuses to start (exit 3) when shap+xgboost do not import.

Original docstring follows.

Portability test for methods/depmap_predictability_precompute/launch_daemon.sh.

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


# The stub answers the launcher's TWO distinct invocations, which is why it has to branch on -c:
#   1. `$PYBIN -c 'import shap, xgboost'` -- the pre-flight dependency probe. `deps_ok` chooses
#      its exit status, which is the whole lever for the refusal test.
#   2. `$PYBIN -u -m methods...cli` -- the real child, whose env is the thing under test.
# It reports `$0` as well as PYTHONPATH so a test can tell WHICH interpreter ran, not merely that
# one did. Without that line, pinning the interpreter to the wrong file is indistinguishable from
# pinning it to the right one.
_STUB_BODY = """#!/usr/bin/env bash
for a in "$@"; do
  if [[ "$a" == "-c" ]]; then exit {probe_rc}; fi
done
printf "INTERPRETER=%s\\n" "$0"
printf "PYTHONPATH=%s\\n" "${{PYTHONPATH:-<unset>}}"
sleep {sleep_s}
exit 0
"""


def _write_stub_python(bin_dir: Path, name: str = "python", deps_ok: bool = True, sleep_s: int = 0) -> Path:
    """A fake interpreter: echoes its own path and the PYTHONPATH it got, then exits.

    `sleep_s` is how long the fake child lives, and it exists for ONE test. Everything else here
    wants a stub that exits at once (see _pythonpath_handed_to_child on why the launcher's rc is
    not asserted), but the launcher only prints its provenance summary AFTER a 2-second `kill -0`
    liveness check, so a zero-lifetime stub can never reach that branch. The sleep is short and
    self-terminating -- unlike keeping the real daemon alive, it leaves nothing behind on a shared
    box, since the detached child is this bash script and not the precompute.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / name
    stub.write_text(_STUB_BODY.format(probe_rc=0 if deps_ok else 1, sleep_s=sleep_s))
    stub.chmod(0o755)
    return stub


def _run_launcher(staged: Path, out_dir: Path, home: Path, path_dir: Path, pybin: Path | None):
    """Invoke the staged launcher. `pybin=None` exercises the PRODUCTION default."""
    env = {"PATH": f"{path_dir}:{BASE_PATH}", "HOME": str(home)}
    if pybin is not None:
        env["DEPMAP_PRECOMPUTE_PYTHON"] = str(pybin)
    return subprocess.run(
        ["bash", str(staged), str(out_dir)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _log_field(out_dir: Path, key: str, proc) -> str:
    log = out_dir / "daemon.log"
    assert log.is_file(), (
        f"launcher produced no daemon.log (rc={proc.returncode}).\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    lines = [ln for ln in log.read_text().splitlines() if ln.startswith(f"{key}=")]
    assert len(lines) == 1, (
        f"expected exactly one {key} line from the stub, got {lines!r} "
        f"(launcher rc={proc.returncode}, stderr: {proc.stderr})"
    )
    return lines[0].split("=", 1)[1]


def _pythonpath_handed_to_child(staged: Path, out_dir: Path, bin_dir: Path, home: Path) -> str:
    """Run the staged launcher against the stub and return the PYTHONPATH the child received.

    The launcher's own exit status is deliberately NOT asserted. The stub exits at once, so the
    launcher's 2-second `kill -0` liveness check fails by construction and it reports rc=1 — that
    is a property of the stub, not of the code under test. Keeping the stub alive long enough to
    satisfy the check would leave `setsid`-detached processes behind on a box shared with other
    sessions, which is a real cost for no added coverage.

    The interpreter is now PINNED rather than resolved from PATH, so these PYTHONPATH tests have
    to hand the stub in explicitly via the override. The tests that cover the pin itself, and the
    production default, are below.
    """
    stub = _write_stub_python(bin_dir)
    proc = _run_launcher(staged, out_dir, home, path_dir=bin_dir, pybin=stub)
    # If the launcher never reached the child, _log_field says so with its own output rather than
    # failing on a confusing empty-string comparison further down.
    return _log_field(out_dir, "PYTHONPATH", proc)


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


# ---------------------------------------------------------------------------------------------
# The interpreter half. Same failure mode as the tree, one layer down: the wrong interpreter is
# missing `shap`, `_has_shap` swallows the ImportError, and the run emits RF importances under an
# XGB label for days without erroring.
# ---------------------------------------------------------------------------------------------


def _stage_pixi_interpreter(root: Path, deps_ok: bool = True, sleep_s: int = 0) -> Path:
    """Put a fake interpreter exactly where the launcher's DEFAULT expects to find one."""
    return _write_stub_python(root / ".pixi" / "envs" / "default" / "bin", deps_ok=deps_ok, sleep_s=sleep_s)


def test_interpreter_default_is_the_checkouts_pixi_env_with_no_override(tmp_path):
    """THE TEST THAT MATTERS MOST, because it is the only path production takes.

    Every other test here hands the launcher an interpreter through DEPMAP_PRECOMPUTE_PYTHON. That
    variable is a TEST SEAM and is never set in real use, so a suite built only on it would go
    green with a typo'd default -- the classic shape where the tests exercise a branch the product
    doesn't. This one sets no override at all and asserts the launcher finds the interpreter inside
    the checkout it resolved.

    PATH deliberately contains NO `python`, which makes the assertion double-duty: the launcher
    cannot have fallen back to a PATH lookup, because there was nothing there to find.
    """
    root = tmp_path / "checkout"
    staged = _stage_launcher(root)
    pinned = _stage_pixi_interpreter(root)
    empty_path_dir = tmp_path / "empty-bin"
    empty_path_dir.mkdir()

    proc = _run_launcher(staged, tmp_path / "out", tmp_path / "fake-home", empty_path_dir, pybin=None)
    used = _log_field(tmp_path / "out", "INTERPRETER", proc)

    assert Path(used).resolve() == pinned.resolve(), (
        f"launcher ran {used!r}; expected the checkout's own pixi interpreter {pinned}"
    )
    # The defect being fenced: a bare `python`, resolved from PATH, landing on the conda base env.
    assert Path(used).name != "python3.12"
    assert "/opt/conda/" not in used


def test_interpreter_default_moves_with_the_checkout(tmp_path):
    """POSITIVE CONTROL for the default: it must be DERIVED, not a constant.

    A launcher that hardcoded one absolute pixi path would satisfy the test above whenever the
    fixture happened to match. Requiring the interpreter to move between two staged checkouts is
    what proves the default is computed from $METHODS_REPO per invocation -- the same argument as
    test_resolved_root_moves_with_the_checkout, applied to the interpreter.
    """
    used = []
    for name in ("alpha", "beta"):
        root = tmp_path / name
        staged = _stage_launcher(root)
        _stage_pixi_interpreter(root)
        empty = tmp_path / f"empty-{name}"
        empty.mkdir()
        proc = _run_launcher(staged, tmp_path / f"out-{name}", tmp_path / "fake-home", empty, pybin=None)
        used.append(_log_field(tmp_path / f"out-{name}", "INTERPRETER", proc))

    assert Path(used[0]).resolve() == (tmp_path / "alpha" / ".pixi/envs/default/bin/python").resolve()
    assert Path(used[1]).resolve() == (tmp_path / "beta" / ".pixi/envs/default/bin/python").resolve()
    assert used[0] != used[1], (
        "the interpreter did not move between two staged checkouts, so it is a hardcoded path rather than a derivation"
    )


def test_a_python_earlier_on_path_is_never_used(tmp_path):
    """PATH must not be able to choose the interpreter, even when it plausibly could.

    This is the pre-fix behaviour stated as a prohibition. The staged root gets its own pixi
    interpreter AND a decoy `python` sits first on PATH; only the former may run.
    """
    root = tmp_path / "checkout"
    staged = _stage_launcher(root)
    pinned = _stage_pixi_interpreter(root)
    decoy_dir = tmp_path / "decoy-bin"
    decoy = _write_stub_python(decoy_dir)

    # CONTROL: the decoy is genuinely a viable candidate -- executable, named `python`, and first
    # on PATH. Without this, "the decoy did not run" could just mean the decoy was unusable, and
    # the test would pass against a launcher that still resolved from PATH.
    assert shutil.which("python", path=f"{decoy_dir}:{BASE_PATH}") == str(decoy)

    proc = _run_launcher(staged, tmp_path / "out", tmp_path / "fake-home", decoy_dir, pybin=None)
    used = Path(_log_field(tmp_path / "out", "INTERPRETER", proc)).resolve()

    assert used == pinned.resolve()
    assert used != decoy.resolve(), "launcher took the interpreter from PATH -- the pin is not in force"


def test_refuses_to_start_when_the_interpreter_cannot_import_shap(tmp_path):
    """The refusal is the point of the change: this absence has to be LOUD.

    `_has_shap` catches ImportError by design, so a missing `shap` cannot surface downstream --
    the run succeeds and the wrong columns ship. The launcher is the only place left to fail.
    Asserted on rc==3 specifically, not merely non-zero: the liveness check below also exits 1,
    and a test that accepted any failure would pass when the launcher broke for a different reason.
    """
    root = tmp_path / "checkout"
    staged = _stage_launcher(root)
    _stage_pixi_interpreter(root, deps_ok=False)
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    out_dir = tmp_path / "out"

    proc = _run_launcher(staged, out_dir, tmp_path / "fake-home", empty, pybin=None)

    assert proc.returncode == 3, (
        f"expected rc=3 (dependency refusal), got {proc.returncode}.\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    # No daemon may exist: the refusal precedes `mkdir -p "$OUT_DIR"`, so not even the out-dir is
    # created. A launcher that started the child and THEN complained would leave a multi-day run
    # going, which is exactly the outcome being prevented.
    assert not (out_dir / "daemon.log").exists(), "launcher started the child despite refusing"
    assert not (out_dir / "daemon.pid").exists()
    assert "shap" in proc.stderr, f"refusal did not name the missing dependency: {proc.stderr!r}"


def test_the_dependency_probe_is_what_gates_the_refusal(tmp_path):
    """POSITIVE CONTROL for the refusal: flipping ONLY the probe's exit status flips the outcome.

    One variable moves. If the launcher refused for any other reason -- an unrelated `set -u`
    trip, a missing directory -- this identical fixture with a passing probe would also fail here.
    """
    root = tmp_path / "checkout"
    staged = _stage_launcher(root)
    _stage_pixi_interpreter(root, deps_ok=True)
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    out_dir = tmp_path / "out"

    proc = _run_launcher(staged, out_dir, tmp_path / "fake-home", empty, pybin=None)

    assert proc.returncode != 3, f"launcher refused even though the probe succeeded: {proc.stderr}"
    assert (out_dir / "daemon.log").is_file(), (
        f"launcher did not reach the child with a passing probe.\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
    )


def test_refuses_to_start_when_the_pinned_interpreter_does_not_exist(tmp_path):
    """A missing pixi env is a hard stop (rc=2), never a PATH fallback.

    Separate exit code from the import refusal so an operator reading a CI log can tell "run
    `pixi install`" apart from "that env is missing shap".
    """
    root = tmp_path / "checkout"
    staged = _stage_launcher(root)  # note: no _stage_pixi_interpreter call
    decoy_dir = tmp_path / "decoy-bin"
    _write_stub_python(decoy_dir)  # a usable `python` on PATH, which must NOT rescue the run
    out_dir = tmp_path / "out"

    proc = _run_launcher(staged, out_dir, tmp_path / "fake-home", decoy_dir, pybin=None)

    assert proc.returncode == 2, (
        f"expected rc=2 (interpreter absent), got {proc.returncode}.\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    assert not (out_dir / "daemon.log").exists()


def test_the_launcher_logs_which_interpreter_it_used(tmp_path):
    """Provenance in the operator-facing log.

    The v3 run's log looked completely healthy for ~11 days. Nothing in it named the interpreter,
    so the one fact that would have exposed the defect was the one fact not recorded.

    The only test in this file that needs the launcher to reach its success branch, hence the
    3-second stub lifetime clearing the 2-second liveness check.
    """
    root = tmp_path / "checkout"
    staged = _stage_launcher(root)
    pinned = _stage_pixi_interpreter(root, sleep_s=3)
    empty = tmp_path / "empty-bin"
    empty.mkdir()

    proc = _run_launcher(staged, tmp_path / "out", tmp_path / "fake-home", empty, pybin=None)

    assert proc.returncode == 0, (
        f"launcher did not reach its success branch (rc={proc.returncode}).\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    assert f"interpreter={pinned}" in proc.stdout, (
        f"launcher did not report the interpreter it used.\nstdout: {proc.stdout}"
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
