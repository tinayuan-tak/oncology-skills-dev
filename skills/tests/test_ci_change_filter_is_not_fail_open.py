"""Guard against the size-dependent CI change-filter fail-open (skills#2258).

The `changes` job in `.github/workflows/skills-validate.yml` decides whether the
`methods-pytest` / `contracts-pytest` / `contracts-static` legs run. It used to test each
prefix with `echo "$changed" | grep -qE '^methods/'` under `set -o pipefail`. `grep -q` exits
at the first match, the writer (`echo`) then takes SIGPIPE, and `pipefail` promotes that to the
pipeline's status (141), so the `if` reads FALSE and the leg is SKIPPED -- while the `pytest`
fan-in reads that skip as *expected* and posts green. It is invisible while the changed-file
list fits the 64 KiB pipe buffer, and fires on exactly the large refactors that most need the
heavy legs (measured on PR #2257: 1215 paths / 75564 bytes -> all three legs skipped).

These tests execute the workflow's *actual* `run:` script (not a paraphrase of it) against
synthetic changed-file lists, so they track the real CI behaviour. None can pass vacuously:
- `test_large_matching_input_runs_all_legs` -- the behavioural teeth.
- `test_discrimination_docs_only / skills_only` -- stops "just hardcode true" from passing.
- `test_mutation_control_piped_form_is_wrong` -- reintroduces the piped form and REQUIRES the
  wrong answer, so the fixture cannot silently drift under the pipe-buffer threshold and pass
  for free.
- `test_no_workflow_pipes_into_grep_q_under_pipefail` -- static ratchet across all workflows.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _REPO_ROOT / ".github/workflows/skills-validate.yml"
_WORKFLOW_DIR = _REPO_ROOT / ".github/workflows"


def _changes_filter_run_script() -> str:
    """Return the raw `run:` script of the `Compute changed-package filters` step."""
    doc = yaml.safe_load(_WORKFLOW.read_text())
    steps = doc["jobs"]["changes"]["steps"]
    matches = [s for s in steps if "changed-package filters" in (s.get("name") or "")]
    assert len(matches) == 1, f"expected exactly one filter step, found {len(matches)}"
    run = matches[0]["run"]
    assert "grep" in run and "GITHUB_OUTPUT" in run, "step shape changed; re-inspect the harness"
    return run


def _prepare(run_script: str, fixture: Path, *, piped_mutation: bool = False) -> str:
    """Turn the CI `run:` script into a locally executable one.

    Substitutes ONLY the two data-source lines (git fetch / the `git diff` that fills `changed`)
    and the `${{ }}` expressions -- everything else, including the prefix-matching logic under
    test, runs verbatim. Every substitution is assert-and-replace: an unmatched pattern is a hard
    error, never a silent no-op that would let the test drift away from the real script.
    """
    s = run_script
    s, n = re.subn(r"\$\{\{\s*github\.event_name\s*\}\}", "pull_request", s)
    assert n >= 1, "github.event_name expression not found"
    s, n = re.subn(r"\$\{\{\s*github\.event\.pull_request\.base\.ref\s*\}\}", "main", s)
    assert n == 1, f"base.ref expression matched {n} times, expected 1"
    s, n = re.subn(r'git fetch -q origin "\$base"', ":", s)
    assert n == 1, f"git fetch line matched {n} times, expected 1"
    s, n = re.subn(
        r"changed=\$\(git diff[^\n]*\)",
        f"changed=$(cat {shlex.quote(str(fixture))})",
        s,
    )
    assert n == 1, f"changed= assignment matched {n} times, expected 1"
    if piped_mutation:
        # Reintroduce the exact bug this guard exists to prevent: pipe into `grep -q` under
        # pipefail. With the match on line 1 of a >pipe-buffer fixture the SIGPIPE is deterministic.
        for pref in ("contracts", "methods", "skills"):
            s, n = re.subn(
                rf"grep -qE '\^{pref}/'\s+\"\$changed_list\"",
                f"echo \"$changed\" | grep -qE '^{pref}/'",
                s,
            )
            assert n == 1, f"could not reintroduce piped form for {pref} (matched {n})"
    return s


def _run(script: str, tmp_path: Path) -> dict[str, str]:
    gho = tmp_path / "github_output"
    gho.touch()
    env = {"GITHUB_OUTPUT": str(gho), "PATH": "/usr/bin:/bin"}
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, timeout=60)
    assert proc.returncode == 0, f"script exited {proc.returncode}\nSTDERR:\n{proc.stderr}"
    out: dict[str, str] = {}
    for line in gho.read_text().splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def _fixture(tmp_path: Path, name: str, head: list[str], pad_prefix: str, min_bytes: int) -> Path:
    """Write a changed-file list starting with `head`, padded past `min_bytes` with non-matching
    `pad_prefix` lines (so the interesting match sits at the top, before the pipe-buffer fills)."""
    lines = list(head)
    i = 0
    while len("\n".join(lines)) < min_bytes:
        lines.append(f"{pad_prefix}/deeply/nested/padding/path/file_{i}.txt")
        i += 1
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n")
    return p


def test_large_matching_input_runs_all_legs(tmp_path: Path) -> None:
    """>64 KiB list matching contracts/ and methods/ at the top -> all three legs run."""
    fx = _fixture(
        tmp_path,
        "big.txt",
        head=["contracts/cards/x.card.yaml", "methods/methods/foo/read.py", "README.md"],
        pad_prefix="docs",
        min_bytes=80_000,
    )
    assert fx.stat().st_size > 65_536
    out = _run(_prepare(_changes_filter_run_script(), fx), tmp_path)
    assert out.get("methods") == "true", out
    assert out.get("contracts") == "true", out
    assert out.get("contracts_jobs") == "true", out


def test_discrimination_docs_only(tmp_path: Path) -> None:
    """A large docs-only list -> every leg false. Defeats a 'hardcode true' fix."""
    fx = _fixture(tmp_path, "docs.txt", head=["README.md"], pad_prefix="docs", min_bytes=80_000)
    out = _run(_prepare(_changes_filter_run_script(), fx), tmp_path)
    assert out.get("methods") == "false", out
    assert out.get("contracts") == "false", out
    assert out.get("contracts_jobs") == "false", out


def test_discrimination_skills_only(tmp_path: Path) -> None:
    """skills-only -> methods/contracts false but contracts_jobs true (methods || skills)."""
    fx = _fixture(tmp_path, "skills.txt", head=["skills/foo/run.py"], pad_prefix="docs", min_bytes=80_000)
    out = _run(_prepare(_changes_filter_run_script(), fx), tmp_path)
    assert out.get("methods") == "false", out
    assert out.get("contracts") == "false", out
    assert out.get("contracts_jobs") == "true", out


def test_mutation_control_piped_form_is_wrong(tmp_path: Path) -> None:
    """Anti-vacuity: restore `echo | grep -q`, feed a >=256 KiB list matching on line 1, and
    require the WRONG answer. If this ever passes (legs come out true), the pipe-buffer SIGPIPE
    stopped firing and the behavioural tests above are no longer proving anything."""
    fx = _fixture(
        tmp_path,
        "mut.txt",
        head=["contracts/first.yaml", "methods/first.py"],
        pad_prefix="docs",
        min_bytes=262_144,
    )
    assert fx.stat().st_size > 256 * 1024
    script = _prepare(_changes_filter_run_script(), fx, piped_mutation=True)
    out = _run(script, tmp_path)
    # The bug: SIGPIPE -> pipeline rc 141 -> if false -> legs wrongly skipped.
    assert out.get("methods") == "false", f"expected the piped form to fail-open, got {out}"
    assert out.get("contracts") == "false", f"expected the piped form to fail-open, got {out}"


def test_no_workflow_pipes_into_grep_q_under_pipefail() -> None:
    """Static ratchet: no `run:` block in any workflow may pipe into `grep -q` while pipefail is
    set -- the shape that caused this bug."""
    offenders: list[str] = []
    for wf in sorted(_WORKFLOW_DIR.glob("*.yml")):
        doc = yaml.safe_load(wf.read_text())
        if not isinstance(doc, dict):
            continue
        for job_name, job in (doc.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                run = step.get("run")
                if not isinstance(run, str):
                    continue
                if "pipefail" not in run:
                    continue
                for lineno, line in enumerate(run.splitlines(), 1):
                    if line.lstrip().startswith("#"):  # a comment mentioning the shape is fine
                        continue
                    if re.search(r"\|\s*grep\s+-[a-zA-Z]*q", line):
                        offenders.append(f"{wf.name}::{job_name} line {lineno}: {line.strip()}")
    assert not offenders, "pipe-into-`grep -q` under pipefail (skills#2258):\n" + "\n".join(offenders)
