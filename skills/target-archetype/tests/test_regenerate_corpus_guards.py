"""Guards on regenerate_corpus.sh — the driver for the multi-hour corpus regen that must PRECEDE a re-freeze.

★ The defect class under test is a SILENT SUCCESS, not a crash. Before these guards, a regen pointed at an
  existing corpus dir skipped all 504 packages, printed `0 runs written, 0 failed`, and exited 0 — the only
  warning was gated on `fail > 0`, which a total skip never trips. Three independent routes to burning
  nothing while looking fine: a panel DERIVED from the frozen atlas (n=297) instead of describing the
  corpus (n=504), skip-if-exists over a populated dir, and a completion line that reported the loop's own
  counters instead of reconciling against the panel.

★ Every test runs the REAL script — with --dry-run, or with a stub run.py through the documented
  REGEN_RUN_PY seam — so the suite needs no S3, no Bedrock and no per-pair cost. `not (corpus/"logs")
  .exists()` is the load-bearing half of each refusal assertion: the log dir is created immediately before
  the first run.py invocation, so its absence proves the guard fired BEFORE any work, not after.
"""

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "regenerate_corpus.sh"

REFUSED = 1  # a pre-flight guard fired; nothing was run
USAGE = 2
INCOMPLETE = 3  # runs happened, but the corpus does not cover the panel

STUB_RUN_PY = """\
import argparse, json, pathlib, sys

ap = argparse.ArgumentParser()
ap.add_argument("--target"); ap.add_argument("--indication"); ap.add_argument("--out")
ap.add_argument("--emit")
for flag in ("--full-package", "--no-ground", "--no-risk", "--no-hypothesis"):
    ap.add_argument(flag, action="store_true")
a = ap.parse_args()

skip_file = pathlib.Path(__file__).with_name("skip.txt")
skip = set(skip_file.read_text().split()) if skip_file.exists() else set()
if f"{a.target}-{a.indication}" in skip:
    sys.exit(1)  # a pair that fails: the sweep must not die, and must not report success either

out = pathlib.Path(a.out)
out.mkdir(parents=True, exist_ok=True)
(out / "evidence_package.json").write_text(json.dumps({"target": a.target}))
"""


def _panel(path: Path, pairs, label: str = "?") -> Path:
    path.write_text("".join(f"{t}\t{i}\t{label}\n" for t, i in pairs))
    return path


def _package(corpus: Path, target: str, indication: str) -> None:
    d = corpus / f"{target}-{indication}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "evidence_package.json").write_text("{}")


def _stub(tmp_path: Path, failing=()) -> Path:
    stub = tmp_path / "stub_run.py"
    stub.write_text(STUB_RUN_PY)
    (tmp_path / "skip.txt").write_text("\n".join(failing))
    return stub


def _run(*args, env_extra=None):
    env = dict(os.environ)
    env.update(env_extra or {})
    return subprocess.run(
        ["bash", str(SCRIPT), *[str(a) for a in args]],
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )


THREE = [("EGFR", "LUAD"), ("KRAS", "PAAD"), ("MYC", "SCLC")]


def test_a_panel_that_does_not_describe_the_corpus_is_refused(tmp_path):
    """★ THE 297-OVER-504 CATCH, and the reason it is a refusal rather than a warning: a panel naming fewer
    pairs than the corpus holds does not fail — it succeeds over the WRONG membership, leaving the regen and
    the re-freeze with different ideas of what the corpus is. Nothing downstream can detect that."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for t, i in THREE:
        _package(corpus, t, i)
    panel = _panel(tmp_path / "panel_297.tsv", [("EGFR", "LUAD")])

    r = _run(corpus, "--panel", panel, "--dry-run")

    assert r.returncode == REFUSED, r.stdout + r.stderr
    assert "does not describe this corpus" in r.stderr, r.stderr
    assert "KRAS-PAAD" in r.stderr, "the refusal must NAME an uncovered package, not just count them"
    assert not (corpus / "logs").exists(), "refused before any run.py invocation"


def test_a_complete_corpus_is_refused_rather_than_silently_skipped(tmp_path):
    """★ The regression with teeth. This exact invocation used to print `0 runs written, 0 failed` and exit
    0, so a re-freeze could proceed on a corpus nobody had regenerated. The refusal must also say how to
    proceed, or the next operator's move is --no-verify-shaped."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for t, i in THREE:
        _package(corpus, t, i)
    panel = _panel(tmp_path / "panel.tsv", THREE)

    r = _run(corpus, "--panel", panel)

    assert r.returncode == REFUSED, r.stdout + r.stderr
    assert "0 runs written" in r.stderr, "the refusal must name the historical no-op it replaces"
    assert "--resume" in r.stderr and "FRESH" in r.stderr, f"must state the way forward: {r.stderr}"
    assert not (corpus / "logs").exists()


