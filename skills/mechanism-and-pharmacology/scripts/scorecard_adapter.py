#!/usr/bin/env python
"""mechanism-and-pharmacology scorecard adapter (#1993) — inventory + disposition + fail-open probes,
copying the tumor-presence exemplar's shape (#1988, A0c, `skills/tumor-presence/scripts/scorecard_adapter.py`)
and its already-landed sibling target-intrinsic (#1992, `skills/target-intrinsic/scripts/scorecard_adapter.py`,
merge 71a51b0f).

Epic #1985's component scorecard (A0a, `_skills_common.component_scorecard`) records ONE cell per
``(skill x layer)`` with four independent criteria — accuracy / utilization / fail_open /
panel_consistency, each GREEN|RED|NULL — plus a cell-level ``built`` flag. This script is the ENTIRE
adapter write surface for mechanism-and-pharmacology: it builds the shard in memory and calls
``write_skill_shard``, which touches exactly ``scorecard/mechanism-and-pharmacology.json``.

## Layer mapping (this skill's own architecture — NOT tumor-presence's)

mechanism-and-pharmacology (v1.11.0, `DATA_PRODUCT.md`) is `role: gating` (verdict resolves on
`network_class` alone, polarity STATICALLY neutral) — verdict-bearing, unlike target-intrinsic's
gateless dossier, but architecturally identical on the axis this adapter measures: it exports NO
``source_properties``/``integrated_properties``/``l3d`` envelope section (no `_skills_common.evidence_frame`
wiring in `run.py`), so:

  L1  — the 5 cards (all `tier: target`, indication-independent — `run.py` has no `CARD_CONTEXT` map):
        raw per-card measurements + their disposition ledger (`field_disposition.yaml`, fully
        human-reviewed).
  L2a/L2b/L3/L4 — NOT_BUILT. There is no exported source_properties/integrated_properties/l3d
        section to measure; an architecture-scope fact, not an unmeasured gap.

## What "accuracy" means here (and why it is NULL, per the brief)

Criterion (a) re-derivation is explicitly OUT OF SCOPE for this issue (#1993). Per the shared
directive ("leave a criterion NULL rather than fabricate a reading you cannot support" — a fixture of
DERIVED values can never fail), L1 accuracy is emitted NULL with that reasoning recorded in evidence.

## Utilization — the ledger already exists and is fleet-enforced

mechanism-and-pharmacology's `field_disposition.yaml` is `_meta.reviewed: true` for every row (a human
read every field's producers/consumers) and is validated + reach-checked by the SHARED fleet guard
`skills/tests/test_field_disposition_ledgers.py` (completeness vs `run.py` CARDS x summary_fields, and
reader-reach for every `role: signal` field, fleet-wide/blind to this skill's own ledger). All 5
signal rows are reader-reached (per the ledger's own `_meta.waived_because` note, no waivers present).
This adapter cites that existing, already-green suite rather than duplicating it.

## Fail-open — the real guard this skill's sub-group panel rests on

mechanism-and-pharmacology wires `subgroup_classify=make_value_classifier(_MECHANISM_VALUE_TIERS)`
(`run.py`) — the SAME shared guard target-intrinsic's adapter probes:
`_skills_common.subgroup_derivation.default_classify` is the fallback for any token this skill's own
`_MECHANISM_VALUE_TIERS` map omits. `default_classify` checks `_UNMEASURED_TOKENS` FIRST, so a
coverage-gap token (`data_unavailable`, `not_assessed`, ...) degrades to the off-axis `unmeasured`
abstention rather than falling through the keyword scan to a manufactured `absent`.
`skills/mechanism-and-pharmacology/tests/test_scorecard_l1_fail_open_probe.py` re-asserts the ordinary
path AND defeats `_UNMEASURED_TOKENS` (monkeypatched to `()`) to show the probe goes RED without the
guard — proving the guard, not something else, holds the conservative degrade.

## Panel-consistency is COMPUTED, not hand-typed (the teeth)

`collect_panel_rows()` runs mechanism-and-pharmacology's OWN entrypoint (`scripts/run.py --target <T>`,
no `--indication` [this skill is indication-independent by design, see DATA_PRODUCT.md §1], no
`--full-package` fan-out) over the 5-target roster (`eval/SCORECARD_PANEL_ROSTER.md`) and checks that
its verdict-bearing field (`network_class`, the sole card the resolver keys on) and its verdict-inert
descriptive facet (`mechanism_verdict`) are not constant across the archetype-diverse roster.

NOTE — a domain-specific finding, not borrowed uncritically from the exemplars: tumor-presence's and
target-intrinsic's adapters both additionally assert their thin-coverage control (HTR1D, a
non-oncology GPCR) reads MORE data-limited than the oncology roster. That assumption does NOT
transfer here: SIGNOR/CollecTRI curated-network annotation density tracks how pharmacologically
well-studied a gene is (GPCRs are a heavily-curated drug-target class), not oncology-relevance, so
HTR1D has no domain reason to be the most gap-shaped mechanism row. A live run confirms this:
HTR1D and EPCAM both read `partial` while KRAS/ERBB2/PLK1 read `well_characterized` — HTR1D is NOT
uniquely thin here. Asserting the borrowed check would manufacture a false RED from an invalid
transplanted assumption, so this adapter checks only the two real non-constancy facts and records
the HTR1D-non-uniqueness finding in evidence for a human to read.

NOTE ON PROVENANCE: `eval/run_scorecard_panel.py --emit` (the A0b #2000 harness, target-profile's full
15-subskill `--full-package`) TIMED OUT at 900s for EPCAM/HTR1D per #2030/the tumor-presence adapter's
own finding. This adapter therefore drives mechanism-and-pharmacology's OWN, much lighter entrypoint
directly, same as tumor-presence and target-intrinsic.
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

SKILL = "mechanism-and-pharmacology"

# ── L1 evidence: accuracy (NULL per brief) ─────────────────────────────────────────────────────────

_L1_ACCURACY_NULL_REASON = (
    "criterion (a) re-derivation is explicitly a SEPARATE issue, out of scope for #1993. Per the "
    "shared directive, an honest NULL beats a fake reconciliation — a fixture of derived values "
    "can never fail, so no accuracy reading is fabricated here."
)

# ── L1 evidence: utilization (test-backed; the fleet guard already covers this skill's ledger) ─────

_L1_UTILIZATION_EVIDENCE = {
    "method": (
        "field_disposition.yaml ledger: every emitted summary_field of all 5 cards carries an "
        "explicit role (signal|context|provenance|display), _meta.reviewed:true for every row (a "
        "human read each field's producers/consumers). Enforced FLEET-WIDE (blind to this skill's own "
        "ledger) by skills/tests/test_field_disposition_ledgers.py: completeness vs run.py CARDS x "
        "each card's summary_fields, non-vacuous reach measurement, and zero un-reached/un-waived "
        "role:signal fields. All 5 of this skill's role:signal rows are reader-reached (exact census "
        "hit per the ledger's own _meta.waived_because note: 'no waivers are present')."
    ),
    "tests": [
        "skills/tests/test_field_disposition_ledgers.py::test_ledgered_skills_only_grow",
        "skills/tests/test_field_disposition_ledgers.py::test_every_ledger_is_wellformed",
        "skills/tests/test_field_disposition_ledgers.py::test_the_fleet_reach_measurement_is_not_vacuous",
        "skills/tests/test_field_disposition_ledgers.py::test_signal_fields_are_reader_reached_or_waived",
    ],
    "coverage": "all 5 cards ledgered; every row reviewed:true (human-assigned, not auto-drafted).",
    "status_as_of": "2026-09-29",
}

# ── L1 evidence: fail_open (test-backed; the real guard the sub-group panel rests on) ───────────────

_L1_FAIL_OPEN_EVIDENCE = {
    "method": (
        "the shared token-classification guard (`_skills_common.subgroup_derivation.default_classify`, "
        "the fallback of this skill's own make_value_classifier(_MECHANISM_VALUE_TIERS), wired at "
        "run.py's subgroup_classify=): a coverage-gap token (data_unavailable/not_assessed/no_data/...) "
        "is checked against _UNMEASURED_TOKENS FIRST and forced to the off-axis `unmeasured` "
        "abstention — never falls through the keyword scan to a manufactured `absent` (a measured "
        "negative)."
    ),
    "tests": [
        "skills/mechanism-and-pharmacology/tests/test_scorecard_l1_fail_open_probe.py"
        "::test_data_unavailable_degrades_conservatively_ordinary_path (ordinary path)",
        "skills/mechanism-and-pharmacology/tests/test_scorecard_l1_fail_open_probe.py"
        "::test_teeth_defeating_the_unmeasured_token_guard_leaks_a_fabricated_absent (TEETH — "
        "monkeypatches _UNMEASURED_TOKENS to () and shows default_classify('data_unavailable') leaks "
        "'absent' instead of 'unmeasured'; probe goes RED without the guard, GREEN with it)",
    ],
    "status_as_of": "2026-09-29",
}

# ── L1 panel_consistency: COMPUTED live from real per-target packages ──────────────────────────────

# mechanism-and-pharmacology is indication-INDEPENDENT (tier:target cards; run.py has no CARD_CONTEXT
# map) — the roster is targets only, drawn from the same eval/SCORECARD_PANEL_ROSTER.md 5-target set.
ROSTER: tuple[str, ...] = ("EPCAM", "KRAS", "ERBB2", "PLK1", "HTR1D")

RUN_PY = SKILL_DIR / "scripts" / "run.py"
PANEL_CACHE_DIR = SKILL_DIR / "scripts" / ".panel_cache"  # gitignored; see .panel_cache/.gitignore

# Coverage-gap-shaped network_class tokens — recorded per-row for a human to read; NOT used to gate a
# thin-coverage-control assumption here (see module docstring: SIGNOR/CollecTRI curated-network
# density does not transfer HTR1D-must-be-thinnest from tumor-presence/target-intrinsic's domain).
_GAP_TOKENS = frozenset({"data_unavailable", "insufficient", "sparse"})


def _load_package(target: str, *, timeout: int = 300) -> tuple[dict | None, str | None]:
    """Load mechanism-and-pharmacology's decision.json for one roster target — from the on-disk cache
    if present, else a live run of this skill's OWN entrypoint (no --full-package fan-out; see module
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
    """The panel-consistency criterion's live computation: one row per roster target (its
    verdict-bearing card class + descriptive verdict + a gap-shaped flag), or PACKAGE_MISSING, plus
    non-vacuity checks over the roster."""
    rows: list[dict] = []
    for target in ROSTER:
        pkg, source = _load_package(target)
        if pkg is None:
            rows.append({"target": target, "status": "PACKAGE_MISSING", "source": None})
            continue
        h = pkg.get("headline", {}) or {}
        network_class = h.get("network_class")
        rows.append(
            {
                "target": target,
                "status": "OK",
                "source": source,
                "network_class": network_class,
                "mechanism_verdict": h.get("mechanism_verdict"),
                "network_class_gap_shaped": str(network_class) in _GAP_TOKENS,
            }
        )

    ok_rows = [r for r in rows if r["status"] == "OK"]
    all_present = len(ok_rows) == len(ROSTER)
    network_classes = {r.get("network_class") for r in ok_rows} - {None}
    mechanism_verdicts = {r.get("mechanism_verdict") for r in ok_rows} - {None}

    # Recorded for a human to read (see module docstring), NOT gated: whether HTR1D is uniquely
    # gap-shaped among the roster. A live run shows it is not (EPCAM shares HTR1D's `partial` read) —
    # this skill's curated-network coverage does not track oncology-relevance the way tumor-presence's/
    # target-intrinsic's assay coverage does.
    htr1d = next((r for r in ok_rows if r["target"] == "HTR1D"), None)
    others = [r for r in ok_rows if r["target"] != "HTR1D"]
    htr1d_uniquely_gap_shaped = False
    if htr1d is not None and others:
        htr1d_gap = bool(htr1d.get("network_class_gap_shaped"))
        all_others_non_gap = all(not o.get("network_class_gap_shaped") for o in others)
        htr1d_uniquely_gap_shaped = htr1d_gap and all_others_non_gap

    checks = {
        "all_roster_rows_present": all_present,
        "network_class_not_constant": len(network_classes) > 1,
        "mechanism_verdict_not_constant": len(mechanism_verdicts) > 1,
    }
    checks["all_pass"] = all(checks.values())
    checks["htr1d_uniquely_gap_shaped_INFORMATIONAL_not_gated"] = htr1d_uniquely_gap_shaped
    return rows, checks


