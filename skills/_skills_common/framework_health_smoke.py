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

DETERMINISTIC + OFFLINE *because of the coverage predicate*, not by wishful assertion: the
smoke flag is honoured inside `resolve_cards`, so a skill is offline under it ONLY if its run
actually reaches `resolve_cards` — which is exactly what `_wired_subskills()` now requires (a
real `run_wired_skill(` CALL, AST-checked). A subskill that runs clean on stubs is demonstrably
executable end-to-end; a subskill that errors here has a real pipeline break the structural
probe cannot see. This is the "runs clean?" tier of the two-tier liveness ladder (see the
redesign design-doc).

★ WHY THAT SENTENCE IS SO CAREFUL (2026-09-11): it used to read "OFFLINE by construction" and
was FALSE. The predicate text-matched the string "run_wired_skill" anywhere in run.py — including
comments that said the OPPOSITE ("this scan hand-rolls main() (no run_wired_skill)") — so the two
standalone scan-hook skills were smoked despite never calling `resolve_cards`. For them the smoke
flag was INERT and this "offline" harness was issuing live per-sample S3 reads. It reported
smoke=clean for weeks (the reads happened to fail fast), then the 40-partner pair scan started
completing and blew the 120s cap, and because `TimeoutExpired` is a `subprocess.SubprocessError`
the harness recorded a FABRICATED smoke="error" — a machine-load artifact presented as a pipeline
break, which turned release-gate step 2 red. Both defects are fixed below; both scan skills were
retired the same day. The lesson worth keeping: a harness's offline/determinism claim must be
ENFORCED by its coverage rule, or it is just a comment.

Usage:
  python -m _skills_common.framework_health_smoke            # write subskill_health.json
  python -m _skills_common.framework_health_smoke --check    # fail if committed file stale
