#!/usr/bin/env python3
"""eval/loop/run_batch.py — the subskill iteration loop's batch runner (SK#2303 Phase 0, WI-A, #2345).

Takes a roster of `target × indication` triples and invokes ONE skill's
`skills/<skill>/scripts/run.py --emit-envelope` per triple, under pixi (py3.14) +
`AWS_PROFILE=cbg`, laying the emitted `evidence_package.json` packages out for the downstream
substrate assembler (WI-B) and triangulation judge (WI-C).

Interpreter (measured in the Phase -1 pilot, durable — see `eval/ITERATION_RUNBOOK.md`):
`conda` lacks `onc_methods` post-#2257 and silently returns false-`insufficient` with
`read_error: No module named onc_methods` on every card. This runner never shells out to a bare
`python` — it re-execs itself under `pixi run python` unless `RUN_BATCH_SKIP_PIXI_REEXEC=1` is set
(tests / an already-pixi'd shell).

The 4-clause preflight sentinel (see `preflight_sentinel`) decides, per triple, whether the emitted
package is USABLE — a liveness check, never a verdict judgement:
  1. n_cards_resolved > 0            (dead run = 0; a partial 12-16 of 17 is FINE)
  2. verdict != "insufficient" AND fired_rules > 0
  3. all four named envelope sections present (source_properties / integrated_properties /
     local_composites / l3d)
  4. no card carries a `read_error` availability_state

None of the known fake sentinels discriminate (rc=0 fires on both good and dead runs; the emitted
card_id roster and local_composites presence are IDENTICAL good-vs-dead) — only the 4 clauses above do.

Concurrency: JOBS default 3, hard ceiling 4 (measured: 2.4x throughput at 3 with packages staying
alive; 6-wide reboots the host — no swap).

Output layout: `eval/loop/runs/iter-NNN-<sha>/<target>_<indication>.json`, plus a sibling
`manifest.json` (roster, skills-repo SHA, per-triple sentinel result + timing).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

LOOP_DIR = Path(__file__).resolve().parent
EVAL_DIR = LOOP_DIR.parent
SKILLS_REPO_ROOT = EVAL_DIR.parent
RUNS_ROOT = LOOP_DIR / "runs"

JOBS_DEFAULT = 3
JOBS_CEILING = 4  # measured: 6-wide reboots the host (no swap) — never raise this silently

# The 4 named top-level envelope sections (SK#1941, docs/EVIDENCE_PROPERTY_ARCHITECTURE_L1_L4.md).
# Not every skill exports all four today (only tumor-presence does; dependency/safety/genomic
# export 3 of 4, several export none) — clause 3 is deliberately strict so the sentinel is honest
# about which triples are USABLE by today's wiring, not a verdict on the skill's maturity.
ENVELOPE_SECTIONS = ("source_properties", "integrated_properties", "local_composites", "l3d")


def _slug(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", str(s).strip())


def skills_repo_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=8", "HEAD"],
            cwd=SKILLS_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001 — the SHA is provenance, not load-bearing; never block a run
        return "unknown"


# ── roster ───────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Triple:
    target: str
    indication: str

    @property
    def key(self) -> str:
        return f"{_slug(self.target)}_{_slug(self.indication)}"


def load_roster(path: Path) -> list[Triple]:
    """Roster file: a JSON list of either `[target, indication]` pairs or
    `{"target": ..., "indication": ...}` objects. Order is preserved; duplicates are deduped
    (first occurrence wins) so a hand-edited roster can't silently double-run a triple."""
    raw = json.loads(path.read_text())
    if not isinstance(raw, list):
        raise ValueError(f"roster {path} must be a JSON list of triples")
    seen: set[str] = set()
    out: list[Triple] = []
    for row in raw:
        if isinstance(row, (list, tuple)):
            target, indication = row[0], row[1]
        elif isinstance(row, dict):
            target, indication = row["target"], row["indication"]
        else:
            raise ValueError(f"roster entry {row!r} is neither a [target, indication] pair nor an object")
        t = Triple(target=str(target), indication=str(indication))
        if t.key in seen:
            continue
        seen.add(t.key)
        out.append(t)
    return out


# ── the 4-clause preflight sentinel ─────────────────────────────────────────────────────────────


@dataclass
class SentinelResult:
    status: str  # "dead" | "partial" | "alive"
    usable: bool
    reasons: list[str] = field(default_factory=list)
    n_cards_resolved: int = 0
    n_cards_attempted: int = 0
    verdict: "str | None" = None
    fired_rules: int = 0
    sections_present: list[str] = field(default_factory=list)
    read_error_cards: list[str] = field(default_factory=list)


