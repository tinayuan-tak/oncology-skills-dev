#!/usr/bin/env python
"""surface-modality-fit scorecard adapter (#1991) — copies the tumor-presence exemplar's shape
(#1988, A0c, the NORMATIVE example). This is the ENTIRE adapter write surface for surface-modality-fit:
it builds the shard in memory and calls ``write_skill_shard``, which touches exactly
``scorecard/surface-modality-fit.json``.

## Layer mapping

surface-modality-fit has NOT built the SK#1941-style EXPORTED evidence-package sections
(``source_properties`` / ``integrated_properties`` / ``l3d``) that tumor-presence's L2a/L2b/L3
grain rests on — a repo-wide grep for those section names under ``skills/surface-modality-fit/``
returns nothing. So here:

  L1  — the 9 cards (``run.py::CARDS``) + their disposition ledger (``field_disposition.yaml``,
        1489 rows, 79 role:signal, part of the fleet-wide floor enforced by
        ``skills/tests/test_field_disposition_ledgers.py``).
  L2a/L2b/L3/L4 — NOT_BUILT (``built=False``): this skill has no exported source_properties /
        integrated_properties / l3d sections, and no L4 synthesis/decision-view layer. An
        architecture gap by design (mirrors tumor-presence's own L4), not a defect — no criterion
        may be measured on an unbuilt layer.

## What "accuracy" means here (NULL by design, per the issue)

Criterion (a) re-derivation from raw substrate is explicitly a SEPARATE issue (#1991's own ask):
"do NOT fake it here: emit criterion (a) = NULL." A fixture of already-derived values can never
fail; an honest NULL beats a fake reconciliation. L1 accuracy is NULL with that reasoning recorded.

## Panel-consistency is COMPUTED, not hand-typed (the teeth)

`collect_panel_rows()` mirrors tumor-presence's `_load_package` pattern exactly: it drives THIS
skill's own light entrypoint (`scripts/run.py --target <T> --indication <I> --out <dir>`, no
--full-package fan-out) across the 5-target roster and extracts the two verdict-bearing headline
fields (`fit_class`, `surface_density_class` — both lifted onto `decision.json.headline`, not the
per-card summary), then asserts non-vacuity (classes aren't constant across the roster). Per #2030, the A0b
`eval/run_scorecard_panel.py --emit` harness times out on the full `--full-package` composition in
this environment — this adapter avoids that entirely by calling the skill's own entrypoint directly,
same as tumor-presence's documented workaround.

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
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from _skills_common import component_scorecard as cs  # noqa: E402

SKILL = "surface-modality-fit"

# ── L1 evidence: utilization / fail_open (test-backed, static evidence dicts) ──────────────────────

_L1_ACCURACY_NULL_REASON = (
    "criterion (a) re-derivation from raw substrate is a SEPARATE issue per #1991's own ask "
    "('do NOT fake it here: emit criterion (a) = NULL'). A fixture of already-derived values can "
    "never fail; left NULL rather than fabricating a reconciliation this adapter was not asked "
    "to build."
)

_L1_UTILIZATION_EVIDENCE = {
    "method": (
        "field_disposition.yaml ledger (1489 lines, 79 role:signal rows, 9 waived_because rows): "
        "every emitted summary_field carries an explicit disposition (signal|context|provenance|"
        "display). The fleet-wide guard (skills/tests/test_field_disposition_ledgers.py) enforces, "
        "once for every ledgered skill, that the declaration is well-formed and that every "
        "role:signal row is reader-reached or explicitly waived — surface-modality-fit is on the "
        "frozen LEDGERED_SKILLS_FLOOR (may never quietly lose its ledger)."
    ),
    "tests": [
        "skills/tests/test_field_disposition_ledgers.py::test_ledgered_skills_only_grow",
        "skills/tests/test_field_disposition_ledgers.py::test_every_ledger_is_wellformed",
        "skills/tests/test_field_disposition_ledgers.py::test_the_fleet_reach_measurement_is_not_vacuous",
        "skills/tests/test_field_disposition_ledgers.py::test_signal_fields_are_reader_reached_or_waived",
    ],
    "coverage": "surface-modality-fit ledgered (on LEDGERED_SKILLS_FLOOR); fleet-wide MIN_FLEET_SIGNAL_ROWS floor",
    "status_as_of": "2026-09-28",
}

_L1_FAIL_OPEN_EVIDENCE = {
    "method": (
        "the skill's own claim-record shadow builder (`run.py::_claim_record` -> "
        "`_skills_common.claim_record.assemble_claim_record`): `_sm_availability()` maps an "
        "unreachable/absent verdict token (data_unavailable/None) through this skill's own "
        "`_SM_OPEN_WORLD` set to availability='not_wired', which the shared assembler forces to "
        "state='unknown', direction='neutral', magnitude.level='none' — never a manufactured "
        "directional finding out of absence (the shared open-world invariant, "
        "'ignorance != negation')."
    ),
    "tests": [
        "skills/surface-modality-fit/tests/test_claim_record_shadow.py::test_data_unavailable_is_open_world "
        "(ordinary path, pre-existing)",
        "skills/surface-modality-fit/tests/test_scorecard_l1_fail_open_probe.py"
        "::test_data_unavailable_degrades_conservatively_ordinary_path (ordinary path, re-asserted "
        "locally for this shard)",
        "skills/surface-modality-fit/tests/test_scorecard_l1_fail_open_probe.py"
        "::test_teeth_defeating_the_open_world_guard_lets_the_raw_token_leak (TEETH — monkeypatches "
        "run.py::_SM_OPEN_WORLD to frozenset() and shows the record leaks the raw 'data_unavailable' "
        "token as a manufactured measured_positive finding instead of unknown/not_wired; probe goes "
        "RED without the guard, GREEN with it)",
    ],
    "status_as_of": "2026-09-28",
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
    """Load surface-modality-fit's decision.json for one roster pair — from the on-disk cache if
    present, else a live run of this skill's OWN entrypoint (no --full-package fan-out; per #2030,
    the A0b eval/run_scorecard_panel.py --emit harness times out at 900s on the full composition).
    Returns (package_dict, source_str), or (None, None) if genuinely unavailable — absence is
    reported, never silently substituted."""
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
    """The panel-consistency criterion's live computation: one row per roster pair (its two
    verdict-bearing card classes, or PACKAGE_MISSING) plus a non-vacuity check over the roster."""
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
                "fit_class": headline.get("fit_class"),
                "surface_density_class": headline.get("surface_density_class"),
            }
        )

    ok_rows = [r for r in rows if r["status"] == "OK"]
    all_present = len(ok_rows) == len(ROSTER)
    fit_classes = {r.get("fit_class") for r in ok_rows} - {None}

    checks = {
        "all_roster_rows_present": all_present,
        "fit_class_not_constant": len(fit_classes) > 1,
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
            "verdict-bearing fit_class must differ meaningfully across archetypes (flagship surface, "
            "flagship intrinsic driver, amplified surface, pan-essential control, thin-coverage "
            "abstention control) rather than collapsing to one constant reading."
        ),
        "roster_source": "eval/SCORECARD_PANEL_ROSTER.md",
        "capture_method": (
            "scorecard_adapter.py::_load_package -> skills/surface-modality-fit/scripts/run.py "
            "--target <T> --indication <I> (direct, no --full-package fan-out; per #2030, "
            "eval/run_scorecard_panel.py --emit times out for the full-package composition)"
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
    "not built for surface-modality-fit: this skill has no exported source_properties / "
    "integrated_properties / l3d evidence-package sections (the SK#1941 grain tumor-presence's "
    "L2a/L2b/L3 rests on) and no L4 synthesis/decision-view layer — an architecture gap by design, "
    "not a defect. built=false; no criterion may be measured on an unbuilt layer."
)


def build_shard() -> cs.SkillShard:
    """Build the surface-modality-fit scorecard shard in memory. Calls `collect_panel_rows()` live
    (via `_panel_consistency_criterion`), so re-running this script re-derives the panel evidence
    rather than replaying a stale table."""
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
            "L1 = the 9 cards (run.py::CARDS) + their field_disposition.yaml ledger. accuracy = NULL "
            "by design per #1991 (re-derivation is a separate issue). NOTE: PR#2033 (open, issue "
            "#2025) is adding a 10th card (cellline-surfaceome-abundance) to this skill's live "
            "composition — file-disjoint from this adapter (own scripts/scorecard_adapter.py + "
            "scorecard/surface-modality-fit.json only); this shard inventories main as-of "
            "2026-09-28 and does not race that PR."
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
    print(f"[surface-modality-fit scorecard adapter] wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