"""

from __future__ import annotations

import argparse
import ast
import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[1]  # .../skills
_OUT = SKILLS_DIR / "_skills_common" / "subskill_health.json"

# Per-subskill wall-clock cap. Every covered subskill resolves its cards to stubs (see the
# predicate below), so a healthy run is seconds — this is ~10x headroom, not a budget. Exceeding
# it is treated as an ENVIRONMENTAL condition (`timeout`), never as a pipeline break.
_TIMEOUT_SECS = 120

# Fixture invocation — a canonical target/indication that exercises indication-scoped AND
# target-only skills. Values are irrelevant to the signal (readers are stubbed); they only
# need to satisfy argparse + any indication-gated applies_when that runs in-process.
_FIX_TARGET = "FIXTURE"
_FIX_INDICATION = "COADREAD"

# Infra / non-skill dirs to skip. Everything else is admitted or rejected by the CALL predicate
# below — a skill that hand-rolls main() needs no skip entry, because it has no run_wired_skill(
# call to find. (target-archetype used to be listed here; the call predicate excludes it for the
# same reason it excludes every other hand-rolled entrypoint, so the special case is gone. The
# synthetic-lethal-partners / combinatorial-dependency / combo-and-resistance / compose-dashboard
# dirs were retired 2026-09-10, and the bispecific-pair-scan / surfaceome-cohort-ranking scan-hook
# dirs on 2026-09-11 — none needs an entry either.)
_SKIP_DIRS = {
    "_skills_common",
    "tests",
    "render-evidence-package",
    "query-target-evidence",
}


def _calls_run_wired_skill(run_py: Path) -> bool:
    """Does this run.py actually CALL run_wired_skill? — AST, not text.

    The distinction is the whole coverage contract, not pedantry. `FRAMEWORK_HEALTH_SMOKE` is
    honoured inside `resolve_cards`, which only the shared `run_wired_skill` dispatcher reaches;
    a skill that hand-rolls main() and reads a method directly ignores the flag entirely, so
    smoking it issues LIVE reads under a harness that advertises itself as offline.

    The former predicate was `"run_wired_skill" in rp.read_text()`, which matched the name in
    COMMENTS — including comments whose text was a denial ("this scan hand-rolls main() (no
    run_wired_skill)"). Three skills were admitted that way: target-archetype (papered over with
    a skip entry on 2026-09-10) and the two scan-hook skills, whose live 40-partner S3 scan
    finally exceeded the timeout and fabricated a pipeline break. An AST walk cannot make that
    mistake: a name inside a comment or docstring is not a Call node.

    A run.py that fails to parse returns False — uncovered rather than falsely covered. That is
    the fail-closed direction here: an unparseable entrypoint is caught by the structural probe
    and by pytest collection, and reporting it as smoke-covered would be the lie this predicate
    exists to prevent.
    """
    try:
        tree = ast.parse(run_py.read_text())
    except (OSError, SyntaxError):
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
        if name == "run_wired_skill":
            return True
    return False


def _wired_subskills() -> list[str]:
    """Skill dirs whose scripts/run.py CALLS run_wired_skill (the ones this harness can smoke
    offline). Everything else — hand-rolled main(), scan-hooks, reduction-stage companions — is
    left out, and the target-contracts rollup records it as runs_clean="unknown", the honest state
    for "this tier has no measurement," rather than a fabricated clean or error."""
    out = []
    for d in sorted(p.name for p in SKILLS_DIR.iterdir() if p.is_dir()):
        if d.startswith(".") or d in _SKIP_DIRS:
            continue
        rp = SKILLS_DIR / d / "scripts" / "run.py"
        if rp.exists() and _calls_run_wired_skill(rp):
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
                timeout=_TIMEOUT_SECS,
                env=env,
            )
        except subprocess.TimeoutExpired:
            # NOT an error. A timeout says the MACHINE was too slow to finish in the window; it
            # says nothing about whether the compute path is broken. Folding it into `error` (which
            # it was until 2026-09-11, because TimeoutExpired subclasses SubprocessError) let load
            # on the box publish a fabricated pipeline break into a cross-repo health feed and turn
            # the release gate red — the same false-signal class the no-spec drift flag was retired
            # for that morning. Its own state, excluded from n_error, and dropped from the --check
            # comparison (see _stable): absence of a measurement is not a changed measurement.
            return {
                "skill_name": skill,
                "smoke": "timeout",
                "smoke_reason": f"no exit within {_TIMEOUT_SECS}s — machine load, not a verdict on the compute path",
            }
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
    n_timeout = sum(1 for r in results if r["smoke"] == "timeout")
    return {
        "schema_version": "1.1.0",  # 1.1.0: added the `timeout` smoke state + n_timeout
        "harness": "framework_health_smoke",
        "note": (
            "Deterministic offline 'runs clean?' smoke of each wired subskill's real "
            "run.py under FRAMEWORK_HEALTH_SMOKE=1 (card readers stubbed; NO live data). "
            "Coverage = run.py actually CALLS run_wired_skill (AST-checked), which is what "
            "makes the offline guarantee true. smoke=clean → compute path executed + emitted "
            "run_health; clean_uninstrumented → ran clean but hand-rolls main() (no run_health); "
            "error → a real pipeline break; timeout → the machine ran out of time, NOT a verdict "
            "on the skill (excluded from n_error and from the --check comparison)."
        ),
        "summary": {
            "n_subskills": len(skills),
            "n_clean": n_clean,
            "n_clean_uninstrumented": n_uninstrumented,
            "n_error": n_error,
            "n_timeout": n_timeout,
        },
        "subskills": {r["skill_name"]: r for r in results},
    }


def _timed_out(report: dict) -> set[str]:
    """Skills that produced NO measurement in this report (see _stable)."""
    return {name for name, e in (report.get("subskills") or {}).items() if e.get("smoke") == "timeout"}


def _stable(report: dict, unmeasured: set[str] = frozenset()) -> str:
    """Canonical projection dropping volatile timings — the --check basis (mirrors the
    dashboard's stable_projection discipline: run-clean STATUS is stable, seconds are not).

    `unmeasured` drops those skills from BOTH sides of a --check comparison. A timed-out skill
    yielded no reading, and comparing "no reading" against a committed `clean` would report the
    file STALE — reddening the release gate — on nothing but machine load. Dropping it reports
    the honest thing (nothing is known about that skill this run) and the caller names it in the
    output instead. `summary` is dropped for the same reason: it is fully derivable from the
    entries, so it adds no coverage, but its counts would disagree whenever a skill is excluded.
    """
    r = copy.deepcopy(report)
    r.pop("summary", None)
    subskills = r.get("subskills") or {}
    for name in unmeasured:
        subskills.pop(name, None)
    for entry in subskills.values():
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
    unmeasured = _timed_out(report)
    fresh = _stable(report, unmeasured)

    if args.check:
        if not _OUT.exists():
            print(f"  MISSING {_OUT.name} — run without --check to generate.", file=sys.stderr)
            return 1
        if unmeasured:
            # Say so loudly: --check just verified LESS than the whole file.
            print(f"  note: {len(unmeasured)} subskill(s) timed out and are excluded: {', '.join(sorted(unmeasured))}")
        if _stable(json.loads(_OUT.read_text()), unmeasured) != fresh:
            print(
                f"  STALE {_OUT.name} — committed subskill health differs from computed; regenerate.", file=sys.stderr
            )
            return 1
        print(f"  OK {_OUT.name} (fresh)")
        return 0

    if unmeasured:
        # Refuse to COMMIT a non-measurement. Writing `timeout` into the feed would publish "we
        # don't know" as this subskill's standing health and make every later --check compare
        # against it; the committed artifact must be a complete reading. Re-run on a quiet box.
        for name in sorted(unmeasured):
            print(f"    TIMEOUT {name}: {report['subskills'][name].get('smoke_reason')}", file=sys.stderr)
        print(
            f"  REFUSING to write {_OUT.name}: {len(unmeasured)} subskill(s) did not finish, so this "
            f"is a PARTIAL reading, not a health record. Re-run on an unloaded machine.",
            file=sys.stderr,
        )
        return 1

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
    # non-failing state (the skill runs — it's just off the run_health path). A timeout returns
    # above without writing, so it can neither be committed nor silently pass.
    return 1 if s["n_error"] else 0


if __name__ == "__main__":
    sys.exit(main())