def test_a_partly_populated_corpus_is_refused_because_a_mixed_corpus_is_unusable(tmp_path):
    """★ Not the same defect as the complete case: here work WOULD happen, which is what makes it worse. The
    result is a corpus half at the old SHA and half at the new one — the freeze would succeed and the
    artefact carries no trace of the split."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _package(corpus, "EGFR", "LUAD")
    panel = _panel(tmp_path / "panel.tsv", THREE)

    r = _run(corpus, "--panel", panel)

    assert r.returncode == REFUSED, r.stdout + r.stderr
    assert "MIXED across two code versions" in r.stderr, r.stderr
    assert not (corpus / "logs").exists()


def test_resume_over_a_complete_corpus_is_a_clean_reconciled_no_op(tmp_path):
    """The green half: --resume is the declared way to say a skip is intended, and it still reports a COUNT
    rather than a bare `complete`."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for t, i in THREE:
        _package(corpus, t, i)
    panel = _panel(tmp_path / "panel.tsv", THREE)

    r = _run(corpus, "--panel", panel, "--resume")

    assert r.returncode == 0, r.stdout + r.stderr
    assert "3 of 3" in r.stdout, f"a completion claim must be a reconciled count: {r.stdout}"


def test_an_omitted_panel_is_refused_when_the_corpus_already_carries_one(tmp_path):
    """★ The ROOT of the derived-panel defect. Deriving membership from the frozen atlas answers a different
    question — what the LAST freeze covered — and the two answers diverged the moment the panel expanded
    297 -> 504. When the corpus can state its own membership, refusing to guess is the whole fix."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _panel(corpus / "panel_504.tsv", THREE)
    _package(corpus, "EGFR", "LUAD")

    r = _run(corpus, "--dry-run")

    assert r.returncode == REFUSED, r.stdout + r.stderr
    assert "no --panel given" in r.stderr, r.stderr
    assert "panel_504.tsv" in r.stderr, "the refusal must name the candidate it found"
    assert not (corpus / "logs").exists()


def test_a_two_column_panel_row_is_refused(tmp_path):
    """★ Pre-existing hazard, promoted from a comment to a guard: build_atlas._load_panel accepts ONLY
    len(parts) == 3, so a 2-column row or a header degrades every curated label to '?' while the build still
    SUCCEEDS. A hazard that only a comment protects is not protected."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    panel = tmp_path / "panel.tsv"
    panel.write_text("EGFR\tLUAD\t?\nKRAS\tPAAD\n")

    r = _run(corpus, "--panel", panel, "--dry-run")

    assert r.returncode == REFUSED, r.stdout + r.stderr
    assert "3 tab-separated columns" in r.stderr, r.stderr
    assert "meta.classes" in r.stderr, "the refusal must say what SILENTLY breaks, not just what is wrong"