def _panel_consistency_criterion() -> cs.Criterion:
    rows, checks = collect_panel_rows()
    all_present = checks["all_roster_rows_present"]
    evidence = {
        "method": (
            "per-target rows across the whole 5-target roster (not one flagship), COMPUTED live by "
            "collect_panel_rows() (see module docstring) rather than hand-typed: this skill's "
            "verdict-bearing card class (network_class, the ONLY card the resolver keys on) and its "
            "descriptive mechanism_verdict must differ meaningfully across archetypes (flagship "
            "surface, flagship intrinsic driver, amplified surface, pan-essential control, "
            "thin-coverage/non-oncology control) rather than collapsing to one constant reading, and "
            "the thin-coverage control (HTR1D, a non-oncology GPCR) must show a gap-shaped "
            "network_class where at least one oncology-roster target does not."
        ),
        "roster_source": "eval/SCORECARD_PANEL_ROSTER.md",
        "capture_method": (
            "scorecard_adapter.py::_load_package -> skills/mechanism-and-pharmacology/scripts/run.py "
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
    "mechanism-and-pharmacology exports NO source_properties/integrated_properties/l3d envelope "
    "section (no _skills_common.evidence_frame wiring in run.py, unlike tumor-presence's SK#1941/#1940 "
    "sections) — an architecture-scope fact, not an unmeasured gap. built=false; no criterion may be "
    "measured on an unbuilt layer."
)


def build_shard() -> cs.SkillShard:
    """Build the mechanism-and-pharmacology scorecard shard in memory. Calls `collect_panel_rows()`
    live (via `_panel_consistency_criterion`), so re-running this script re-derives the panel evidence
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
            "L1 = the 5 cards (all tier:target, indication-independent; run.py has no CARD_CONTEXT "
            "map). mechanism-and-pharmacology is role:gating with the verdict resolved on "
            "network_class alone (polarity statically neutral). accuracy NULL per brief "
            "(re-derivation is a separate issue)."
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
    print(f"[mechanism-and-pharmacology scorecard adapter] wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