def preflight_sentinel(package: dict) -> SentinelResult:
    """Apply the 4-clause liveness check to an emitted evidence_package.json dict.

    Clause-by-clause (any failure => usable=False):
      1. n_cards_resolved > 0           — n_cards_passed from governance.validation_summary
                                           (a dead run resolves zero cards; dispatcher rc=0 either way).
      2. verdict != "insufficient" AND fired_rules > 0
      3. all four named envelope sections present (and non-null)
      4. no card entry carries availability_state == "read_error"

    status: "dead" (n_cards_resolved == 0), "partial" (usable but n_cards_resolved < n_cards_attempted),
    "alive" (usable and every attempted card resolved). A partial 12/17 is FINE and marked usable —
    partial coverage is a genuine per-target gap, not a defect; only a hard-fail clause marks dead.
    """
    reasons: list[str] = []

    cards = package.get("cards") or []
    read_error_cards = sorted(c.get("card_id", "?") for c in cards if c.get("availability_state") == "read_error")

    governance = package.get("governance") or {}
    validation_summary = governance.get("validation_summary") or {}
    n_cards_resolved = int(validation_summary.get("n_cards_passed", 0) or 0)
    n_cards_attempted = int(validation_summary.get("n_cards_attempted", 0) or 0)

    synthesis = package.get("synthesis") or {}
    verdict = synthesis.get("verdict")
    fired_rule_ids = synthesis.get("fired_rule_ids") or []
    fired_rules = len(fired_rule_ids)

    sections_present = [s for s in ENVELOPE_SECTIONS if package.get(s) is not None]

    clause1 = n_cards_resolved > 0
    if not clause1:
        reasons.append("clause1: n_cards_resolved == 0 (dead run)")

    clause2 = verdict is not None and verdict != "insufficient" and fired_rules > 0
    if not clause2:
        reasons.append(
            f"clause2: verdict={verdict!r} fired_rules={fired_rules} "
            "(need verdict != 'insufficient' AND fired_rules > 0)"
        )

    clause3 = len(sections_present) == len(ENVELOPE_SECTIONS)
    if not clause3:
        missing = sorted(set(ENVELOPE_SECTIONS) - set(sections_present))
        reasons.append(f"clause3: missing envelope section(s) {missing}")

    clause4 = not read_error_cards
    if not clause4:
        reasons.append(f"clause4: read_error on card(s) {read_error_cards}")

    usable = clause1 and clause2 and clause3 and clause4
    if n_cards_resolved == 0:
        status = "dead"
    elif usable and n_cards_resolved >= n_cards_attempted and n_cards_attempted > 0:
        status = "alive"
    elif usable:
        status = "partial"
    else:
        status = "dead"

    return SentinelResult(
        status=status,
        usable=usable,
        reasons=reasons,
        n_cards_resolved=n_cards_resolved,
        n_cards_attempted=n_cards_attempted,
        verdict=verdict,
        fired_rules=fired_rules,
        sections_present=sections_present,
        read_error_cards=read_error_cards,
    )


# ── per-triple invocation ───────────────────────────────────────────────────────────────────────


def _pixi_reexec_if_needed() -> None:
    """Re-exec this process under `pixi run python` unless already running under one (tests set
    RUN_BATCH_SKIP_PIXI_REEXEC=1 to stay in-process; a shell that already invoked us via
    `pixi run python eval/loop/run_batch.py ...` is a no-op re-exec guard via the env marker)."""
    if os.environ.get("RUN_BATCH_SKIP_PIXI_REEXEC") == "1" or os.environ.get("_RUN_BATCH_PIXI_REEXECED") == "1":
        return
    env = {**os.environ, "_RUN_BATCH_PIXI_REEXECED": "1"}
    argv = ["pixi", "run", "python", str(Path(__file__).resolve()), *sys.argv[1:]]
    rc = subprocess.run(argv, cwd=SKILLS_REPO_ROOT, env=env).returncode
    sys.exit(rc)


def run_one(skill: str, triple: Triple, out_dir: Path, timeout: int) -> dict:
    """Invoke `skills/<skill>/scripts/run.py --emit-envelope` for one triple. Returns a manifest
    row: {target, indication, status, usable, reasons, duration_s, package_path, rc}."""
    run_py = SKILLS_REPO_ROOT / "skills" / skill / "scripts" / "run.py"
    out_dir.mkdir(parents=True, exist_ok=True)
    argv = [
        sys.executable,
        str(run_py),
        "--target",
        triple.target,
        "--indication",
        triple.indication,
        "--out",
        str(out_dir),
        "--emit-envelope",
    ]
    env = {**os.environ, "AWS_PROFILE": "cbg"}
    t0 = time.time()
    row: dict = {
        "target": triple.target,
        "indication": triple.indication,
        "skill": skill,
        "package_path": str(out_dir / "evidence_package.json"),
    }
    try:
        r = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout)
        row["rc"] = r.returncode
        pkg_path = out_dir / "evidence_package.json"
        if r.returncode == 0 and pkg_path.exists():
            try:
                package = json.loads(pkg_path.read_text())
            except (ValueError, OSError) as e:
                row.update(status="dead", usable=False, reasons=[f"unparseable package: {e}"])
                return _finish(row, t0)
            sentinel = preflight_sentinel(package)
            row.update(
                status=sentinel.status,
                usable=sentinel.usable,
                reasons=sentinel.reasons,
                n_cards_resolved=sentinel.n_cards_resolved,
                n_cards_attempted=sentinel.n_cards_attempted,
                verdict=sentinel.verdict,
                fired_rules=sentinel.fired_rules,
            )
        else:
            row.update(
                status="dead",
                usable=False,
                reasons=[f"rc={r.returncode} stderr_tail={(r.stderr or '')[-200:].strip()!r}"],
            )
    except subprocess.TimeoutExpired:
        row.update(status="dead", usable=False, reasons=[f"timeout after {timeout}s"])
    return _finish(row, t0)


