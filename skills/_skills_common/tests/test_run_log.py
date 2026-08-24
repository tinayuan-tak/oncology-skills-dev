"""run_log — stdout+stderr tee for development + provenance (2026-08-24).

Every wired skill routes through `run_wired_skill`, which installs this tee so its backend
narration is mirrored to `<out>/run.log` (per-line UTC-stamped) as a durable audit trail.
These are offline guards on the tee mechanics — no S3, no dispatcher, no main() invocation.
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent            # skills/_skills_common
sys.path.insert(0, str(SKILL_DIR.parent))                     # skills/ on path

from _skills_common import run_log  # noqa: E402


def test_tee_captures_both_streams_with_stamps_and_header(tmp_path):
    orig_out, orig_err = sys.stdout, sys.stderr
    try:
        assert run_log.install_run_log(tmp_path, header={"skill": "demo", "skill_version": "9.9.9"})
        print("hello from stdout")
        print("[demo] a warning", file=sys.stderr)
    finally:
        run_log.restore_run_log()

    # Streams restored to exactly what they were before install.
    assert sys.stdout is orig_out and sys.stderr is orig_err

    log = (tmp_path / "run.log").read_text()
    assert "# run log" in log
    assert "# skill: demo" in log and "# skill_version: 9.9.9" in log
    assert "# started_at:" in log and "# argv:" in log

    out_lines = [ln for ln in log.splitlines() if " OUT " in ln and "hello from stdout" in ln]
    err_lines = [ln for ln in log.splitlines() if " ERR " in ln and "a warning" in ln]
    assert out_lines and err_lines
    assert out_lines[0].startswith("20") and out_lines[0][10] == "T"   # ISO-8601 UTC stamp prefix


def test_live_stream_is_preserved(tmp_path, capsys):
    try:
        run_log.install_run_log(tmp_path)
        print("still live")
    finally:
        run_log.restore_run_log()
    assert "still live" in capsys.readouterr().out


def test_install_is_idempotent_no_tee_stacking(tmp_path):
    # A harness that runs a skill twice in one process must not stack tees.
    d1, d2 = tmp_path / "r1", tmp_path / "r2"
    try:
        run_log.install_run_log(d1)
        print("first run only")
        run_log.install_run_log(d2)      # re-install WITHOUT restoring — must self-tear-down d1
        print("second run only")
    finally:
        run_log.restore_run_log()
    log1 = (d1 / "run.log").read_text()
    log2 = (d2 / "run.log").read_text()
    assert "first run only" in log1 and "second run only" not in log1
    assert "second run only" in log2 and "first run only" not in log2


def test_teardown_is_clobber_safe_when_stream_swapped(tmp_path):
    # If something downstream (e.g. a fresh pytest capsys) swaps sys.stdout AFTER install,
    # restore must NOT clobber it back to the stale original.
    orig = sys.stdout
    try:
        run_log.install_run_log(tmp_path)
        swapped = _Sink()
        sys.stdout = swapped            # simulate an external swap of the stream
        run_log.restore_run_log()       # must leave the swapped stream in place
        assert sys.stdout is swapped
    finally:
        sys.stdout = orig
        run_log.restore_run_log()


def test_restore_is_safe_to_call_twice(tmp_path):
    run_log.install_run_log(tmp_path)
    run_log.restore_run_log()
    run_log.restore_run_log()           # no exception on a second teardown


def test_open_failure_degrades_without_raising(tmp_path, capsys):
    # A path whose PARENT is a file (not a dir) makes mkdir/open fail → best-effort skip.
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    orig_out, orig_err = sys.stdout, sys.stderr
    ok = run_log.install_run_log(blocker / "sub")   # parent is a file → OSError
    assert ok is False
    assert sys.stdout is orig_out and sys.stderr is orig_err
    assert "could not open" in capsys.readouterr().err


class _Sink:
    def write(self, s):  # minimal writable stream stand-in
        return len(s)

    def flush(self):
        pass