def test_a_duplicate_panel_row_is_refused(tmp_path):
    """A duplicated pair double-books a ~2-minute slot and makes the reconciliation target unachievable."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    panel = _panel(tmp_path / "panel.tsv", [*THREE, ("EGFR", "LUAD")])

    r = _run(corpus, "--panel", panel, "--dry-run")

    assert r.returncode == REFUSED, r.stdout + r.stderr
    assert "duplicate" in r.stderr, r.stderr


def test_jobs_above_the_cap_is_refused_with_the_reason(tmp_path):
    """★ The cap is not a style preference: swap=0 with vm.overcommit_memory=1 means an overcommit is an
    OOM-kill or a hard reboot, never a clean MemoryError, and a 6-wide sweep has rebooted this host. A cap
    whose refusal does not say that gets raised by the next person in a hurry."""
    r = _run(tmp_path / "corpus", "--panel", tmp_path / "nope.tsv", "--jobs", 5, "--dry-run")

    assert r.returncode == REFUSED, r.stdout + r.stderr
    assert "cap of 4" in r.stderr, r.stderr
    assert "REBOOT" in r.stderr, f"the cap must carry its reason: {r.stderr}"


def test_a_non_integer_jobs_is_a_usage_error_not_a_refusal(tmp_path):
    """Distinct exit codes: a typo in an argument is not a guard firing about the corpus."""
    r = _run(tmp_path / "corpus", "--jobs", "four", "--dry-run")
    assert r.returncode == USAGE, r.stdout + r.stderr


def test_dry_run_on_a_virgin_dir_plans_every_pair(tmp_path):
    """The other green state: with nothing on disk the plan must cover the whole panel, and still touch
    nothing. If this went red the guards would be refusing the legitimate first run."""
    corpus = tmp_path / "corpus"
    panel = _panel(tmp_path / "panel_504.tsv", THREE)

    r = _run(corpus, "--panel", panel, "--dry-run")

    assert r.returncode == 0, r.stdout + r.stderr
    assert "would run 3 of 3" in r.stdout, r.stdout
    assert not (corpus / "logs").exists(), "--dry-run must not invoke run.py"


def test_a_finished_sweep_reports_a_reconciled_count(tmp_path):
    """The completion line is now a COUNT of packages on disk against the panel, which is robust to HOW the
    runs executed — serial or --jobs N — where the old `n runs written` counted loop iterations and so was
    blind to the parallel path the header itself recommended."""
    corpus = tmp_path / "corpus"
    panel = _panel(tmp_path / "panel.tsv", THREE)
    stub = _stub(tmp_path)

    r = _run(corpus, "--panel", panel, "--jobs", 2, env_extra={"REGEN_RUN_PY": str(stub)})

    assert r.returncode == 0, r.stdout + r.stderr
    assert "COMPLETE and reconciled" in r.stdout, r.stdout
    assert "3 of 3" in r.stdout, r.stdout
    for t, i in THREE:
        assert (corpus / f"{t}-{i}" / "evidence_package.json").exists()


def test_a_sweep_that_loses_pairs_exits_nonzero_and_names_them(tmp_path):
    """★★ THE CENTRAL TEST. A sweep where some pairs fail is the realistic outcome of a 5 h live-S3 job, and
    it is exactly the case the old driver reported as success: per-pair failures are deliberately swallowed
    so one bad pair cannot kill the sweep, which means the ONLY thing standing between a partial corpus and
    a freeze is this reconciliation. It must fail, and it must name what is missing — a count alone would
    send the operator back to a 504-line log."""
    corpus = tmp_path / "corpus"
    panel = _panel(tmp_path / "panel.tsv", THREE)
    stub = _stub(tmp_path, failing=["KRAS-PAAD"])

    r = _run(corpus, "--panel", panel, env_extra={"REGEN_RUN_PY": str(stub)})

    assert r.returncode == INCOMPLETE, r.stdout + r.stderr
    assert "INCOMPLETE" in r.stderr, r.stderr
    assert "2 of 3" in r.stderr, r.stderr
    assert "KRAS-PAAD" in r.stderr, "must name the missing pair, not just count it"
    assert "COMPLETE and reconciled" not in r.stdout, "a partial sweep must never print the success line"
    # ★ and the sweep did NOT abort on the failing pair — the other two still landed.
    assert (corpus / "MYC-SCLC" / "evidence_package.json").exists(), "one bad pair must not kill the sweep"


def test_help_prints_the_header_and_not_the_script_body():
    """★ Guarding a guard against ROT. The first usage() hardcoded `sed -n '2,70p'` and had ALREADY drifted
    past the header, printing `set -euo pipefail` as if it were documentation — a help text keyed to a line
    NUMBER breaks silently the next time the header grows. This pins the BOUNDARY instead of the range."""
    r = _run("--help")

    assert r.returncode == 0, r.stdout + r.stderr
    assert "EXIT CODES" in r.stdout, r.stdout
    assert "set -euo pipefail" not in r.stdout, "usage() leaked the script body into the help text"
    assert "--run-one re-entry" not in r.stdout, "usage() leaked an internal implementation comment"
