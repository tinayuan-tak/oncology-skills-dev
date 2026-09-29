#!/usr/bin/env python
"""tumor-selectivity scorecard adapter (#1989) — copies the tumor-presence exemplar's shape
(A0c #1988, `skills/tumor-presence/scripts/scorecard_adapter.py`) for this skill.

Epic #1985's component scorecard (A0a, `_skills_common.component_scorecard`) records ONE cell per
``(skill x layer)`` with four independent criteria — accuracy / utilization / fail_open /
panel_consistency, each GREEN|RED|NULL — plus a cell-level ``built`` flag. This script is the ENTIRE
adapter write surface for tumor-selectivity: it builds the shard in memory and calls
``write_skill_shard``, which touches exactly ``scorecard/tumor-selectivity.json``.

## Layer mapping (this skill's own architecture)

Unlike tumor-presence, tumor-selectivity has NOT exported a SK#1941-style envelope
(``source_properties``/``integrated_properties``/``l3d``) — `run.py` composes 10 cards straight into
a headline/verdict with no named, reconstructable L2a/L2b/L3 section. Per the dispatch directive
("layers that don't exist for this skill = NOT_BUILT, never RED"), L2a/L2b/L3/L4 all carry
``built=False``:

  L1  — the 10 cards (2 verdict-driving: tumor-vs-normal-selectivity, modality-therapeutic-window,
        + sc-normal-celltype-expression normal-breadth veto instrument; the rest additive/display —
        see ``run.py`` CARDS comments) plus their disposition ledger
        (``field_disposition.yaml``, CI-enforced fleet-wide by
        ``skills/tests/test_field_disposition_ledgers.py``).
  L2a — NOT_BUILT: no exported source_properties section exists for this skill.
  L2b — NOT_BUILT: no exported integrated_properties / concordance-island section exists.
  L3  — NOT_BUILT: no l3d domain-interpretation story exists.
  L4  — NOT_BUILT: no synthesis/decision-view layer exists (mirrors tumor-presence's L4, out of
        scope for the whole reference-vertical wave per epic #1938).

## Criterion (a) accuracy = NULL by design

Per this issue's explicit directive: re-derivation is a SEPARATE issue (#2001) — do NOT fake it here.
L1 accuracy is left NULL with the reason recorded in evidence (no analysis-methods T3 raw-substrate
anchor has been wired into this shard yet); a fixture of already-derived values can never fail, so an
honest NULL beats a fabricated reconciliation.

## Panel-consistency is COMPUTED, not hand-typed (the teeth)

`collect_panel_rows()` mirrors tumor-presence's live computation: it loads (or live-emits + caches,
via `_load_package`) each of the 5 roster pairs' tumor-selectivity decision.json, extracts the
verdict-bearing card fields (dominant_direction/selectivity_class/comparator_concordance from
tumor-vs-normal-selectivity, therapeutic_window_class from modality-therapeutic-window), and computes
non-vacuity checks (classes aren't constant across the roster) plus `htr1d_matches_expected_archetype`
— the DGE-vertical-specific, APPLICABLE expectation for HTR1D per
`eval/SCORECARD_PANEL_ROSTER.md`'s per-skill x per-target table: a measured `strong_tumor_selective`,
concordant row, NOT a degraded one (issue #2070 diagnosis: HTR1D's thin-coverage/abstention
archetype lives in surface-modality-fit, not here).

## #2070 fix: the dead `dominant_direction` vs `selectivity_class` comparison

The original `thin_coverage_control_degrades` check compared `dominant_direction` (token space:
up/down/None) against a set of degraded-CLASS tokens (`data_unavailable`,
`discordant_across_comparators`, ...) — a comparison that could never fire, because
`dominant_direction` can never hold those values. `_is_degraded_selectivity_class()` fixes the
token-space mismatch by reading `selectivity_class` instead; `thin_coverage_control_degrades` is kept
as a DIAGNOSTIC field (not gated into `all_pass`) since degradation is not HTR1D's applicable
expectation in this vertical.
`skills/tumor-selectivity/tests/test_scorecard_shard.py` has mutation teeth for both: a doctored
(constant-class / all-missing) panel reds the applicable checks, AND a synthetic degraded-HTR1D row
proves `_is_degraded_selectivity_class`/`thin_coverage_control_degrades` CAN fire on the correct
field — RED-failing if the `dominant_direction` field-mismatch bug is reintroduced.

## Power/coverage grading = NULL with named blocker #1663

`n_tumor`/`n_adjacent` are stranded (`None`) panel-wide in this vintage (flagships included), so
there is zero power/coverage variation to grade a genuine power dimension on. `panel_consistency`
therefore reads NULL (never a fabricated GREEN) with `evidence["blocked_on"] == "#1663"` once the
applicable, measurable conjuncts all pass; it reads RED only if one of those applicable conjuncts
itself fails (a genuine defect, not a blocked dimension). Re-measure also owed at `#868`'s DGE
re-materialization.

NOTE ON PROVENANCE: as with tumor-presence, `eval/run_scorecard_panel.py --emit` (A0b #2000) times out
at 900s for the full `--full-package` fan-out (per #2030) — `_load_package` drives tumor-selectivity's
OWN, much lighter entrypoint directly (`scripts/run.py --target <T> --indication <I>`, no
`--full-package` fan-out).
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

SKILL = "tumor-selectivity"

# ── L1 evidence: accuracy / utilization / fail_open (test-backed, static evidence dicts) ──────────

_L1_ACCURACY_NULL_REASON = (
    "criterion (a) re-derivation is a SEPARATE issue (#2001) per this issue's explicit directive — "
    "do NOT fake it here. No analysis-methods T3 raw-substrate re-derivation anchor has been wired "
    "into this shard yet for any of tumor-selectivity's cards. Left NULL rather than fabricating a "
    "reconciliation against already-derived numbers (a fixture of derived values can never fail)."
)

_L1_UTILIZATION_EVIDENCE = {
    "method": (
        "field_disposition.yaml ledger: every emitted summary_field of tumor-selectivity's cards "
        "carries an explicit disposition (signal|context|provenance|display), mostly human-authored "
        "(reviewed: true on every row). Completeness (ledger == run.py CARDS' emitted summary_fields) "
        "and reader-reach for role:signal fields is enforced fleet-wide (not per-skill) by "
        "skills/tests/test_field_disposition_ledgers.py, which already lists 'tumor-selectivity' in "
        "its tracked skill set."
    ),
    "tests": [
        "skills/tests/test_field_disposition_ledgers.py::test_ledgered_skills_only_grow",
        "skills/tests/test_field_disposition_ledgers.py::test_every_ledger_is_wellformed",
        "skills/tests/test_field_disposition_ledgers.py::test_the_fleet_reach_measurement_is_not_vacuous",
        "skills/tests/test_field_disposition_ledgers.py::test_signal_fields_are_reader_reached_or_waived",
    ],
    "coverage": "field_disposition.yaml covers tumor-vs-normal-selectivity + the other 9 composed cards.",
    "status_as_of": "2026-09-28",
}

_L1_FAIL_OPEN_EVIDENCE = {
    "method": (
        "the shared open-world invariant (`_skills_common.claim_record`, 'ignorance != negation'): "
        "a data_unavailable/unreachable bucket forces state=unknown, direction=neutral, "
        "magnitude.level=none — never a manufactured directional finding. tumor-selectivity's "
        "`_claim_record` (run.py) feeds this same shared assembler."
    ),
    "tests": [
        "skills/tumor-selectivity/tests/test_claim_record_shadow.py"
        "::test_data_unavailable_is_open_world_noncommittal (ordinary path, pre-existing)",
        "skills/tumor-selectivity/tests/test_scorecard_l1_fail_open_probe.py"
        "::test_data_unavailable_degrades_conservatively_ordinary_path (ordinary path, re-asserted "
        "locally for this shard)",
        "skills/tumor-selectivity/tests/test_scorecard_l1_fail_open_probe.py"
        "::test_teeth_defeating_the_open_world_guard_lets_the_raw_token_leak (TEETH — monkeypatches "
        "claim_record.OPEN_WORLD_AVAILABILITY to frozenset() and shows finding.state leaks the raw "
        "'data_unavailable' token instead of 'unknown'; probe goes RED without the guard, GREEN with it)",
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
PANEL_CACHE_DIR = SKILL_DIR / "scripts" / ".panel_cache"  # gitignored; see .panel_cache/.gitignore

# Tokens that mean "this bucket's selectivity CLASS read as data-limited/degraded" — a
# `selectivity_class` token space (run.py's `tumor-vs-normal-selectivity` card summary), NOT a
# `dominant_direction` token space (which only ever holds up/down/None). #2070 diagnosis: the
# original comparison read `dominant_direction` against these tokens, which can never fire (a
# dead comparison — the field can never hold the values being tested for).
_DEGRADED_SELECTIVITY_CLASSES = frozenset(
    {"data_unavailable", "discordant_across_comparators", "not_informative", "insufficient"}
)


def _is_degraded_selectivity_class(selectivity_class: str | None) -> bool:
    """Token-space membership test (never a truthiness/identity shortcut) — kept as its own
    function so the #2070 mutation-teeth test can assert it fires on a synthetic degraded row."""
    return selectivity_class in _DEGRADED_SELECTIVITY_CLASSES


