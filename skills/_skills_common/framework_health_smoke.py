#!/usr/bin/env python3
"""framework_health_smoke.py — deterministic "runs clean?" health harness.

The framework-health dashboard's structural probes answer "is this subskill WIRED?"
(entrypoint, reader, method dir present). This harness answers the orthogonal
"does it RUN CLEAN?" — does the compute path (resolve_cards → fire rules → verdict →
run_health) execute end-to-end without error — WITHOUT any live/S3 read.

How: run each wired subskill's REAL run.py in a subprocess with FRAMEWORK_HEALTH_SMOKE=1
(resolve_cards then returns synthetic empty card stubs instead of live dispatcher reads —
see _skills_common.resolve_cards) on a fixture target. Capture the run_health block the
dispatcher emits into decision.json. Roll all subskills into ONE committed
subskill_health.json that the target-contracts health probe reads.

DETERMINISTIC + OFFLINE by construction: no network, no credentials, no live data. A
subskill that runs clean on stubs is demonstrably executable end-to-end; a subskill that
errors here has a real pipeline break the structural probe cannot see. This is the
"runs clean?" tier of the two-tier liveness ladder (see the redesign design-doc).

Usage:
  python -m _skills_common.framework_health_smoke            # write subskill_health.json
  python -m _skills_common.framework_health_smoke --check    # fail if committed file stale
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[1]  # .../skills
_OUT = SKILLS_DIR / "_skills_common" / "subskill_health.json"

# Fixture invocation — a canonical target/indication that exercises indication-scoped AND
# target-only skills. Values are irrelevant to the signal (readers are stubbed); they only
# need to satisfy argparse + any indication-gated applies_when that runs in-process.
_FIX_TARGET = "FIXTURE"
_FIX_INDICATION = "COADREAD"

# Non-run.py / non-wired skill dirs to skip (orchestration/retrieval/workflow + infra).
_SKIP_DIRS = {
    "_skills_common",
    "tests",
    "render-evidence-package",
    "query-target-evidence",
    # (The synthetic-lethal-partners / combinatorial-dependency / combo-and-resistance /
    # compose-dashboard skill dirs were retired 2026-09-10 — consolidated into
    # combination-and-vulnerability / report_render — so no skip entry is needed.)
}


def _wired_subskills() -> list[str]:
    """Skill dirs whose scripts/run.py calls run_wired_skill (the ones this harness covers)."""
    out = []
    for d in sorted(p.name for p in SKILLS_DIR.iterdir() if p.is_dir()):
        if d.startswith(".") or d in _SKIP_DIRS:
            continue
        rp = SKILLS_DIR / d / "scripts" / "run.py"
        if rp.exists() and "run_wired_skill" in rp.read_text():
            out.append(d)
    return out


def _smoke_one(skill: str) -> dict:
    """Run one subskill's real run.py under the smoke flag; return its run_health (+ harness
    status). A non-zero exit or missing run_health is a FAILED smoke — the real signal."""
    rp = SKILLS_DIR / skill / "scripts" / "run.py"
    with tempfile.TemporaryDirectory() as td:
        env = {
            **os.environ,
            "FRAMEWORK_HEALTH_SMOKE": "1",
            "PYTHONPATH": str(SKILLS_DIR) + os.pathsep + os.environ.get("PYTHONPATH", ""),
        }
        try:
            proc = subprocess.run(
                [sys.executable, str(rp), "--target", _FIX_TARGET, "--indication", _FIX_INDICATION, "--out", td],
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
            )
        except subprocess.SubprocessError as e:
            return {"skill_name": skill, "smoke": "error", "smoke_reason": f"subprocess: {type(e).__name__}: {e}"}
        dj = Path(td) / "decision.json"
        if proc.returncode != 0:
            # last stderr line is the useful bit; keep the record small.
            tail = (proc.stderr or "").strip().splitlines()[-1:] or [""]
            return {
                "skill_name": skill,
                "smoke": "error",
                "exit_code": proc.returncode,
                "smoke_reason": f"run.py exit {proc.returncode}: {tail[0][:200]}",
            }
        if not dj.exists():
            return {"skill_name": skill, "smoke": "error", "smoke_reason": "run.py exited 0 but wrote no decision.json"}
        try:
            rh = json.loads(dj.read_text()).get("run_health")
        except (OSError, json.JSONDecodeError) as e:
            return {"skill_name": skill, "smoke": "error", "smoke_reason": f"unreadable decision.json: {e}"}
        if not rh:
            # Ran clean (exit 0, wrote a decision.json) but emitted NO run_health — the skill
            # HAND-ROLLS main() instead of calling run_wired_skill (e.g. genomic-alteration-profile,
            # for custom subtype fan-out). That is an honest, distinct state: the compute path
            # executes, but it's off the instrumented dispatcher, so we have no read/compute split.
            # Reporting this as 'error' would overstate the problem (the skill works); reporting it
            # as 'clean' would hide that it's not covered by run_health. So: its own status.
            return {
                "skill_name": skill,
                "smoke": "clean_uninstrumented",
                "smoke_reason": "ran clean but hand-rolls main() (no run_wired_skill) → no run_health",
            }
        # smoke passes iff the run completed and emitted run_health. run_health.status
        # (ok|degraded) is the dispatcher's own read of card availability — under smoke all
        # cards resolve to stubs, so status should be 'ok'; a 'degraded' here means the
        # skill declares on_dependency_status skips even for present cards (informative).
        return {
            "skill_name": skill,
            "smoke": "clean",
            "run_health": {
                k: rh.get(k)
                for k in (
                    "status",
                    "n_cards_consumed",
                    "n_cards_resolved",
                    "n_cards_fired",
                    "cards_fired",
                    "read_secs",
                    "compute_secs",
                    "total_secs",
                )
            },
        }


def build() -> dict:
    skills = _wired_subskills()
    results = [_smoke_one(s) for s in skills]
    n_clean = sum(1 for r in results if r["smoke"] == "clean")
    n_uninstrumented = sum(1 for r in results if r["smoke"] == "clean_uninstrumented")
    n_error = sum(1 for r in results if r["smoke"] == "error")
    return {
        "schema_version": "1.0.0",
        "harness": "framework_health_smoke",
        "note": (
            "Deterministic offline 'runs clean?' smoke of each wired subskill's real "
            "run.py under FRAMEWORK_HEALTH_SMOKE=1 (card readers stubbed; NO live data). "
            "smoke=clean → compute path executed + emitted run_health; clean_uninstrumented "
            "→ ran clean but hand-rolls main() (no run_health); error → a real pipeline break."
        ),
        "summary": {
            "n_subskills": len(skills),
            "n_clean": n_clean,
            "n_clean_uninstrumented": n_uninstrumented,
            "n_error": n_error,
        },
        "subskills": {r["skill_name"]: r for r in results},
    }


def _stable(report: dict) -> str:
    """Canonical projection dropping volatile timings — the --check basis (mirrors the
    dashboard's stable_projection discipline: run-clean STATUS is stable, seconds are not)."""
    import copy

    r = copy.deepcopy(report)
    for entry in r.get("subskills", {}).values():
        rh = entry.get("run_health") or {}
        for vol in ("read_secs", "compute_secs", "total_secs"):
            rh.pop(vol, None)
    return json.dumps(r, indent=2, sort_keys=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Framework-health 'runs clean?' subskill smoke harness.")
    ap.add_argument(
        "--check",
        action="store_true",
        help="fail (exit 1) if the committed subskill_health.json is stale vs a fresh smoke "
        "(compares a STABLE projection dropping volatile timings)",
    )
    args = ap.parse_args(argv)

    report = build()
    fresh = _stable(report)

    if args.check:
        if not _OUT.exists():
            print(f"  MISSING {_OUT.name} — run without --check to generate.", file=sys.stderr)
            return 1
        if _stable(json.loads(_OUT.read_text())) != fresh:
            print(
                f"  STALE {_OUT.name} — committed subskill health differs from computed; regenerate.", file=sys.stderr
            )
            return 1
        print(f"  OK {_OUT.name} (fresh)")
        return 0

    _OUT.write_text(json.dumps(report, indent=2))
    s = report["summary"]
    print(
        f"  wrote {_OUT.name}: {s['n_subskills']} subskills, {s['n_clean']} clean, "
        f"{s['n_clean_uninstrumented']} clean-uninstrumented, {s['n_error']} error"
    )
    for name, r in report["subskills"].items():
        if r["smoke"] == "error":
            print(f"    ERROR {name}: {r.get('smoke_reason')}", file=sys.stderr)
        elif r["smoke"] == "clean_uninstrumented":
            print(f"    note {name}: {r.get('smoke_reason')}")
    # Only a real pipeline break (error) fails the harness; clean_uninstrumented is an honest,
    # non-failing state (the skill runs — it's just off the run_health path).
    return 1 if s["n_error"] else 0


if __name__ == "__main__":
    sys.exit(main())
