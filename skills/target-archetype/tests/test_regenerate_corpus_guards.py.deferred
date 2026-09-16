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

import json
import os
import subprocess
import threading
import time
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


def _run(*args, env_extra=None, mem_guard=False):
    """Run the real script. THE MEMORY GUARD IS OFF BY DEFAULT, and that is a correctness requirement.

    ★ A test whose verdict depends on the RUNNER's MemAvailable is flaky by construction. The guard's
      default soft floor is 35 G — calibrated for the ~124 G host this driver drives — so on a CI runner or
      a loaded workstation the already-below-floor refusal would fire and red tests that have nothing to do
      with memory. Worse, it would red them with exit 1, the same code the panel guards use, so the suite
      would look like a guard regression. The guard's own behaviour is covered by the tests below, which
      drive the floors to values that need no real memory pressure to reach.
    """
    argv = [str(a) for a in args]
    if not mem_guard:
        argv.append("--no-mem-guard")
    env = dict(os.environ)
    env.update(env_extra or {})
    return subprocess.run(
        ["bash", str(SCRIPT), *argv],
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


# ═══ THE MEMORY GUARD ════════════════════════════════════════════════════════════════════════════════════
# ★ Why these tests exist at all, and why they are worth their complexity: the guard's two floors are
#   otherwise reachable only by actually exhausting a 124 G box. Untestable safety code is unshipped safety
#   code — and this driver has NO shell linting in CI, so this file is the only gate it has. The two seams
#   (REGEN_MEMINFO, REGEN_MEM_MIN_KILL_KB) exist for exactly that reason and for nothing else: neither is
#   referenced on the real invocation path.
#
# ★★ THE FIRST VERSION OF THE DRAIN WAS INERT, AND ONLY A DETERMINISTIC TEST FOUND IT. It fed a gated stream
#   into `xargs -P N -n 2` on the premise that xargs pulls from stdin as slots free. xargs actually does one
#   buffered read() and batches out of its own buffer, so all 504 gate checks ran in the first milliseconds,
#   before any worker had allocated anything. The guard could not fire. `test_the_drain_gate_is_evaluated...`
#   below is the regression test for that: it is the only test here that would pass a broken gate as green if
#   it were written in terms of the final state instead of the drain COUNT.


def _meminfo(path: Path, avail_g: int, total_g: int = 124) -> Path:
    """A /proc/meminfo-shaped file the guard can be pointed at. Only the two lines it reads are needed."""
    path.write_text(f"MemTotal:       {total_g * 1048576} kB\nMemAvailable:   {avail_g * 1048576} kB\n")
    return path


# A stub that makes pressure ARRIVE, on its first invocation only, and leaves it there.
# ★ It must NOT lift the pressure itself: the drain is gated between pairs, so a stub that restored
#   MemAvailable before exiting would have the relief in place before the gate ever looked. That mistake made
#   the first draft of the drain test pass against a guard that never drained.
STUB_PRESSURE_RUN_PY = """\
import argparse, json, os, pathlib

ap = argparse.ArgumentParser()
ap.add_argument("--target"); ap.add_argument("--indication"); ap.add_argument("--out")
ap.add_argument("--emit")
for flag in ("--full-package", "--no-ground", "--no-risk", "--no-hypothesis"):
    ap.add_argument(flag, action="store_true")
a = ap.parse_args()

mi = pathlib.Path(os.environ["REGEN_MEMINFO"])
seen = pathlib.Path(str(mi) + ".invocations")
n = int(seen.read_text()) if seen.exists() else 0
seen.write_text(str(n + 1))
if n == 0:
    avail = int(os.environ["STUB_PRESSURE_G"]) * 1048576
    mi.write_text("MemTotal:       130023424 kB\\nMemAvailable:   %d kB\\n" % avail)

out = pathlib.Path(a.out)
out.mkdir(parents=True, exist_ok=True)
(out / "evidence_package.json").write_text(json.dumps({"target": a.target}))
"""

# A stub that is BIG and STAYS ALIVE, so the watchdog has a real sacrifice target to pick out of a ppid walk.
STUB_FAT_RUN_PY = """\
import argparse, json, os, pathlib, time

ap = argparse.ArgumentParser()
ap.add_argument("--target"); ap.add_argument("--indication"); ap.add_argument("--out")
ap.add_argument("--emit")
for flag in ("--full-package", "--no-ground", "--no-risk", "--no-hypothesis"):
    ap.add_argument(flag, action="store_true")
a = ap.parse_args()

mb = int(os.environ.get("STUB_FAT_MB", "200"))
blob = bytearray(mb * 1024 * 1024)
blob[::4096] = b"\\x01" * (len(blob) // 4096)     # touch every page so this is RESIDENT, not just mapped
mi = pathlib.Path(os.environ["REGEN_MEMINFO"])
mi.write_text("MemTotal:       130023424 kB\\nMemAvailable:   %d kB\\n"
              % (int(os.environ["STUB_PRESSURE_G"]) * 1048576))
time.sleep(30)                                   # still in flight when the watchdog next samples

out = pathlib.Path(a.out)
out.mkdir(parents=True, exist_ok=True)
(out / "evidence_package.json").write_text(json.dumps({"target": a.target}))
"""

# A stub that leaves a package which EXISTS and does not PARSE — the shape a truncate-then-write leaves
# behind when it dies mid-flush. STUB_RC picks which mechanism should catch it: nonzero exits go to the
# --run-one purge, zero exits go to the reconciliation.
STUB_TRUNCATING_RUN_PY = """\
import argparse, os, pathlib, sys

ap = argparse.ArgumentParser()
ap.add_argument("--target"); ap.add_argument("--indication"); ap.add_argument("--out")
ap.add_argument("--emit")
for flag in ("--full-package", "--no-ground", "--no-risk", "--no-hypothesis"):
    ap.add_argument(flag, action="store_true")
a = ap.parse_args()

out = pathlib.Path(a.out)
out.mkdir(parents=True, exist_ok=True)
pkg = out / "evidence_package.json"
if f"{a.target}-{a.indication}" in os.environ.get("STUB_TRUNCATE", "").split():
    pkg.write_text('{"target": "%s", "claim_vectors": [{"id": 1' % a.target)
    sys.exit(int(os.environ.get("STUB_RC", "1")))
pkg.write_text('{"target": "%s"}' % a.target)
"""


def _stub_src(tmp_path: Path, src: str, name: str = "stub_run.py") -> Path:
    stub = tmp_path / name
    stub.write_text(src)
    return stub


def _lift_pressure_once_drained(corpus: Path, meminfo: Path, avail_g: int, deadline: float = 90.0):
    """Relieve the simulated pressure the moment the driver RECORDS a drain, in a side thread.

    ★ CAUSAL, NOT A TIMER, and that is the whole point. A `threading.Timer(3, ...)` would race the stub's own
      write on a loaded box — this host runs peer sessions and a live regen — and the failure would be a
      GREEN test (no drain observed, nothing asserted about it) rather than a red one. Keying the relief off
      the guard's own `DRAIN #1` line means the ordering the test depends on is enforced, not hoped for.
    """
    log = corpus / "logs" / "memory-guard.log"

    def wait_then_lift():
        end = time.time() + deadline
        while time.time() < end:
            try:
                if "DRAIN #1" in log.read_text():
                    _meminfo(meminfo, avail_g)
                    return
            except OSError:
                pass
            time.sleep(0.05)

    t = threading.Thread(target=wait_then_lift, daemon=True)
    t.start()
    return t


def _floors(floor, hard, poll=1, drain_timeout=60):
    """The four memory flags as argv, so each test's intent — which floors, how fast, how patient — reads on
    one line instead of twelve. Every guard test drives the floors explicitly: a default-floor test would be
    a test of the runner's MemAvailable."""
    flags = {"--mem-floor": floor, "--mem-hard": hard, "--mem-poll": poll, "--mem-drain-timeout": drain_timeout}
    return [str(x) for flag, value in flags.items() for x in (flag, value)]


def test_the_drain_gate_is_evaluated_when_a_slot_frees_not_when_the_feed_is_read(tmp_path):
    """★★ THE REGRESSION TEST FOR AN INERT GUARD. Pressure arrives while pair 1 is in flight and persists
    after it retires, so the drain can only be seen by a gate that samples MemAvailable at the slot handover.
    The first implementation gated a feed piped into `xargs -P`, which reads ahead into its own buffer — so
    every check ran before any worker existed and the drain count was 0 while the corpus still came out
    COMPLETE. That is why this asserts on the DRAIN COUNT and the RESUME, not on the final corpus: a
    fully-correct final state is exactly what the broken version produced."""
    corpus = tmp_path / "corpus"
    panel = _panel(tmp_path / "panel.tsv", THREE)
    stub = _stub_src(tmp_path, STUB_PRESSURE_RUN_PY)
    meminfo = _meminfo(tmp_path / "meminfo", avail_g=100)
    _lift_pressure_once_drained(corpus, meminfo, avail_g=100)

    env = {"REGEN_RUN_PY": str(stub), "REGEN_MEMINFO": str(meminfo), "STUB_PRESSURE_G": "20"}
    args = [corpus, "--panel", panel, "--jobs", 1, *_floors(floor=40, hard=5)]
    r = _run(*args, mem_guard=True, env_extra=env)

    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 drain(s)" in r.stdout, f"the gate never saw the pressure -- it is inert: {r.stdout}"
    assert "DRAIN: MemAvailable 20G below floor 40G" in r.stderr, r.stderr
    assert "RESUME" in r.stderr, f"a drain that never lifts is a stall, not a drain: {r.stderr}"
    # ★ and the drain cost WALL CLOCK, not a pair: draining is the cheap tier.
    assert "3 of 3" in r.stdout, r.stdout
    log = (corpus / "logs" / "memory-guard.log").read_text()
    assert "DRAIN #1" in log and "drain #1 lifted" in log, log


def test_a_drain_that_never_lifts_ends_incomplete_rather_than_hanging(tmp_path):
    """★ The timeout lands on the recovery loop this driver ALREADY has (exit 3 + --resume) instead of
    inventing a second one, and it is TERMINAL: it stops the dispatch loop outright. Per-pair timeouts would
    make a stuck box cost 900 s x 490 remaining pairs — a 40-hour "guard"."""
    corpus = tmp_path / "corpus"
    panel = _panel(tmp_path / "panel.tsv", THREE)
    stub = _stub_src(tmp_path, STUB_PRESSURE_RUN_PY)
    meminfo = _meminfo(tmp_path / "meminfo", avail_g=100)

    env = {"REGEN_RUN_PY": str(stub), "REGEN_MEMINFO": str(meminfo), "STUB_PRESSURE_G": "20"}
    args = [corpus, "--panel", panel, "--jobs", 1, *_floors(floor=40, hard=5, drain_timeout=2)]
    r = _run(*args, mem_guard=True, env_extra=env)

    assert r.returncode == INCOMPLETE, r.stdout + r.stderr
    assert "DRAIN TIMEOUT" in r.stderr, r.stderr
    assert "--resume" in r.stderr, "the timeout must name its recovery, or it reads as a dead end"
    assert "1 of 3" in r.stderr, r.stderr
    assert "MISSING (2)" in r.stderr and "KRAS-PAAD" in r.stderr, "must name the pairs it never launched"
    assert "COMPLETE and reconciled" not in r.stdout


def test_the_hard_floor_sacrifices_the_largest_worker_and_the_pair_reconciles_as_missing(tmp_path):
    """★★ THE SACRIFICE IS ONLY SAFE BECAUSE A FAILED PAIR NOW LEAVES NO PACKAGE BEHIND. SIGKILL mid-write on
    a truncate-then-write producer is precisely how you get a file that EXISTS and does not PARSE, and the
    reconciliation used to key on presence — so this guard would have traded a host reboot for a silently
    corrupt corpus, which is worse: a reboot is loud. Assert the pair is NOT counted, both ways."""
    corpus = tmp_path / "corpus"
    panel = _panel(tmp_path / "panel.tsv", THREE)
    stub = _stub_src(tmp_path, STUB_FAT_RUN_PY)
    meminfo = _meminfo(tmp_path / "meminfo", avail_g=100)

    env = {
        "REGEN_RUN_PY": str(stub),
        "REGEN_MEMINFO": str(meminfo),
        "STUB_PRESSURE_G": "3",
        "STUB_FAT_MB": "200",
        # ★ The real threshold is 1 GiB, to stop the watchdog killing bookkeeping (a bash re-entry, its
        #   own awk) and spending a pair's slot while freeing nothing. Lowered to 50 MiB so a cheap stub
        #   can stand in for a 24 G worker — and still ABOVE the bookkeeping, so that invariant is under
        #   test rather than switched off.
        "REGEN_MEM_MIN_KILL_KB": str(50 * 1024),
    }
    args = [corpus, "--panel", panel, "--jobs", 1, *_floors(floor=40, hard=5, drain_timeout=2)]
    r = _run(*args, mem_guard=True, env_extra=env)

    assert r.returncode == INCOMPLETE, r.stdout + r.stderr
    assert "SACRIFICE: MemAvailable 3G below hard floor 5G" in r.stderr, r.stderr
    assert "1 sacrifice(s)" in r.stdout, r.stdout
    log = (corpus / "logs" / "memory-guard.log").read_text()
    assert "SACRIFICING pid" in log, log
    assert "MiB RSS" in log, "the log must state what was freed; integer GiB printed a 200 MiB target as 0G"
    assert "out=" in log, "the sacrifice must name the pair it cost, not just a pid"
    # ★ The sacrificed pair is MISSING, never merely present-and-broken.
    assert not (corpus / "EGFR-LUAD" / "evidence_package.json").exists()
    assert "0 unparseable" in r.stderr, f"a sacrifice must not leave a half-written package: {r.stderr}"
    assert "EGFR-LUAD" in r.stderr, "reconciliation must name the sacrificed pair so --resume refills it"


def test_a_complete_sweep_exits_zero_with_the_guard_ON(tmp_path):
    """★★ REGRESSION: a fully reconciled sweep used to exit 1 with the guard on. `set -e` applies inside an
    EXIT trap, the explicit reap had already collected the watchdog, so the trap's `kill` failed with "no
    such process" and the trap died with status 1. Exit 1 is the REFUSAL code — a perfect 5 h regen would
    have reported itself as a pre-flight guard firing, and the operator's next move would have been to hunt a
    guard bug instead of freezing. The guard being ON must be invisible when nothing is wrong."""
    corpus = tmp_path / "corpus"
    panel = _panel(tmp_path / "panel.tsv", THREE)
    stub = _stub(tmp_path)
    meminfo = _meminfo(tmp_path / "meminfo", avail_g=100)

    env = {"REGEN_RUN_PY": str(stub), "REGEN_MEMINFO": str(meminfo)}
    r = _run(corpus, "--panel", panel, "--jobs", 2, "--mem-poll", 1, mem_guard=True, env_extra=env)

    assert r.returncode == 0, f"a complete sweep must exit 0 with the guard on: {r.stdout + r.stderr}"
    assert "0 drain(s), 0 sacrifice(s)" in r.stdout, r.stdout
    assert "3 of 3" in r.stdout, r.stdout


def test_a_floor_already_breached_is_refused_before_any_work(tmp_path):
    """★ Otherwise the guard produces the very outcome this driver exists to prevent: the gate blocks on pair
    1, the sweep drains for --mem-drain-timeout, and it ends INCOMPLETE having run NOTHING — a confident
    no-op wearing the costume of protection. Same family as the skip-all refusal, so it is caught the same
    way: before any work, which `not (corpus/"logs").exists()` is what proves."""
    corpus = tmp_path / "corpus"
    panel = _panel(tmp_path / "panel.tsv", THREE)
    meminfo = _meminfo(tmp_path / "meminfo", avail_g=10)

    r = _run(corpus, "--panel", panel, mem_guard=True, env_extra={"REGEN_MEMINFO": str(meminfo)})

    assert r.returncode == REFUSED, r.stdout + r.stderr
    assert "already below --mem-floor" in r.stderr, r.stderr
    assert "--no-mem-guard" in r.stderr, "the refusal must state the deliberate override"
    assert not (corpus / "logs").exists(), "refused before any run.py invocation"


def test_the_guard_auto_disables_loudly_on_a_box_too_small_for_its_default_floor(tmp_path):
    """★★ A DEFAULT CALIBRATED FOR ONE HOST IS A BLANKET REFUSAL EVERYWHERE ELSE. The 35 G floor is measured
    off this ~124 G box; on a CI runner it would refuse every run with exit 1 — the same code the panel
    guards use — so the whole suite would read as a guard regression. Auto-disable is the fix, and it is
    LOUD: a safety guard that switches itself off quietly is the fail-open shape this driver exists to
    eliminate."""
    corpus = tmp_path / "corpus"
    panel = _panel(tmp_path / "panel.tsv", THREE)
    stub = _stub(tmp_path)
    meminfo = _meminfo(tmp_path / "meminfo", avail_g=20, total_g=40)  # 40 < floor 35 + p90 pair 24

    env = {"REGEN_RUN_PY": str(stub), "REGEN_MEMINFO": str(meminfo)}
    r = _run(corpus, "--panel", panel, mem_guard=True, env_extra=env)

    assert r.returncode == 0, r.stdout + r.stderr
    assert "MEMORY GUARD AUTO-DISABLED" in r.stderr, r.stderr
    assert "3 of 3" in r.stdout, "auto-disabling must let the work through, not refuse it"


def test_an_explicit_mem_floor_is_honoured_on_a_small_box_and_never_auto_disabled(tmp_path):
    """The other half of the rule above, and the half that makes it safe: auto-disable applies ONLY to the
    default. If it overrode an explicit --mem-floor, an operator on a small box could not opt into a floor
    that suits it, and the guard would be unreachable exactly where memory is tightest."""
    corpus = tmp_path / "corpus"
    panel = _panel(tmp_path / "panel.tsv", THREE)
    stub = _stub(tmp_path)
    meminfo = _meminfo(tmp_path / "meminfo", avail_g=20, total_g=40)

    env = {"REGEN_RUN_PY": str(stub), "REGEN_MEMINFO": str(meminfo)}
    args = [corpus, "--panel", panel, *_floors(floor=10, hard=4)]
    r = _run(*args, mem_guard=True, env_extra=env)

    assert r.returncode == 0, r.stdout + r.stderr
    assert "AUTO-DISABLED" not in r.stderr, f"an explicit --mem-floor must always be honoured: {r.stderr}"
    assert "memory guard ON: drain below 10G, sacrifice below 4G" in r.stdout, r.stdout


def test_a_hard_floor_at_or_above_the_soft_floor_is_a_usage_error(tmp_path):
    """★ Inverted floors would sacrifice pairs the guard never tried to SAVE — it would kill a worker at a
    pressure level where draining had not yet been attempted. That is a mis-ordering of the two tiers, not a
    tuning choice, so it is exit 2 rather than a clamp: silently reordering them would hide the operator's
    misunderstanding of what the two floors are for."""
    args = [tmp_path / "corpus", "--panel", tmp_path / "nope.tsv", *_floors(floor=20, hard=20)]
    r = _run(*args, mem_guard=True)

    assert r.returncode == USAGE, r.stdout + r.stderr
    assert "must be BELOW --mem-floor" in r.stderr, r.stderr
    # ★ Pin a fragment that cannot straddle the message's line wrap: the first version of this assertion
    #   asserted "...never tried to save" and red-failed on a message that says exactly that, because the
    #   wrap falls between "to" and "save". An assertion that breaks on reflowing prose tests the formatter.
    assert "sacrifice pairs it never tried to" in r.stderr, "the error must carry its reason"


def test_an_unreadable_meminfo_is_refused_rather_than_silently_unguarded(tmp_path):
    """★ A guard whose input is missing must REFUSE, not proceed. Reading an absent MemAvailable as "plenty"
    is the fail-open default that makes a safety feature worse than none: the operator believes they are
    protected. --no-mem-guard is the way to run unguarded, and it has to be said out loud."""
    env = {"REGEN_MEMINFO": str(tmp_path / "no-such-meminfo")}
    args = [tmp_path / "corpus", "--panel", tmp_path / "nope.tsv", "--mem-floor", 30]
    r = _run(*args, mem_guard=True, env_extra=env)

    assert r.returncode == REFUSED, r.stdout + r.stderr
    assert "unreadable" in r.stderr and "silently never fire" in r.stderr, r.stderr


# ═══ PRESENT vs USABLE: a package can exist and be worthless ══════════════════════════════════════════════


def test_a_failing_worker_that_left_a_truncated_package_has_it_purged(tmp_path):
    """★ The producer is `out_path.write_text(json.dumps(...))` — truncate-then-write, no atomic rename — on
    a 1.5-6.7 MB payload, so any death mid-write leaves a file that EXISTS and is TRUNCATED. Reconciliation
    keyed on presence would count that as a finished pair and the freeze would encode it. The purge is
    deliberately CONDITIONAL on the file not parsing: run.py keeps working after the write (the
    --full-package review bundle), so a LATE failure can leave a perfectly good package that must survive."""
    corpus = tmp_path / "corpus"
    panel = _panel(tmp_path / "panel.tsv", THREE)
    stub = _stub_src(tmp_path, STUB_TRUNCATING_RUN_PY)

    env = {"REGEN_RUN_PY": str(stub), "STUB_TRUNCATE": "KRAS-PAAD", "STUB_RC": "1"}
    r = _run(corpus, "--panel", panel, "--jobs", 1, env_extra=env)

    assert r.returncode == INCOMPLETE, r.stdout + r.stderr
    assert "PURGED: KRAS / PAAD" in r.stderr, r.stderr
    assert not (corpus / "KRAS-PAAD" / "evidence_package.json").exists(), "the truncated file must be gone"
    # ★ reported MISSING, not "unparseable": the purge is what makes the two mechanisms distinguishable.
    assert "1 missing, 0 unparseable" in r.stderr, r.stderr
    assert (corpus / "MYC-SCLC" / "evidence_package.json").exists(), "one bad pair must not kill the sweep"


def test_reconciliation_catches_a_package_that_exists_but_does_not_parse(tmp_path):
    """★ The case the purge CANNOT catch, which is why both exist. Here the worker exits 0 having written a
    bad package, so nothing in the per-pair path fires — and the same is true of a truncation this driver
    never caused (a host reboot mid-write, a full disk, the corpus that predates this script). PRESENT and
    USABLE are different sets, and only parsing tells them apart. It costs seconds against a multi-hour
    sweep."""
    corpus = tmp_path / "corpus"
    panel = _panel(tmp_path / "panel.tsv", THREE)
    stub = _stub_src(tmp_path, STUB_TRUNCATING_RUN_PY)

    env = {"REGEN_RUN_PY": str(stub), "STUB_TRUNCATE": "MYC-SCLC", "STUB_RC": "0"}
    r = _run(corpus, "--panel", panel, "--jobs", 1, env_extra=env)

    assert r.returncode == INCOMPLETE, r.stdout + r.stderr
    assert "0 missing, 1 unparseable" in r.stderr, r.stderr
    assert "UNPARSEABLE (1)" in r.stderr and "MYC-SCLC" in r.stderr, r.stderr
    assert "JSONDecodeError" in r.stderr, "name the parse failure, or this reads as a missing run"
    assert "PURGED" not in r.stderr, "a worker that exited 0 must not be treated as a failed one"
    assert "--resume RE-RUNS these" in r.stderr, (
        "the message must not tell the operator to delete files by hand -- --resume now re-runs them, and an "
        "instruction that was true before the pre-flight became parse-aware is now a false conclusion"
    )


def test_resume_reruns_an_unparseable_package_instead_of_skipping_it_forever(tmp_path):
    """★★ SKIP-IF-EXISTS KEYED ON PRESENCE FREEZES A CORRUPT PACKAGE IN PERMANENTLY. Every subsequent
    --resume would skip it, so the corpus can never heal and the reconciliation would fail identically
    forever. Keying the gap-fill on whether the package PARSES is what closes that loop — and the pre-flight
    line must show the two counts SEPARATELY, or an operator cannot tell a re-run from a no-op."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for t, i in THREE:
        _package(corpus, t, i)
    # a reboot caught this one mid-flush: present, 20 bytes, unparseable
    (corpus / "KRAS-PAAD" / "evidence_package.json").write_text('{"target": "KRAS", "clai')
    panel = _panel(tmp_path / "panel.tsv", THREE)
    stub = _stub(tmp_path)

    r = _run(corpus, "--panel", panel, "--resume", env_extra={"REGEN_RUN_PY": str(stub)})

    assert r.returncode == 0, r.stdout + r.stderr
    assert "present 3 | usable 2 | to run 1" in r.stdout, (
        f"the pre-flight must distinguish PRESENT from USABLE: {r.stdout}"
    )
    assert "ok:     KRAS / PAAD" in r.stdout, "the unparseable package must be RE-RUN, not skipped"
    assert "3 of 3" in r.stdout, r.stdout
    json.loads((corpus / "KRAS-PAAD" / "evidence_package.json").read_text())  # healed, not skipped
