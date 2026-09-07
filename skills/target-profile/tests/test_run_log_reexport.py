"""run.log re-export smoke (2026-08-24).

The tee itself lives in _skills_common.run_log (thoroughly tested there and shared with the
focused skills' dispatcher). target-profile re-exports it under the private names its main()
and downstream consumers use; this guards that the re-export is wired and produces run.log.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parents[1], "tp_run_log")


def test_reexports_shared_run_log():
    from _skills_common.run_log import install_run_log, restore_run_log

    assert tp._install_run_log is install_run_log
    assert tp._restore_run_log is restore_run_log


def test_writes_run_log_end_to_end(tmp_path, capsys):
    try:
        tp._install_run_log(tmp_path, header={"skill": "target-profile"})
        print("[target-profile] fanning out")
    finally:
        tp._restore_run_log()
    log = (tmp_path / "run.log").read_text()
    assert "# skill: target-profile" in log
    assert "fanning out" in log
    assert "fanning out" in capsys.readouterr().out  # live output preserved
