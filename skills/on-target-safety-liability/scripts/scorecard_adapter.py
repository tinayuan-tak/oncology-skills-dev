#!/usr/bin/env python
"""on-target-safety-liability scorecard adapter (#1990) — copies the tumor-presence exemplar's shape
(#1988, A0c, the NORMATIVE example). This is the ENTIRE adapter write surface for
on-target-safety-liability: it builds the shard in memory and calls ``write_skill_shard``, which
touches exactly ``scorecard/on-target-safety-liability.json``.

## Layer mapping

on-target-safety-liability has NOT built the SK#1941-style EXPORTED evidence-package sections
(``source_properties`` / ``integrated_properties`` / ``l3d``) that tumor-presence's L2a/L2b/L3
grain rests on — a repo-wide grep for those section names under
``skills/on-target-safety-liability/`` returns nothing. So here:

  L1  — the CARDS list (``run.py::CARDS``) + their disposition ledger (``field_disposition.yaml``)
        as inventoried; part of the fleet-wide floor enforced by
        ``skills/tests/test_field_disposition_ledgers.py``.
  L2a/L2b/L3/L4 — NOT_BUILT (``built=False``): this skill has no exported source_properties /
        integrated_properties / l3d sections, and no L4 synthesis/decision-view layer. An
        architecture gap by design (mirrors tumor-presence's own L4), not a defect — no criterion
        may be measured on an unbuilt layer.

## What "accuracy" means here (NULL by design, per the issue)

Criterion (a) re-derivation from raw substrate is explicitly OUT OF SCOPE for this issue and is
already covered by the #1792/#1793/#1794 verification work (per the issue's own "Safety note"): "do
NOT fake it here: emit criterion (a) = NULL." A fixture of already-derived values can never fail; an
honest NULL beats a fake reconciliation. L1 accuracy is NULL with that reasoning recorded.

## Fail-open regression teeth (the #1792/#1793/#1794 closure)

This skill just had three fail-open bugs closed:
  - #1792 whole-axis confidence gating on thin coverage (critical_axes broadened to all 7 legs).
  - #1793 the TPHP HPA-BLIND vital-organ coverage gap (a previously-uncovered vital organ read
    CLEAN instead of surfacing the coverage hole).
  - #1794 the pan-essential fail-open closure (unanchored + graded-band routing, so a curated-anchor
    outage or a partial broad-tox band no longer reads falsely clean/tolerant).
criterion (c) here re-asserts the ordinary open-world path (`_SAFETY_OPEN_WORLD` /
`_safety_availability` -> `assemble_claim_record`'s ignorance-!=-negation invariant) AND proves it
has teeth by defeating the guard and watching the probe go RED
(`tests/test_scorecard_l1_fail_open_probe.py`) — the same shape of regression the #179x closures fix,
kept green going forward.

## Panel-consistency is COMPUTED, not hand-typed (the teeth)

`collect_panel_rows()` mirrors tumor-presence's `_load_package` pattern exactly: it drives THIS
skill's own light entrypoint (`scripts/run.py --target <T> --indication <I> --out <dir>`) across the
5-target roster and extracts the verdict-bearing headline field (`safety_verdict`, on
`decision.json.headline`), then asserts non-vacuity (the class isn't constant across the roster —
PLK1's pan-essential control and HTR1D's thin-coverage abstention control are deliberately chosen to
diverge from the flagship targets, per `eval/SCORECARD_PANEL_ROSTER.md`).

If the full 5-target roster packages are not all present (no cache, live run fails/times out/lacks
credentials), panel_consistency is left NULL-with-disposition (never a partial-roster GREEN/RED),
per the issue's explicit instruction.

## Evidence recipe

Every evidence dict below either (a) names a COMMITTED, currently-green test (utilization/fail_open
— re-run before trusting the shard) or (b) is COMPUTED live from real per-target packages
(panel_consistency) — never a static claim with no test/artifact behind it.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
REPO_ROOT = SKILLS_ROOT.parent

from _skills_common import component_scorecard as cs  # noqa: E402

SKILL = "on-target-safety-liability"

# ── L1 evidence: utilization / fail_open (test-backed, static evidence dicts) ──────────────────────

_L1_ACCURACY_NULL_REASON = (
    "criterion (a) re-derivation from raw substrate is OUT OF SCOPE for this issue per #1990's own "
    "ask and its explicit safety note ('covered by the #1792/#1793/#1794 verification work — do not "
    "duplicate a re-derivation here'). A fixture of already-derived values can never fail; left NULL "
    "rather than fabricating a reconciliation this adapter was not asked to build."
)

_L1_UTILIZATION_EVIDENCE = {
    "method": (
        "field_disposition.yaml ledger: every emitted summary_field carries an explicit disposition "
        "(signal|context|provenance|display). The fleet-wide guard "
        "(skills/tests/test_field_disposition_ledgers.py) enforces, once for every ledgered skill, "
        "that the declaration is well-formed and that every role:signal row is reader-reached or "
        "explicitly waived — on-target-safety-liability is on the frozen LEDGERED_SKILLS_FLOOR (may "
        "never quietly lose its ledger)."
    ),
    "tests": [
        "skills/tests/test_field_disposition_ledgers.py::test_ledgered_skills_only_grow",
        "skills/tests/test_field_disposition_ledgers.py::test_every_ledger_is_wellformed",
        "skills/tests/test_field_disposition_ledgers.py::test_the_fleet_reach_measurement_is_not_vacuous",
        "skills/tests/test_field_disposition_ledgers.py::test_signal_fields_are_reader_reached_or_waived",
    ],
    "coverage": "on-target-safety-liability ledgered (on LEDGERED_SKILLS_FLOOR); fleet-wide MIN_FLEET_SIGNAL_ROWS floor",
    "status_as_of": "2026-09-29",
}

_L1_FAIL_OPEN_EVIDENCE = {
    "method": (
        "the skill's own claim-record shadow builder (`run.py::_claim_record` -> "
        "`_skills_common.claim_record.assemble_claim_record`): `_safety_availability()` maps an "
        "unreachable/absent verdict token (data_unavailable/None) through this skill's own "
        "`_SAFETY_OPEN_WORLD` set to availability='not_wired', which the shared assembler forces to "
        "state='unknown', direction='neutral', magnitude.level='none' — never a manufactured "
        "directional finding out of absence (the shared open-world invariant, "
        "'ignorance != negation'). This is the same fail-open class the #1792/#1793/#1794 closures "
        "fixed on the resolver side; this probe re-asserts it on the claim-record shadow side with "
        "seeded teeth."
    ),
    "tests": [
        "skills/on-target-safety-liability/tests/test_claim_record_shadow.py"
        "::test_data_unavailable_is_open_world_noncommittal (ordinary path, pre-existing)",
        "skills/on-target-safety-liability/tests/test_scorecard_l1_fail_open_probe.py"
        "::test_data_unavailable_degrades_conservatively_ordinary_path (ordinary path, re-asserted "
        "locally for this shard)",
        "skills/on-target-safety-liability/tests/test_scorecard_l1_fail_open_probe.py"
        "::test_teeth_defeating_the_open_world_guard_lets_the_raw_token_leak (TEETH — monkeypatches "
        "run.py::_SAFETY_OPEN_WORLD to frozenset() and shows the record leaks the raw "
        "'data_unavailable' token instead of unknown/not_wired; probe goes RED without the guard, "
        "GREEN with it)",
    ],
    "status_as_of": "2026-09-29",
}

# ── L1 panel_consistency: COMPUTED live from real per-target packages ──────────────────────────────

ROSTER: tuple[tuple[str, str], ...] = (
    ("EPCAM", "COADREAD"),
    ("KRAS", "COADREAD"),
    ("ERBB2", "BRCA"),
    ("PLK1", "COADREAD"),
    ("HTR1D", "COADREAD"),
)

RUN_PY = SKILL_DIR / "scripts" / "run.py"
PANEL_CACHE_DIR = SKILL_DIR / "scripts" / ".panel_cache"  # gitignored, mirrors tumor-presence's cache


def _load_package(target: str, indication: str, *, timeout: int = 300) -> tuple[dict | None, str | None]:
    """Load on-target-safety-liability's decision.json for one roster pair — from the on-disk cache
    if present, else a live run of this skill's OWN entrypoint. Returns (package_dict, source_str),
    or (None, None) if genuinely unavailable — absence is reported, never silently substituted."""
    dest = PANEL_CACHE_DIR / f"{target}__{indication.lower()}"
    cached = dest / "decision.json"
    if cached.exists():
        try:
            return json.loads(cached.read_text()), str(cached.relative_to(REPO_ROOT))
        except (OSError, json.JSONDecodeError):
            pass
    dest.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(
            [sys.executable, str(RUN_PY), "--target", target, "--indication", indication, "--out", str(dest)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, None
    if r.returncode != 0 or not cached.exists():
        return None, None
    return json.loads(cached.read_text()), str(cached.relative_to(REPO_ROOT))


def collect_panel_rows() -> tuple[list[dict], dict]:
    """The panel-consistency criterion's live computation: one row per roster pair (its
    verdict-bearing safety_verdict, or PACKAGE_MISSING) plus a non-vacuity check over the roster."""
    rows: list[dict] = []
    for target, indication in ROSTER:
        pkg, source = _load_package(target, indication)
        if pkg is None:
            rows.append({"target": target, "indication": indication, "status": "PACKAGE_MISSING", "source": None})
            continue
        headline = pkg.get("headline", {})
        rows.append(
            {
                "target": target,
                "indication": indication,
                "status": "OK",
                "source": source,
                "safety_verdict": headline.get("safety_verdict"),
            }
        )

    ok_rows = [r for r in rows if r["status"] == "OK"]
    all_present = len(ok_rows) == len(ROSTER)
    safety_classes = {r.get("safety_verdict") for r in ok_rows} - {None}

    checks = {
        "all_roster_rows_present": all_present,
        "safety_verdict_not_constant": len(safety_classes) > 1,
    }
    checks["all_pass"] = all(checks.values())
    return rows, checks


def _panel_consistency_criterion() -> cs.Criterion:
    rows, checks = collect_panel_rows()
    all_present = checks["all_roster_rows_present"]
    evidence = {
        "method": (
            "per-target rows across the whole 5-target roster (not one flagship), COMPUTED live by "
            "collect_panel_rows() (see module docstring) rather than hand-typed: this skill's "
            "verdict-bearing safety_verdict must differ meaningfully across archetypes (2 flagships, "
            "an amplified-surface target, PLK1's pan-essential broad-tox control, HTR1D's "
            "thin-coverage abstention control) rather than collapsing to one constant reading."
        ),
        "roster_source": "eval/SCORECARD_PANEL_ROSTER.md",
        "capture_method": (
            "scorecard_adapter.py::_load_package -> skills/on-target-safety-liability/scripts/run.py "
            "--target <T> --indication <I>"
        ),
        "rows": rows,
        "checks": checks,
        "status_as_of": time.strftime("%Y-%m-%d", time.gmtime()),
    }
    if not all_present:
        missing = [f"{r['target']}/{r['indication']}" for r in rows if r["status"] == "PACKAGE_MISSING"]
        evidence["null_reason"] = (
            f"package(s) unavailable for {missing} (no cache, and a live run failed/timed out/lacked "
            "credentials) — left NULL rather than scoring a partial roster, per the issue's explicit "
            "instruction for panel_consistency when the full roster is absent."
        )
        evidence["packages_missing"] = missing
        return cs.Criterion(status=cs.NULL, evidence=evidence)
    return cs.Criterion(status=(cs.GREEN if checks["all_pass"] else cs.RED), evidence=evidence)


_NOT_BUILT_NOTE = (
    "not built for on-target-safety-liability: this skill has no exported source_properties / "
    "integrated_properties / l3d evidence-package sections (the SK#1941 grain tumor-presence's "
    "L2a/L2b/L3 rests on) and no L4 synthesis/decision-view layer — an architecture gap by design, "
    "not a defect. built=false; no criterion may be measured on an unbuilt layer."
)


def build_shard() -> cs.SkillShard:
    """Build the on-target-safety-liability scorecard shard in memory. Calls `collect_panel_rows()`
    live (via `_panel_consistency_criterion`), so re-running this script re-derives the panel
    evidence rather than replaying a stale table."""
    shard = cs.baseline_shard(SKILL)

    shard.cells["L1"] = cs.Cell(
        built=True,
        criteria={
            "accuracy": cs.Criterion(status=cs.NULL, evidence={"reason": _L1_ACCURACY_NULL_REASON}),
            "utilization": cs.Criterion(status=cs.GREEN, evidence=_L1_UTILIZATION_EVIDENCE),
            "fail_open": cs.Criterion(status=cs.GREEN, evidence=_L1_FAIL_OPEN_EVIDENCE),
            "panel_consistency": _panel_consistency_criterion(),
        },
        notes=(
            "L1 = run.py::CARDS + their field_disposition.yaml ledger. accuracy = NULL by design "
            "per #1990 (re-derivation is covered by the #1792/#1793/#1794 verification work, not "
            "this issue). fail_open re-asserts the #1792/#1793/#1794 open-world regression class "
            "with seeded teeth on the claim-record shadow."
        ),
    )

    for layer in ("L2a", "L2b", "L3", "L4"):
        shard.cells[layer] = cs.Cell(
            built=False,
            criteria={name: cs.Criterion(status=cs.NULL, evidence=None) for name in cs.CRITERIA},
            notes=_NOT_BUILT_NOTE,
        )

    return shard


def main() -> int:
    scorecard_dir = REPO_ROOT / cs.SCORECARD_DIRNAME
    shard = build_shard()
    path = cs.write_skill_shard(scorecard_dir, shard)
    print(f"[on-target-safety-liability scorecard adapter] wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
