"""The dge-deseq2 CLI must propagate run_pipeline.R's exit status.

Click DISCARDS a command callback's return value in standalone mode — it calls ctx.exit() with no
argument — so the former `return result.returncode` exited 0 even when the R pipeline failed. Callers
(framework runs, CI, `&&` chains) then read SUCCESS from a run that wrote no result.parquet, and the
R stderr was thrown away: the only surviving symptom was a FileNotFoundError on the missing parquet
downstream. That also made the byte-identity test's own `assert new_result.returncode == 0` VACUOUS.

Both directions are pinned here — a nonzero child status must reach the caller, and a successful run
must still exit 0 — because a fix that simply always exited nonzero would satisfy the first alone.
The R pipeline itself is stubbed, so these are hermetic (no Rscript, no S3).
"""

from __future__ import annotations

import subprocess

import pytest
from click.testing import CliRunner

from onc_methods.dge_deseq2 import cli as cli_mod


@pytest.fixture
def stub_pipeline(monkeypatch, tmp_path):
    """Stub everything main() touches before the subprocess, and record the invocation.

    Returns a factory: call it with the exit code the fake Rscript should report.
    """

    def _install(returncode: int) -> dict:
        seen: dict = {"calls": []}

        monkeypatch.setattr(cli_mod, "resolve_config", lambda *a, **kw: tmp_path / "COADREAD.yaml")
        monkeypatch.setattr(cli_mod, "compute_git_sha", lambda *a, **kw: "0" * 40)

        def fake_run(cmd, *args, **kwargs):
            seen["calls"].append(cmd)
            return subprocess.CompletedProcess(cmd, returncode)

        monkeypatch.setattr(cli_mod.subprocess, "run", fake_run)
        return seen

    return _install


def _invoke(tmp_path):
    return CliRunner().invoke(
        cli_mod.main,
        [
            "--indication",
            "COADREAD",
            "--contrast",
            "tumor_vs_adjacent",
            "--release-pin",
            "2026-Q2",
            "--out",
            str(tmp_path / "out"),
        ],
    )


def test_nonzero_pipeline_status_reaches_the_caller(stub_pipeline, tmp_path):
    """A failed R pipeline must NOT look like success. Fails on the pre-fix CLI (exit_code == 0)."""
    seen = stub_pipeline(3)
    result = _invoke(tmp_path)
    # Liveness: the stub must actually have been reached, otherwise an early return would make the
    # exit-code assertion below pass for the wrong reason.
    assert seen["calls"], "the R pipeline was never invoked — the exit-code assertion would be vacuous"
    assert result.exit_code == 3, f"expected the child's status 3 to propagate, got {result.exit_code}"


def test_successful_pipeline_still_exits_zero(stub_pipeline, tmp_path):
    """The other direction: propagating a status must not turn a clean run into a failure."""
    seen = stub_pipeline(0)
    result = _invoke(tmp_path)
    assert seen["calls"], "the R pipeline was never invoked"
    assert result.exit_code == 0, f"a clean pipeline must exit 0, got {result.exit_code}: {result.output}"


def test_dry_run_exits_zero_without_invoking_the_pipeline(stub_pipeline, tmp_path):
    """--dry-run returns before the subprocess; it must stay a clean exit."""
    seen = stub_pipeline(3)  # would be a failure IF it ran
    result = CliRunner().invoke(
        cli_mod.main,
        [
            "--indication",
            "COADREAD",
            "--contrast",
            "tumor_vs_adjacent",
            "--release-pin",
            "2026-Q2",
            "--out",
            str(tmp_path / "out"),
            "--dry-run",
        ],
    )
    assert not seen["calls"], "--dry-run must not invoke the R pipeline"
    assert result.exit_code == 0