def _finish(row: dict, t0: float) -> dict:
    row["duration_s"] = round(time.time() - t0, 1)
    return row


def _existing_package_is_valid(pkg_path: Path) -> bool:
    """--resume support: an existing package counts as valid (skip the re-run) iff it parses AND
    the sentinel marks it usable (alive or partial). A dead existing package IS re-run."""
    if not pkg_path.exists():
        return False
    try:
        package = json.loads(pkg_path.read_text())
    except (ValueError, OSError):
        return False
    return preflight_sentinel(package).usable


# ── batch orchestration ─────────────────────────────────────────────────────────────────────────


def next_iter_dir(runs_root: Path, sha: str, iter_tag: "str | None") -> Path:
    if iter_tag is not None:
        return runs_root / f"iter-{iter_tag}-{sha}"
    existing = sorted(runs_root.glob("iter-*-*")) if runs_root.exists() else []
    nums = []
    for p in existing:
        m = re.match(r"iter-(\d+)-", p.name)
        if m:
            nums.append(int(m.group(1)))
    n = (max(nums) + 1) if nums else 1
    return runs_root / f"iter-{n:03d}-{sha}"


def run_batch(
    skill: str,
    roster: list[Triple],
    iter_dir: Path,
    jobs: int = JOBS_DEFAULT,
    resume: bool = False,
    timeout: int = 400,
) -> dict:
    jobs = max(1, min(jobs, JOBS_CEILING))
    iter_dir.mkdir(parents=True, exist_ok=True)

    todo: list[Triple] = []
    skipped: list[dict] = []
    for t in roster:
        pkg_path = iter_dir / f"{t.key}.json"
        if resume and _existing_package_is_valid(pkg_path):
            skipped.append({"target": t.target, "indication": t.indication, "status": "resumed_valid"})
            continue
        todo.append(t)

    rows: list[dict] = list(skipped)
    t_batch0 = time.time()
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futs = {}
        for t in todo:
            out_dir = iter_dir / f"_emit__{t.key}"
            futs[pool.submit(run_one, skill, t, out_dir, timeout)] = t
        for fut in as_completed(futs):
            row = fut.result()
            dest = iter_dir / f"{Triple(row['target'], row['indication']).key}.json"
            emitted = Path(row["package_path"])
            if emitted.exists():
                dest.write_text(emitted.read_text())
            row["package_path"] = str(dest) if emitted.exists() else None
            rows.append(row)
            print(
                f"  [{row.get('status', '?')}] {row['target']}/{row['indication']} ({row.get('duration_s', '?')}s)",
                flush=True,
            )

    manifest = {
        "skill": skill,
        "iter_dir": str(iter_dir),
        "skills_repo_sha": skills_repo_sha(),
        "jobs": jobs,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "roster_size": len(roster),
        "n_run": len(todo),
        "n_resumed": len(skipped),
        "duration_s": round(time.time() - t_batch0, 1),
        "triples": sorted(rows, key=lambda r: (r["target"], r["indication"])),
        "summary": {
            "alive": sum(1 for r in rows if r.get("status") == "alive"),
            "partial": sum(1 for r in rows if r.get("status") == "partial"),
            "dead": sum(1 for r in rows if r.get("status") == "dead"),
            "resumed_valid": sum(1 for r in rows if r.get("status") == "resumed_valid"),
        },
    }
    (iter_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────────


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("--skill", required=True, help="skill directory name under skills/ (e.g. tumor-presence)")
    ap.add_argument("--roster", required=True, type=Path, help="JSON roster: [[target, indication], ...]")
    ap.add_argument(
        "--jobs", type=int, default=JOBS_DEFAULT, help=f"concurrency (default {JOBS_DEFAULT}, ceiling {JOBS_CEILING})"
    )
    ap.add_argument("--resume", action="store_true", help="skip triples with a valid existing package")
    ap.add_argument("--timeout", type=int, default=400, help="per-triple subprocess timeout (s)")
    ap.add_argument("--runs-root", type=Path, default=RUNS_ROOT, help="override the runs/ root (tests)")
    ap.add_argument("--iter-tag", default=None, help="override the auto-incremented iter-NNN tag")
    args = ap.parse_args(argv)

    _pixi_reexec_if_needed()

    roster = load_roster(args.roster)
    sha = skills_repo_sha()
    iter_dir = next_iter_dir(args.runs_root, sha, args.iter_tag)
    print(f"[run_batch] skill={args.skill} roster={len(roster)} jobs={args.jobs} -> {iter_dir}", flush=True)
    manifest = run_batch(
        skill=args.skill,
        roster=roster,
        iter_dir=iter_dir,
        jobs=args.jobs,
        resume=args.resume,
        timeout=args.timeout,
    )
    print(f"[run_batch] done: {manifest['summary']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
