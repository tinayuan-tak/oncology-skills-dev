"""run.log — stdout+stderr tee for development + provenance (2026-08-24).

The full run already narrates its backend to stderr via `[target-profile] …` prints, but
that output is transient. `_install_run_log` tees stdout+stderr to `<out>/run.log` with
per-line UTC timestamps so the narration becomes a durable, greppable audit trail that
travels with the artifact tree. These are offline guards on the tee mechanics — no Bedrock,
no S3, no main() invocation.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_run_log", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


tp = _load()


def test_tee_captures_stdout_and_stderr_with_stamps(tmp_path):
    orig_out, orig_err = sys.stdout, sys.stderr
    try:
        tp._install_run_log(tmp_path)
        print("hello from stdout")
        print("[target-profile] a warning", file=sys.stderr)
    finally:
        tp._restore_run_log()

    # Streams are restored to exactly what they were before install.
    assert sys.stdout is orig_out
    assert sys.stderr is orig_err

    log = (tmp_path / "run.log").read_text()
    # Header carries the audit context.
    assert "# target-profile run log" in log
    assert "# started_at:" in log and "# argv:" in log
    # Both streams captured, tagged, and each line carries an ISO-8601 UTC stamp.
    out_lines = [ln for ln in log.splitlines() if " OUT " in ln and "hello from stdout" in ln]
    err_lines = [ln for ln in log.splitlines() if " ERR " in ln and "a warning" in ln]
    assert out_lines and err_lines
    assert out_lines[0].startswith("20") and out_lines[0][10] == "T"  # 2026-…T…Z stamp prefix


def test_live_stream_is_preserved(tmp_path, capsys):
    # The tee must still write to the REAL stream — capsys sees the live output.
    try:
        tp._install_run_log(tmp_path)
        print("still live")
    finally:
        tp._restore_run_log()
    assert "still live" in capsys.readouterr().out


def test_install_is_idempotent_no_tee_stacking(tmp_path):
    # A harness that calls main() twice in one process must not stack tees: the second
    # install tears down the first, so writes never fan out into a stale prior log.
    d1, d2 = tmp_path / "run1", tmp_path / "run2"
    d1.mkdir(); d2.mkdir()
    try:
        tp._install_run_log(d1)
        print("first run only")
        tp._install_run_log(d2)          # re-install WITHOUT restoring — must self-tear-down
        print("second run only")
    finally:
        tp._restore_run_log()

    log1 = (d1 / "run.log").read_text()
    log2 = (d2 / "run.log").read_text()
    assert "first run only" in log1 and "second run only" not in log1
    assert "second run only" in log2 and "first run only" not in log2


def test_restore_is_safe_to_call_twice(tmp_path):
    tp._install_run_log(tmp_path)
    tp._restore_run_log()
    tp._restore_run_log()  # no exception on a second teardown


def test_open_failure_degrades_without_raising(tmp_path, capsys):
    # If run.log can't be opened, the run continues with streams untouched.
    orig_out, orig_err = sys.stdout, sys.stderr
    missing = tmp_path / "does-not-exist"  # parent absent → open() raises OSError
    tp._install_run_log(missing)
    assert sys.stdout is orig_out and sys.stderr is orig_err
    assert "could not open run.log" in capsys.readouterr().err
