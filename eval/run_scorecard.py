#!/usr/bin/env python3
"""eval/run_scorecard.py — the one-command framework scorecard.

Rolls the framework's EXISTING durable eval harnesses into a single pass + a
consolidated `eval/scorecard.json`. This is an ORCHESTRATOR: it reuses the
committed instruments, it does not reimplement any of them.

Steps (each best-effort, its own subprocess, all rolled into one report):

  1. framework_health   --check    structural WIRED? (target-contracts dashboard staleness)
  2. runs-clean smoke    --check    RUNS-CLEAN? (skills subskill smoke projection)
  3. calibration suite   pytest     per-target known-target regression (snapshots)
  4. discrimination      --check    aggregate predictive validity + regression floors
  5. known-target panel  score-only fresh nominations + SIGNAL VECTOR vs reference_profiles
  6. eval-ledger         --self-check  portfolio-memory artifact integrity

Exit code is non-zero iff any NON-STUB step FAILs or ERRORs — so this command
is a CI-grade gate as well as a human dashboard.

## Interpreters (important)

The steps live in two repos with different environments:
  - target-contracts is BARE python (no pixi) — steps 1,3,4,6 need only pyyaml + pytest.
  - the skills smoke (step 2) imports each subskill's run.py, so it needs the card stack
    (openpyxl, lifelines, pyreadr, gseapy, …) — i.e. the pixi env or system conda with those.

Each step runs under `sys.executable` by default. Override per-family with env vars when the
orchestrator's interpreter can't satisfy a step's imports (the step then reports ERROR, never
crashes the whole scorecard):
  SCORECARD_CONTRACTS_PY   interpreter for target-contracts steps (default: sys.executable)
  SCORECARD_SKILLS_PY      interpreter for the skills smoke step   (default: sys.executable)

Repo locations follow the framework convention (env override, else the SageMaker default layout):
  TARGET_CONTRACTS_ROOT, CLAUDE_ONCOLOGY_SKILLS_ROOT.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# ── repo-root resolution (framework convention: env var, else default layout) ──────────────
_SIBLINGS = Path.home()
_DEFAULT_SKILLS = _SIBLINGS / "rnd-computational-biology-oncology-claude-oncology-skills"
_DEFAULT_CONTRACTS = _SIBLINGS / "rnd-computational-biology-oncology-target-contracts"

SKILLS_ROOT = Path(os.environ.get("CLAUDE_ONCOLOGY_SKILLS_ROOT", _DEFAULT_SKILLS))
CONTRACTS_ROOT = Path(os.environ.get("TARGET_CONTRACTS_ROOT", _DEFAULT_CONTRACTS))

# The orchestrator's own dir (this file lives at <skills_root>/eval/) — but resolve robustly
# so it works from a worktree checkout too.
EVAL_DIR = Path(__file__).resolve().parent
OUT_PATH = EVAL_DIR / "scorecard.json"

CONTRACTS_PY = os.environ.get("SCORECARD_CONTRACTS_PY", sys.executable)
SKILLS_PY = os.environ.get("SCORECARD_SKILLS_PY", sys.executable)

# Status vocabulary (fail-visible): PASS ran+green; FAIL ran+red; ERROR couldn't run
# (missing repo/interpreter/deps); STUB not-yet-implemented (never gates).
PASS, FAIL, ERROR, STUB = "PASS", "FAIL", "ERROR", "STUB"


@dataclass
class Step:
    key: str
    label: str
    kind: str                    # "regression" | "structural" | "memory" | "stub"
    interpreter: str
    argv: list[str]              # argv AFTER the interpreter
    cwd: Path
    env: dict = field(default_factory=dict)
    stub_reason: str = ""


def _steps() -> list[Step]:
    contracts = CONTRACTS_ROOT
    skills = SKILLS_ROOT
    return [
        Step(
            key="framework_health",
            label="Structural health (WIRED?) — dashboard staleness --check",
            kind="structural",
            interpreter=CONTRACTS_PY,
            argv=["validators/framework_health/build_framework_health.py", "--check"],
            cwd=contracts,
        ),
        Step(
            key="runs_clean_smoke",
            label="Runs-clean smoke (RUNS-CLEAN?) — subskill projection --check",
            kind="structural",
            interpreter=SKILLS_PY,
            argv=["-m", "_skills_common.framework_health_smoke", "--check"],
            cwd=skills / "skills",
        ),
        Step(
            key="calibration",
            label="Known-target calibration suite (per-target regression)",
            kind="regression",
            interpreter=CONTRACTS_PY,
            argv=["-m", "pytest", "tests/calibration/", "-q"],
            cwd=contracts,
        ),
        Step(
            key="discrimination",
            label="Framework discrimination (predictive validity + floors --check)",
            kind="regression",
            interpreter=CONTRACTS_PY,
            argv=["validators/validate_framework_discrimination.py", "--check"],
            cwd=contracts,
        ),
        Step(
            # Live known-target backtest, SCORE-ONLY here (fast/offline): scores whatever fresh
            # packages exist against reference_profiles + surfaces the signal-substrate rollup.
            # Populate/refresh packages out-of-band with `run_known_target_panel.py --emit` (slow,
            # needs cbg creds). Gates red only on a real regression (validated_lane now vetoed).
            key="known_target_panel",
            label="Known-target nomination backtest (signal vector; score-only)",
            kind="regression",
            interpreter=CONTRACTS_PY,
            argv=[str(EVAL_DIR / "run_known_target_panel.py")],
            cwd=EVAL_DIR,
        ),
        Step(
            key="eval_ledger",
            label="Eval-ledger portfolio-memory integrity (--self-check)",
            kind="memory",
            interpreter=CONTRACTS_PY,
            argv=["validators/build_eval_ledger.py", "--self-check"],
            cwd=contracts,
        ),
    ]


def _run_step(step: Step, tail_lines: int) -> dict:
    if step.kind == "stub":
        return {"key": step.key, "label": step.label, "kind": step.kind,
                "status": STUB, "returncode": None, "duration_s": 0.0,
                "note": step.stub_reason, "tail": ""}

    if not step.cwd.exists():
        return {"key": step.key, "label": step.label, "kind": step.kind,
                "status": ERROR, "returncode": None, "duration_s": 0.0,
                "note": f"cwd not found: {step.cwd}", "tail": ""}

    env = {**os.environ, **step.env}
    t0 = time.time()
    try:
        proc = subprocess.run(
            [step.interpreter, *step.argv],
            cwd=str(step.cwd), env=env, capture_output=True, text=True, timeout=1800,
        )
    except FileNotFoundError as e:
        return {"key": step.key, "label": step.label, "kind": step.kind,
                "status": ERROR, "returncode": None, "duration_s": round(time.time() - t0, 1),
                "note": f"interpreter not found: {e}", "tail": ""}
    except subprocess.TimeoutExpired:
        return {"key": step.key, "label": step.label, "kind": step.kind,
                "status": ERROR, "returncode": None, "duration_s": round(time.time() - t0, 1),
                "note": "timeout (1800s)", "tail": ""}

    combined = (proc.stdout or "") + (proc.stderr or "")
    tail = "\n".join(combined.strip().splitlines()[-tail_lines:])
    # An import/collection failure (missing deps) is an ERROR, not a real FAIL of the metric.
    is_env_error = proc.returncode != 0 and (
        "ModuleNotFoundError" in combined or "ImportError" in combined
        or "No module named" in combined or "INTERNALERROR" in combined
    )
    status = PASS if proc.returncode == 0 else (ERROR if is_env_error else FAIL)
    return {"key": step.key, "label": step.label, "kind": step.kind,
            "status": status, "returncode": proc.returncode,
            "duration_s": round(time.time() - t0, 1), "note": "", "tail": tail}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="One-command framework eval scorecard.")
    ap.add_argument("--json", action="store_true", help="print the scorecard JSON to stdout too")
    ap.add_argument("--tail", type=int, default=12, help="lines of each step's output to retain")
    ap.add_argument("--only", nargs="*", help="run only these step keys")
    args = ap.parse_args(argv)

    steps = _steps()
    if args.only:
        steps = [s for s in steps if s.key in set(args.only)]

    results = [_run_step(s, args.tail) for s in steps]

    report = {
        "schema_version": "1.0.0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "roots": {"skills": str(SKILLS_ROOT), "contracts": str(CONTRACTS_ROOT)},
        "interpreters": {"contracts": CONTRACTS_PY, "skills": SKILLS_PY},
        "steps": results,
    }
    tally = {s: sum(1 for r in results if r["status"] == s) for s in (PASS, FAIL, ERROR, STUB)}
    report["summary"] = tally
    # The gate: green iff no non-stub step is red or un-runnable.
    gating = [r for r in results if r["kind"] != "stub"]
    report["gate_green"] = all(r["status"] == PASS for r in gating)

    OUT_PATH.write_text(json.dumps(report, indent=2))

    # ── console table ──────────────────────────────────────────────────────────────────────
    print(f"\n=== FRAMEWORK SCORECARD  ({report['generated_at']}) ===")
    for r in results:
        mark = {PASS: "✓", FAIL: "✗", ERROR: "!", STUB: "·"}[r["status"]]
        dur = f"{r['duration_s']:.0f}s" if r["status"] not in (STUB,) else "—"
        print(f"  [{mark}] {r['status']:5} {r['key']:20} {dur:>6}  {r['label']}")
        if r["note"]:
            print(f"          note: {r['note']}")
        if r["status"] in (FAIL, ERROR) and r["tail"]:
            for ln in r["tail"].splitlines()[-6:]:
                print(f"          | {ln}")
    print(f"\n  tally: {tally}   gate: {'GREEN' if report['gate_green'] else 'RED'}")
    print(f"  wrote {OUT_PATH}")

    if args.json:
        print(json.dumps(report, indent=2))
    return 0 if report["gate_green"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