def _load_package(target: str, indication: str, *, timeout: int = 300) -> tuple[dict | None, str | None]:
    """Load tumor-selectivity's decision.json for one roster pair — from the on-disk cache if
    present, else a live run of this skill's OWN entrypoint (no --full-package fan-out; see module
    docstring for why). Returns (package_dict, source_str), or (None, None) if genuinely unavailable
    (no creds, live run failed/timed out) — absence is reported, never silently substituted."""
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
    verdict-bearing card classes, or PACKAGE_MISSING) plus non-vacuity checks over the roster."""
    rows: list[dict] = []
    for target, indication in ROSTER:
        pkg, source = _load_package(target, indication)
        if pkg is None:
            rows.append({"target": target, "indication": indication, "status": "PACKAGE_MISSING", "source": None})
            continue
        cards = {c["card_id"]: c.get("summary", {}) for c in pkg.get("cards", [])}
        tvn_summary = cards.get("tumor-vs-normal-selectivity", {})
        window_summary = cards.get("modality-therapeutic-window", {})
        card_data_unavailable = bool(tvn_summary.get("_live_read_error") or window_summary.get("_live_read_error"))
        rows.append(
            {
                "target": target,
                "indication": indication,
                "status": "OK",
                "source": source,
                "dominant_direction": tvn_summary.get("dominant_direction"),
                "selectivity_class": tvn_summary.get("selectivity_class"),
                "comparator_concordance": tvn_summary.get("comparator_concordance"),
                "therapeutic_window_class": window_summary.get("therapeutic_window_class"),
                "card_data_unavailable": card_data_unavailable,
                "card_data_unavailable_reason": (
                    tvn_summary.get("_live_read_error") or window_summary.get("_live_read_error")
                )
                if card_data_unavailable
                else None,
            }
        )

    ok_rows = [r for r in rows if r["status"] == "OK"]
    all_present = len(ok_rows) == len(ROSTER)
    # A package can be OK (decision.json produced) while its VERDICT-BEARING cards themselves
    # report a live-read error (e.g. this environment's credentials being ACCESS_DENIED on a
    # specific S3-backed derived product) — distinct from PACKAGE_MISSING. Such a row carries no
    # genuine signal; scoring it as a real constant-class reading would be a false RED (the
    # environment's access posture, not the skill's logic, is what's constant). All-unavailable
    # rows therefore drop the panel to NULL rather than a fabricated pass/fail.
    unavailable_rows = [r for r in ok_rows if r.get("card_data_unavailable")]
    all_card_data_unavailable = bool(ok_rows) and len(unavailable_rows) == len(ok_rows)
    scoreable_rows = [r for r in ok_rows if not r.get("card_data_unavailable")]
    direction_classes = {r.get("dominant_direction") for r in scoreable_rows} - {None}
    window_classes = {r.get("therapeutic_window_class") for r in scoreable_rows} - {None}

    htr1d = next((r for r in ok_rows if r["target"] == "HTR1D"), None)
    others = [r for r in ok_rows if r["target"] != "HTR1D"]
    # DIAGNOSTIC ONLY (#2070): whether HTR1D's selectivity_class reads as degraded relative to the
    # rest of the roster, using the FIXED token-space comparison (selectivity_class, not
    # dominant_direction — see _is_degraded_selectivity_class). This is NOT gated into all_pass:
    # per eval/SCORECARD_PANEL_ROSTER.md's per-skill x per-target stress-expectation table, HTR1D's
    # thin-coverage/abstention archetype lives in the surface-modality-fit vertical, NOT in
    # tumor-selectivity's DGE vertical, where HTR1D's tumor-vs-normal read is fully materialized and
    # genuinely strong/concordant. Coverage of an archetype stress is skill-relative; asserting
    # degradation here would assert an inapplicable clause (issue #2070 decision pt.1/pt.4).
    thin_coverage_control_degrades = False
    if htr1d is not None and others:
        htr1d_degraded = _is_degraded_selectivity_class(htr1d.get("selectivity_class"))
        others_not_degraded = any(not _is_degraded_selectivity_class(o.get("selectivity_class")) for o in others)
        thin_coverage_control_degrades = htr1d_degraded and others_not_degraded

    # APPLICABLE clause for tumor-selectivity's DGE vertical (issue #2070 decision pt.1): HTR1D's
    # expectation here is exactly a measured strong-selective row with concordant comparators — the
    # roster table's own per-skill entry for (HTR1D, tumor-selectivity). Comparator-discordance was
    # considered and REJECTED as the DGE-vertical thin-control discriminator (decision pt.4): it
    # fires on the EPCAM/KRAS flagships too (both discordant, 2/1 fam), so it cannot distinguish a
    # genuine control from the flagships.
    htr1d_matches_expected_archetype = bool(
        htr1d is not None
        and htr1d.get("selectivity_class") == "strong_tumor_selective"
        and htr1d.get("comparator_concordance") == "concordant"
    )

    checks = {
        "all_roster_rows_present": all_present,
        "direction_class_not_constant": len(direction_classes) > 1,
        "window_class_not_constant": len(window_classes) > 1,
        "htr1d_matches_expected_archetype": htr1d_matches_expected_archetype,
    }
    checks["all_pass"] = all(checks.values())
    checks["all_card_data_unavailable"] = all_card_data_unavailable
    # Diagnostic-only field, NOT part of all_pass — see comment above.
    checks["thin_coverage_control_degrades"] = thin_coverage_control_degrades
    return rows, checks


def _panel_consistency_criterion() -> cs.Criterion:
    rows, checks = collect_panel_rows()
    all_present = checks["all_roster_rows_present"]
    evidence = {
        "method": (
            "per-target rows across the whole 5-target roster (not one flagship), COMPUTED live by "
            "collect_panel_rows() (see module docstring) rather than hand-typed: tumor-selectivity's "
            "verdict-bearing card classes must differ meaningfully across archetypes (flagship "
            "surface, flagship intrinsic driver, amplified surface, pan-essential control) rather "
            "than collapsing to one constant reading. HTR1D's thin-coverage/abstention archetype "
            "lives in the surface-modality-fit vertical, NOT here (issue #2070 diagnosis + "
            "eval/SCORECARD_PANEL_ROSTER.md's per-skill x per-target table): in tumor-selectivity's "
            "DGE vertical, HTR1D's expectation is the OPPOSITE of degradation -- a measured "
            "strong_tumor_selective, concordant row, checked by htr1d_matches_expected_archetype. "
            "Coverage of an archetype stress is skill-relative; a global thin-coverage label applied "
            "to every skill was the root cause this issue fixes."
        ),
        "roster_source": "eval/SCORECARD_PANEL_ROSTER.md",
        "capture_method": (
            "scorecard_adapter.py::_load_package -> skills/tumor-selectivity/scripts/run.py "
            "--target <T> --indication <I> (direct, no --full-package fan-out; per #2030, "
            "eval/run_scorecard_panel.py --emit times out at 900s)"
        ),
        "rows": rows,
        "checks": checks,
        "status_as_of": time.strftime("%Y-%m-%d", time.gmtime()),
    }
    if not all_present:
        missing = [f"{r['target']}/{r['indication']}" for r in rows if r["status"] == "PACKAGE_MISSING"]
        evidence["null_reason"] = (
            f"package(s) unavailable for {missing} (no cache, and a live run failed/timed out/lacked "
            "credentials) — left NULL rather than scoring a partial roster."
        )
        evidence["packages_missing"] = missing
        return cs.Criterion(status=cs.NULL, evidence=evidence)
    if checks.get("all_card_data_unavailable"):
        unavailable = {
            f"{r['target']}/{r['indication']}": r.get("card_data_unavailable_reason")
            for r in rows
            if r.get("card_data_unavailable")
        }
        evidence["null_reason"] = (
            "the full 5-pair roster resolved a package for every target, but the two verdict-bearing "
            "cards (tumor-vs-normal-selectivity, modality-therapeutic-window) reported a live-read "
            "error for EVERY row in this environment — this credential context lacks S3 access to the "
            "underlying *-dge-tumor-vs-normal-sensitivity-v1 derived products (ACCESS_DENIED), not a "
            "genuine constant biological reading. Scoring a run this environment cannot actually reach "
            "would be a fabricated pass/fail, so panel_consistency is left NULL with this disposition "
            "rather than a false RED."
        )
        evidence["card_data_unavailable_by_target"] = unavailable
        return cs.Criterion(status=cs.NULL, evidence=evidence)
    # Power/coverage grading (issue #2070 decision pt.3): n_tumor/n_adjacent are stranded (None)
    # panel-wide in this vintage — flagships included — so there is zero power/coverage variation
    # to grade a genuine power dimension on. That dimension is structurally blocked on #1663, not
    # merely unmeasured today, so this criterion can never honestly reach GREEN until it lands (a
    # GREEN here would claim the panel exercises a power/coverage check it structurally cannot).
    # The measurable, APPLICABLE conjuncts (rows present, direction/window non-constancy, HTR1D's
    # skill-specific archetype match) are still scored: if any of those fail, that is a genuine
    # defect and the criterion reads RED; if they all pass, the honest state is NULL (not GREEN),
    # named against #1663. Re-measure also owed at #868's DGE re-materialization (n_tumor may
    # populate then and enable a real power dimension).
    evidence["blocked_on"] = "#1663"
    evidence["blocked_on_note"] = (
        "n_tumor/n_adjacent read None for every roster target in this vintage (flagships included) "
        "-- zero power/coverage variation exists to grade a genuine power dimension on. Blocked on "
        "#1663 (stranded n_tumor); re-measure also owed at #868's DGE re-materialization."
    )
    if not checks["all_pass"]:
        return cs.Criterion(status=cs.RED, evidence=evidence)
    evidence["null_reason"] = (
        "all measurable/applicable conjuncts pass (rows present; direction/window classes "
        "non-constant across the roster; HTR1D reads its tumor-selectivity-specific expectation -- "
        "a measured strong_tumor_selective, concordant row), but the power/coverage grading "
        "dimension is structurally blocked on #1663 -- left NULL rather than a GREEN the panel "
        "cannot structurally earn."
    )
    return cs.Criterion(status=cs.NULL, evidence=evidence)


# ── L2a / L2b / L3 / L4: all NOT_BUILT for this skill ──────────────────────────────────────────────

_NOT_BUILT_NOTES = {
    "L2a": (
        "L2a (source_properties) is NOT_BUILT: tumor-selectivity has not exported a SK#1941-style "
        "envelope section. run.py composes 10 cards straight into a headline/verdict with no named, "
        "reconstructable per-source export. Architecture gap, not a defect."
    ),
    "L2b": ("L2b (integrated_properties) is NOT_BUILT: no concordance-island section exists for this skill."),
    "L3": "L3 (l3d domain-interpretation story) is NOT_BUILT: no such section exists for this skill.",
    "L4": (
        "L4 (SYNTHESIS / decision views) is NOT_BUILT, mirroring tumor-presence's L4 — out of scope "
        "for the whole reference-vertical wave per epic #1938."
    ),
}


def build_shard() -> cs.SkillShard:
    """Build the tumor-selectivity scorecard shard in memory. Calls `collect_panel_rows()` live (via
    `_panel_consistency_criterion`), so re-running this script re-derives the panel evidence rather
    than replaying a stale table."""
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
            "L1 = tumor-selectivity's 10 composed cards (2 verdict-driving + sc-normal-celltype-"
            "expression normal-breadth veto instrument; the rest additive/verdict-inert display — "
            "see run.py CARDS comments). accuracy left NULL per this issue's directive "
            "(re-derivation is separate issue #2001)."
        ),
    )

    for layer in ("L2a", "L2b", "L3", "L4"):
        shard.cells[layer] = cs.Cell(
            built=False,
            criteria={name: cs.Criterion(status=cs.NULL, evidence=None) for name in cs.CRITERIA},
            notes=_NOT_BUILT_NOTES[layer],
        )

    return shard


def main() -> int:
    scorecard_dir = REPO_ROOT / cs.SCORECARD_DIRNAME
    shard = build_shard()
    path = cs.write_skill_shard(scorecard_dir, shard)
    print(f"[tumor-selectivity scorecard adapter] wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
