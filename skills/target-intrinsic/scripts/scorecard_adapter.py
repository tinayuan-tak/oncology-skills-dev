#!/usr/bin/env python
"""target-intrinsic scorecard adapter (#1992) — inventory + disposition + fail-open probes, copying
the tumor-presence exemplar's shape (#1988, A0c, `skills/tumor-presence/scripts/scorecard_adapter.py`).

Epic #1985's component scorecard (A0a, `_skills_common.component_scorecard`) records ONE cell per
``(skill x layer)`` with four independent criteria — accuracy / utilization / fail_open /
panel_consistency, each GREEN|RED|NULL — plus a cell-level ``built`` flag. This script is the ENTIRE
adapter write surface for target-intrinsic: it builds the shard in memory and calls
``write_skill_shard``, which touches exactly ``scorecard/target-intrinsic.json``.

## Layer mapping (this skill's own architecture — NOT tumor-presence's)

target-intrinsic (v1.6.1, `DATA_PRODUCT.md`) is a DESCRIPTIVE, GATELESS dossier: ``verdict_fn=None``,
role ``descriptive``, ``polarity: not_scored`` — `headline_block.verdict.call` is always null by
design (that is a disposition fact recorded here, not a defect). Unlike tumor-presence, it exports NO
``source_properties``/``integrated_properties``/``l3d`` envelope section (no SK#1941-style
EXPORTED sections; `_skills_common.evidence_frame` is not wired into this skill's `run.py`):

  L1  — the 20 cards themselves (all `tier: target`, indication-independent): raw per-card
        measurements + their disposition ledger (`field_disposition.yaml`, fully human-reviewed).
  L2a/L2b/L3/L4 — NOT_BUILT. There is no exported source_properties/integrated_properties/l3d
        section to measure; this is an architecture-scope fact (this skill never built the
        evidence-property envelope), not an unmeasured gap.

## What "accuracy" means here (and why it is NULL, per the brief)

Criterion (a) re-derivation is explicitly OUT OF SCOPE for this issue (#1992) — it is issue #2003.
Per the shared directive ("leave a criterion NULL rather than fabricate a reading you cannot
support" — a fixture of DERIVED values can never fail), L1 accuracy is emitted NULL with that
reasoning recorded in evidence.

## Utilization — the ledger already exists and is fleet-enforced

target-intrinsic's `field_disposition.yaml` is `_meta.reviewed: true` for every row (a human read
every field's producers/consumers) and is validated + reach-checked by the SHARED fleet guard
`skills/tests/test_field_disposition_ledgers.py` (completeness vs `run.py` CARDS x summary_fields,
and reader-reach for every `role: signal` field, fleet-wide/blind to this skill's own ledger). This
adapter cites that existing, already-green suite rather than duplicating it.

## Fail-open — the real guard this skill's *_class panel rests on

target-intrinsic has no per-skill open-world claim-record shadow (that machinery is tumor-presence's
own `_claim_record`). Its equivalent guard is `_skills_common.subgroup_derivation.default_classify`:
every `*_class` token that reaches the `--figures` sub-group panel (`_TARGET_INTRINSIC_SUBGROUP_READER`
+ `make_value_classifier(_TARGET_INTRINSIC_VALUE_TIERS)`, see `run.py`) passes through it as the
fallback for any token the skill's own explicit tier map omits. `default_classify` checks
`_UNMEASURED_TOKENS` FIRST, so a coverage-gap token (`data_unavailable`, `not_assessed`, ...) degrades
to the off-axis `unmeasured` abstention rather than falling through the keyword scan to a manufactured
`absent`. `skills/target-intrinsic/tests/test_scorecard_l1_fail_open_probe.py` re-asserts the ordinary
path AND defeats `_UNMEASURED_TOKENS` (monkeypatched to `()`) to show the probe goes RED without the
guard — proving the guard, not something else, holds the conservative degrade.

## Panel-consistency is COMPUTED, not hand-typed (the teeth)

`collect_panel_rows()` runs target-intrinsic's OWN entrypoint (`scripts/run.py --target <T>`, no
`--indication`, no `--full-package` fan-out — this skill is indication-independent by design, see
DATA_PRODUCT.md) over the 5-target roster (`eval/SCORECARD_PANEL_ROSTER.md`) and checks that its two
claim-vector-projecting dossier fields (`tdl_class` = TRACTABILITY_PRECEDENT,
`modality_implication_class` = MODALITY_ROUTING) are not constant across the archetype-diverse roster,
plus that HTR1D (the roster's thin-coverage / non-oncology GPCR control) genuinely shows more
coverage-gap-shaped reads on the human-genetics-safety legs than the oncology targets — mirroring the
tumor-presence exemplar's thin-coverage-control check.

NOTE ON PROVENANCE: `eval/run_scorecard_panel.py --emit` (the A0b #2000 harness, target-profile's full
15-subskill `--full-package`) TIMED OUT at 900s for EPCAM/HTR1D per #2030/the tumor-presence adapter's
own finding — the full composition is too slow for that timeout on a richly- or thinly-covered target
alike. This adapter therefore drives target-intrinsic's OWN, much lighter entrypoint directly, same as
the tumor-presence exemplar.
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

SKILL = "target-intrinsic"

# ── L1 evidence: accuracy (NULL per brief) ─────────────────────────────────────────────────────────

_L1_ACCURACY_NULL_REASON = (
    "criterion (a) re-derivation is explicitly a SEPARATE issue (#2003), out of scope for #1992. Per "
    "the shared directive, an honest NULL beats a fake reconciliation — a fixture of derived values "
    "can never fail, so no accuracy reading is fabricated here."
)

# ── L1 evidence: utilization (test-backed; the fleet guard already covers this skill's ledger) ─────

_L1_UTILIZATION_EVIDENCE = {
    "method": (
        "field_disposition.yaml ledger: every emitted summary_field of all 20 cards carries an "
        "explicit role (signal|context|provenance|display), _meta.reviewed:true for every row (a "
        "human read each field's producers/consumers). Enforced FLEET-WIDE (blind to this skill's own "
        "ledger) by skills/tests/test_field_disposition_ledgers.py: completeness vs run.py CARDS x "
        "each card's summary_fields, non-vacuous reach measurement, and zero un-reached/un-waived "
        "role:signal fields. Only 2 of target-intrinsic's own fields (domain-modality-relevance "
        "modality_implication_class, target-development-level tdl_class) additionally project into "
        "this skill's OWN claim_vector; every other field's role:signal (where set) records that it "
        "feeds a claim/verdict elsewhere in the framework (this skill is gateless)."
    ),
    "tests": [
        "skills/tests/test_field_disposition_ledgers.py::test_ledgered_skills_only_grow",
        "skills/tests/test_field_disposition_ledgers.py::test_every_ledger_is_wellformed",
        "skills/tests/test_field_disposition_ledgers.py::test_the_fleet_reach_measurement_is_not_vacuous",
        "skills/tests/test_field_disposition_ledgers.py::test_signal_fields_are_reader_reached_or_waived",
    ],
    "coverage": "all 20 cards ledgered; every row reviewed:true (human-assigned, not auto-drafted).",
    "status_as_of": "2026-09-28",
}

# ── L1 evidence: fail_open (test-backed; the real guard the *_class panel rests on) ────────────────

_L1_FAIL_OPEN_EVIDENCE = {
    "method": (
        "the shared token-classification guard (`_skills_common.subgroup_derivation.default_classify`, "
        "the fallback of this skill's own make_value_classifier(_TARGET_INTRINSIC_VALUE_TIERS)): a "
        "coverage-gap token (data_unavailable/not_assessed/no_data/...) is checked against "
        "_UNMEASURED_TOKENS FIRST and forced to the off-axis `unmeasured` abstention — never falls "
        "through the keyword scan to a manufactured `absent` (a measured negative)."
    ),
    "tests": [
        "skills/target-intrinsic/tests/test_scorecard_l1_fail_open_probe.py"
        "::test_data_unavailable_degrades_conservatively_ordinary_path (ordinary path)",
        "skills/target-intrinsic/tests/test_scorecard_l1_fail_open_probe.py"
        "::test_teeth_defeating_the_unmeasured_token_guard_leaks_a_fabricated_absent (TEETH — "
        "monkeypatches _UNMEASURED_TOKENS to () and shows default_classify('data_unavailable') leaks "
        "'absent' instead of 'unmeasured'; probe goes RED without the guard, GREEN with it)",
    ],
    "status_as_of": "2026-09-28",
}

# ── L1 panel_consistency: COMPUTED live from real per-target packages ──────────────────────────────

# target-intrinsic is indication-INDEPENDENT (tier:target cards; --indication optional/ignored) — the
# roster is targets only, drawn from the same eval/SCORECARD_PANEL_ROSTER.md 5-target set.
ROSTER: tuple[str, ...] = ("EPCAM", "KRAS", "ERBB2", "PLK1", "HTR1D")

RUN_PY = SKILL_DIR / "scripts" / "run.py"
PANEL_CACHE_DIR = SKILL_DIR / "scripts" / ".panel_cache"  # gitignored; see .panel_cache/.gitignore

# Coverage-gap-shaped tokens on the human-genetics-safety legs — used to check the thin-coverage /
# non-oncology GPCR control (HTR1D) genuinely reads MORE data-limited than the oncology roster.
_GAP_TOKENS = frozenset({"data_unavailable", "insufficient", "unknown", "no_phenotype", "not_assessed"})


def _load_package(target: str, *, timeout: int = 300) -> tuple[dict | None, str | None]:
    """Load target-intrinsic's decision.json for one roster target — from the on-disk cache if
    present, else a live run of this skill's OWN entrypoint (no --full-package fan-out; see module
    docstring for why). Returns (package_dict, source_str), or (None, None) if genuinely unavailable
    (no creds, live run failed/timed out) — absence is reported, never silently substituted."""
    dest = PANEL_CACHE_DIR / target
    cached = dest / "decision.json"
    if cached.exists():
        try:
            return json.loads(cached.read_text()), str(cached.relative_to(REPO_ROOT))
        except (OSError, json.JSONDecodeError):
            pass
    dest.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(
            [sys.executable, str(RUN_PY), "--target", target, "--out", str(dest)],
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
    """The panel-consistency criterion's live computation: one row per roster target (its two
    claim-vector-projecting dossier fields + a human-genetics-safety gap tally, or PACKAGE_MISSING)
    plus non-vacuity checks over the roster."""
    rows: list[dict] = []
    for target in ROSTER:
        pkg, source = _load_package(target)
        if pkg is None:
            rows.append({"target": target, "status": "PACKAGE_MISSING", "source": None})
            continue
        h = pkg.get("headline", {}) or {}
        safety_fields = [
            h.get("gnomad_constraint_class"),
            h.get("gene_burden_safety_class"),
            h.get("clinvar_pathogenic_class"),
            h.get("clingen_dosage_class"),
            h.get("impc_ko_phenotype_class"),
            h.get("mouse_ko_phenotype_class"),
        ]
        n_gap = sum(1 for v in safety_fields if str(v) in _GAP_TOKENS)
        rows.append(
            {
                "target": target,
                "status": "OK",
                "source": source,
                "tdl_class": h.get("tdl_class"),
                "modality_implication_class": h.get("modality_implication_class"),
                "n_safety_legs_gap_shaped": n_gap,
                "n_safety_legs_measured": len(safety_fields),
            }
        )

    ok_rows = [r for r in rows if r["status"] == "OK"]
    all_present = len(ok_rows) == len(ROSTER)
    tdl_classes = {r.get("tdl_class") for r in ok_rows} - {None}
    modality_classes = {r.get("modality_implication_class") for r in ok_rows} - {None}

    htr1d = next((r for r in ok_rows if r["target"] == "HTR1D"), None)
    others = [r for r in ok_rows if r["target"] != "HTR1D"]
    thin_coverage_control_degrades = False
    if htr1d is not None and others:
        htr1d_gap = htr1d.get("n_safety_legs_gap_shaped", 0)
        mean_other_gap = sum(o.get("n_safety_legs_gap_shaped", 0) for o in others) / len(others)
        thin_coverage_control_degrades = htr1d_gap > mean_other_gap

    checks = {
        "all_roster_rows_present": all_present,
        "tdl_class_not_constant": len(tdl_classes) > 1,
        "modality_implication_class_not_constant": len(modality_classes) > 1,
        "thin_coverage_control_degrades": thin_coverage_control_degrades,
    }
    checks["all_pass"] = all(checks.values())
    return rows, checks


def _panel_consistency_criterion() -> cs.Criterion:
    rows, checks = collect_panel_rows()
    all_present = checks["all_roster_rows_present"]
    evidence = {
        "method": (
            "per-target rows across the whole 5-target roster (not one flagship), COMPUTED live by "
            "collect_panel_rows() (see module docstring) rather than hand-typed: target-intrinsic's "
            "two claim-vector-projecting dossier fields (tdl_class=TRACTABILITY_PRECEDENT, "
            "modality_implication_class=MODALITY_ROUTING) must differ meaningfully across archetypes "
            "(flagship surface, flagship intrinsic driver, amplified surface, pan-essential control, "
            "thin-coverage/non-oncology control) rather than collapsing to one constant reading, and "
            "the thin-coverage control (HTR1D, a non-oncology GPCR) must show more coverage-gap-shaped "
            "human-genetics-safety reads than the oncology-roster mean."
        ),
        "roster_source": "eval/SCORECARD_PANEL_ROSTER.md",
        "capture_method": (
            "scorecard_adapter.py::_load_package -> skills/target-intrinsic/scripts/run.py "
            "--target <T> (direct, no --indication [this skill is indication-independent], no "
            "--full-package fan-out; eval/run_scorecard_panel.py --emit timed out at 900s for "
            "EPCAM/HTR1D per #2030 in this environment)"
        ),
        "rows": rows,
        "checks": checks,
        "status_as_of": time.strftime("%Y-%m-%d", time.gmtime()),
    }
    if not all_present:
        missing = [r["target"] for r in rows if r["status"] == "PACKAGE_MISSING"]
        evidence["null_reason"] = (
            f"package(s) unavailable for {missing} (no cache, and a live run failed/timed out/lacked "
            "credentials) — left NULL rather than scoring a partial roster."
        )
        evidence["packages_missing"] = missing
        return cs.Criterion(status=cs.NULL, evidence=evidence)
    return cs.Criterion(status=(cs.GREEN if checks["all_pass"] else cs.RED), evidence=evidence)


# ── L2a / L2b / L3 / L4 — none of this envelope is built for this skill (architecture gap) ─────────

_NOT_BUILT_NOTE = (
    "target-intrinsic exports NO source_properties/integrated_properties/l3d envelope section "
    "(no _skills_common.evidence_frame wiring in run.py, unlike tumor-presence's SK#1941/#1940 "
    "sections) — an architecture-scope fact, not an unmeasured gap. built=false; no criterion may be "
    "measured on an unbuilt layer."
)


def build_shard() -> cs.SkillShard:
    """Build the target-intrinsic scorecard shard in memory. Calls `collect_panel_rows()` live (via
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
            "L1 = the 20 cards (all tier:target, indication-independent). target-intrinsic is "
            "DESCRIPTIVE/GATELESS (verdict_fn=None, role:descriptive, polarity:not_scored) — "
            "headline_block.verdict.call is always null by design, a disposition fact recorded here, "
            "not a defect. accuracy NULL per brief (re-derivation is issue #2003)."
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
    print(f"[target-intrinsic scorecard adapter] wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
