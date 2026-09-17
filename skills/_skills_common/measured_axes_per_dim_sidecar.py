#!/usr/bin/env python3
"""measured_axes_per_dim_sidecar.py — publish per-dim axis MEASURABILITY as a committed feed.

Dimension 3 of 3 of the framework-health visibility layer, after `descriptor_coverage.json`
(dim 1) and `field_read_health.json` (dim 2). The question it makes visible: *for each of the
six governance dims, how many of its axes can measure anything at all* — asked of the framework's
own declarations, before any target is run.

WHY A STATIC ARTIFACT, AND WHY THE PLAN THIS REPLACES DOES NOT WORK
-------------------------------------------------------------------
The obvious design was for the target-contracts dashboard to read the PER-RUN projection
`risk_projection.evidence_coverage_by_axis` / `_by_dim` straight out of committed evidence
packages. MEASURED 2026-09-17 and it cannot: the consumer's `products` root holds 4 committed
`evidence_package.json` files, all 4 carry only `cards`, `synthesis.skill_reports` is EMPTY on
all 4, and the string `evidence_coverage` appears in none of them. The join key that projection
needs (`skill_reports[axis].provenance.cards_used`) is not in the bytes any repo commits. The
corpus numbers behind that projection (4536 axis-runs over 504 packages) are real, but they live
in a CORPUS RUN — a different aperture from the one the dashboard can reach.

So this publishes the half that IS computable from committed source: the STATIC one. Same hop
that makes dims 1 and 2 populated instead of hostage to whichever bytes a downstream repo last
committed.

CAPABILITY IS NOT OUTCOME — the single most important reading note
------------------------------------------------------------------
This artifact answers "does an instrument EXIST for this axis" (capability, from declarations).
`evidence_coverage_by_axis` answers "did this run measure anything" (outcome, from data). They
are ORTHOGONAL, and the state names here are deliberately DISJOINT from
`risk_projection.COVERAGE_STATES` so no consumer can reconcile the wrong pair — the same trap
dim 2 hit when a static classification and a per-run emission outcome were nearly collapsed.

They can disagree, and one axis DOES disagree today. `translational_readiness` is
`descriptor_covered` here while the 504-target corpus measured it `undescribed` on 504/504 runs.
BOTH are correct: 1 of its 4 declared types (`crispr_lof_dependency`) carries measurement
descriptors, which is enough for capability, while no field emitted by its RESOLVED cards matched
a measurement descriptor on any run. Do NOT read this artifact as a prediction of per-run
coverage, and do not "fix" either side to make them agree.

READ THE PER-TYPE RATIO, NOT THE PER-AXIS FLAG
----------------------------------------------
The per-axis flag reads `descriptor_covered` on 14 of 15 fan-out axes — a metric pinned near
100% because it measures the direction already finished (any one covered type is enough). The
live signal is per TYPE: 62 of 123 declared measurement_types carry NO measurement descriptor at
all. That queue is the reason this dimension is worth a dashboard row, and it is why
`types_without_measurement_descriptor` is published per axis and per dim rather than summarised.

DECLARED, NOT DERIVED — AND THAT IS THE CONSUMER'S HALF OF THE JOB
------------------------------------------------------------------
The axis→measurement_type edge here comes from each SKILL.md's
`composition.measurement_types_pulled`, which is a SELF-DECLARED list that has drifted from
`cards_used` before (four skills at once in the 2026-08-14 sweep, which is why
`test_measurement_types_resolver.py` exists). `probe.py`'s standing contract is that probes never
trust a self-declaration, so this must be RECONCILED against the card→measurement_type back-ref
— and that back-ref lives in target-contracts (`vocabularies/measurement_types.yaml`;
`measurement_types.py` resolves it from the SIBLING repo). A skills-only checkout cannot read it,
so computing the reconcile HERE would make this producer's `--check` fail in skills CI, which is
exactly the cross-repo PR gate the framework-health handoff forbids.

Hence the repo-ownership split: skills publishes what skills owns (`declared_types_by_axis` +
`cards_by_axis` + descriptor coverage), and target-contracts — which owns the registry — derives
each card's type and reports the drift. Measured on this host 2026-09-17 with the sibling present:
the two routes agree on STATE for 15 of 15 axes, and differ in TYPE SET for exactly one,
`surface_modality` (21 declared vs 22 card-derived, with `surfaceome-cohort-ranking` carrying no
registry back-ref). That is a DATED measurement of a state this artifact cannot verify — treat it
as a cache and re-measure downstream, never as a pinned fact.

NO `generated_at`, AND THEREFORE NO STABLE PROJECTION
-----------------------------------------------------
Every input is committed source (two module constants, two AST literals, 15 SKILL.md
frontmatters). Nothing is volatile, so `--check` compares the WHOLE document. Do not add a
timestamp: it would be the only volatile field and would force a projection that weakens every
other field's guard. Same rule as `descriptor_coverage_sidecar`.

Usage:
  python -m _skills_common.measured_axes_per_dim_sidecar          # write measured_axes_per_dim.json
  python -m _skills_common.measured_axes_per_dim_sidecar --check  # fail if the committed file is stale
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

from _skills_common import field_descriptor
from _skills_common.narrator_lenses import LENSES
from _skills_common.report_render.ir import _CONTEXT_DIM
from _skills_common.risk_projection import (
    AXIS_DIM_EXCLUSIONS,
    AXIS_TO_DIM,
    COVERAGE_ONLY_AXES,
    MEASUREMENT_ROLES,
    NON_MEASUREMENT_ROLES,
)

SKILLS_DIR = Path(__file__).resolve().parents[1]  # .../skills
_OUT = SKILLS_DIR / "_skills_common" / "measured_axes_per_dim.json"
TP_FANOUT = SKILLS_DIR / "target-profile" / "scripts" / "tp_fanout.py"

SCHEMA_VERSION = "1.0.0"

# STATIC states. Deliberately DISJOINT from `risk_projection.COVERAGE_STATES` (measured /
# unmeasured / undescribed / absent): those are per-RUN outcomes, these are declaration-time
# capability. `test_static_states_are_disjoint_from_per_run_coverage_states` pins the disjointness
# so the two vocabularies cannot converge by accident later.
STATE_DESCRIPTOR_COVERED = "descriptor_covered"  # >=1 declared type carries a MEASUREMENT descriptor
STATE_DESCRIPTOR_BLIND = "descriptor_blind"  # types declared, NONE descriptor-covered -> instrument gap
STATE_NO_DECLARED_TYPES = "no_declared_types"  # a fan-out skill declaring no measurement_types_pulled
STATE_NOT_A_FANOUT_AXIS = "not_a_fanout_axis"  # no skill dir: card-fed pseudo-dim, or composed inline
STATIC_STATES: frozenset = frozenset(
    {STATE_DESCRIPTOR_COVERED, STATE_DESCRIPTOR_BLIND, STATE_NO_DECLARED_TYPES, STATE_NOT_A_FANOUT_AXIS}
)


def _fanout_roster() -> dict[str, str]:
    """`{axis_short: skill_dir}` from target-profile's own `SUB_SKILLS` literal, via ast.

    Read by ast rather than imported for the reason `test_axis_dim_mapping_completeness` gives:
    importing `tp_fanout` drags in the whole fan-out. RAISES when the literal is not found —
    never returns `{}`. That is not defensive habit, it is the exact defect this dimension's own
    PR fixed on the consumer side (target-contracts #795): the same literal was read from
    `run.py` after it moved to `tp_fanout.py`, and because a missing file and an unmapped axis
    both yield a falsy result, three artifact fields read `None` on 22 of 22 skills for weeks
    with nothing red. A producer that publishes a silently empty roster is that bug again.
    """
    tree = ast.parse(TP_FANOUT.read_text())
    roster: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and "SUB_SKILLS" in {getattr(t, "id", None) for t in node.targets}:
            roster.update({e.elts[1].value: e.elts[0].value for e in node.value.elts})
    if not roster:
        raise RuntimeError(f"SUB_SKILLS literal not found in {TP_FANOUT} — the axis roster would be EMPTY")
    return roster


def _short_to_gate() -> dict[str, str]:
    """`{axis_short: scorecard gate name}` from tp_fanout's `_SHORT_TO_GATE` literal.

    The gate roster is the oracle for "may this axis be a verdict member of its dim" under
    RISK_CATEGORY_DASHBOARD_SPINE Decision 3 (a dim's bin rolls up its GATES, so a gateless axis
    can never be one). Published per axis so the dashboard can show WHY a live, well-instrumented
    axis is still not a bin member. Being a gate is NECESSARY, not sufficient — 2 of the 8 gates
    are unread by `deterministic_bins` — so no consumer may invert this field.
    """
    tree = ast.parse(TP_FANOUT.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and "_SHORT_TO_GATE" in {getattr(t, "id", None) for t in node.targets}:
            return {k.value: v.value for k, v in zip(node.value.keys, node.value.values)}
    raise RuntimeError(f"_SHORT_TO_GATE literal not found in {TP_FANOUT}")


def _composition(skill_dir: str) -> dict:
    """A skill's SKILL.md frontmatter `composition:` block, or `{}`.

    Same frontmatter walk as `test_measurement_types_resolver._gate_pulls` — split on `---` and
    take the first chunk that yaml-parses to a dict with a `composition` mapping, because several
    SKILL.md files carry more than one fenced block.
    """
    import yaml  # lazy: keep import-time cost off every consumer of this module

    md = SKILLS_DIR / skill_dir / "SKILL.md"
    if not md.exists():
        return {}
    for chunk in md.read_text().split("---")[1:]:
        try:
            doc = yaml.safe_load(chunk)
        except yaml.YAMLError:
            continue
        if isinstance(doc, dict) and isinstance(doc.get("composition"), dict):
            return doc["composition"]
    return {}


def _measurement_fields(measurement_type: str) -> int:
    """How many descriptor fields of `measurement_type` sit in a MEASUREMENT role.

    The ROLE test is computed rather than shortcut to catalog membership. Today the two coincide
    — every one of the 61 spec'd types has >=1 measurement-role field, so `descriptor_blind` is
    currently identical to "absent from SALIENCE_SPECS" — but a spec carrying only `label` /
    `strata` / `envelope` fields would be an instrument that measures nothing while being
    present, and membership alone would call it covered.
    """
    return sum(
        1
        for d in (field_descriptor.descriptors_for(measurement_type) or {}).values()
        if d.get("role") in MEASUREMENT_ROLES
    )


def build() -> dict:
    """The static per-axis / per-dim measurability census, plus the rosters a cross-repo consumer
    needs to reconcile it WITHOUT re-implementing any join."""
    roster = _fanout_roster()
    gates = _short_to_gate()
    catalog = field_descriptor.descriptor_catalog()

    # Every axis any of the four maps knows about. Unioned rather than taken from AXIS_TO_DIM alone
    # because the three maps route the same axis for three different consumers (verdict member /
    # coverage count / display) and every pair of them has drifted before.
    axes = sorted(
        set(AXIS_TO_DIM) | set(COVERAGE_ONLY_AXES) | set(AXIS_DIM_EXCLUSIONS) | set(_CONTEXT_DIM) | set(roster)
    )

    per_axis: dict[str, dict] = {}
    declared_types_by_axis: dict[str, list[str]] = {}
    cards_by_axis: dict[str, list[str]] = {}
    for axis in axes:
        skill_dir = roster.get(axis)
        comp = _composition(skill_dir) if skill_dir else {}
        types = sorted({t for t in (comp.get("measurement_types_pulled") or []) if isinstance(t, str)})
        cards = sorted({c for c in (comp.get("cards_used") or []) if isinstance(c, str)})
        covered = [t for t in types if _measurement_fields(t) > 0]
        blind = [t for t in types if _measurement_fields(t) == 0]

        if skill_dir is None:
            state = STATE_NOT_A_FANOUT_AXIS
        elif not types:
            state = STATE_NO_DECLARED_TYPES
        elif covered:
            state = STATE_DESCRIPTOR_COVERED
        else:
            state = STATE_DESCRIPTOR_BLIND

        lens = LENSES.get(skill_dir) if skill_dir else None
        per_axis[axis] = {
            "static_state": state,
            "skill_dir": skill_dir,
            # None = this axis is not a scorecard gate, so Decision 3 forbids it a bin. NOT a gap.
            "gate_short": gates.get(axis),
            # from narrator_lenses, the same oracle test_axis_dim_mapping_completeness uses. None
            # for a non-fan-out axis and for a lens-less skill dir; both are absences, not False.
            "verdict_bearing": (lens.verdict_key is not None) if lens is not None else None,
            "dim_verdict_member": AXIS_TO_DIM.get(axis),
            "dim_coverage_only": COVERAGE_ONLY_AXES.get(axis),
            "dim_displayed_context": _CONTEXT_DIM.get(axis),
            "declared_absence_state": (AXIS_DIM_EXCLUSIONS.get(axis) or {}).get("state"),
            "n_declared_types": len(types),
            "n_declared_cards": len(cards),
            "n_types_with_measurement_descriptor": len(covered),
            "types_without_measurement_descriptor": blind,
            "n_measurement_descriptor_fields": sum(_measurement_fields(t) for t in types),
        }
        if types:
            declared_types_by_axis[axis] = types
        if cards:
            cards_by_axis[axis] = cards

    # Per-dim roll-up. The dim SET is AXIS_TO_DIM's values, matching `evidence_coverage_by_dim`:
    # neither COVERAGE_ONLY_AXES nor _CONTEXT_DIM may invent a dim, they may only annotate one.
    dims: dict[str, dict] = {}
    for dim in dict.fromkeys(AXIS_TO_DIM.values()):
        members = [a for a in axes if AXIS_TO_DIM.get(a) == dim]
        counted = [a for a in axes if COVERAGE_ONLY_AXES.get(a) == dim]
        displayed = [a for a in axes if _CONTEXT_DIM.get(a) == dim]
        declared = members + counted  # the axes whose evidence COUNTS for the dim (Step 2d's rule)
        blind_types = sorted({t for a in declared for t in per_axis[a]["types_without_measurement_descriptor"]})
        dims[dim] = {
            "verdict_member_axes": members,
            "coverage_only_axes": counted,
            "displayed_context_axes": displayed,
            "n_axes_counted": len(declared),
            "n_axes_descriptor_covered": sum(
                1 for a in declared if per_axis[a]["static_state"] == STATE_DESCRIPTOR_COVERED
            ),
            "descriptor_blind_axes": [a for a in declared if per_axis[a]["static_state"] == STATE_DESCRIPTOR_BLIND],
            "not_a_fanout_axes": [a for a in declared if per_axis[a]["static_state"] == STATE_NOT_A_FANOUT_AXIS],
            "n_declared_types": len({t for a in declared for t in declared_types_by_axis.get(a, [])}),
            "n_types_without_measurement_descriptor": len(blind_types),
            "types_without_measurement_descriptor": blind_types,
        }

    all_types = {t for ts in declared_types_by_axis.values() for t in ts}
    blind_types = sorted(t for t in all_types if _measurement_fields(t) == 0)
    # The REVERSE queue: a spec nobody pulls. EMPTY today (catalog is a strict subset of the
    # declared set), and published as a number precisely so it can stop being zero — an absent
    # field would read as "not applicable" instead of "measured, and currently none".
    specs_unpulled = sorted(set(catalog) - all_types)
    state_counts = {s: sum(1 for v in per_axis.values() if v["static_state"] == s) for s in sorted(STATIC_STATES)}

    return {
        "schema_version": SCHEMA_VERSION,
        "producer": "measured_axes_per_dim_sidecar",
        "note": (
            "STATIC per-axis / per-dim measurability for the target-contracts framework-health "
            "dashboard (dimension 3 of 3). A TRENDING signal, never a gate. Pure function of "
            "committed source (risk_projection + ir._CONTEXT_DIM constants, tp_fanout's SUB_SKILLS "
            "and _SHORT_TO_GATE literals, narrator_lenses, and 15 SKILL.md frontmatters) with no "
            "clock and no I/O beyond reading those files => --check compares the whole document "
            "and this artifact must never acquire a timestamp. READING NOTES, each one a mistake "
            "this artifact makes easy: (1) CAPABILITY, NOT OUTCOME. `static_state` says whether an "
            "instrument EXISTS for an axis; risk_projection.evidence_coverage_by_axis says whether "
            "a RUN measured anything. The state vocabularies are deliberately disjoint so the "
            "wrong pair cannot be reconciled. They DO disagree: translational_readiness is "
            "descriptor_covered here and was `undescribed` on 504/504 corpus runs, and both "
            "readings are correct. (2) DO NOT HEADLINE `n_axes_descriptor_covered`: one covered "
            "type is enough to earn it, so it reads 14/15 and measures the direction already "
            "finished. The live queue is per TYPE -- 62 of 123 declared measurement_types carry no "
            "measurement descriptor. (3) `gate_short: null` is a DECISION, not a gap: under "
            "RISK_CATEGORY_DASHBOARD_SPINE Decision 3 a gateless axis can never be a verdict "
            "member of its dim, so a well-instrumented axis with no gate is correctly excluded. "
            "Being a gate is necessary, not sufficient (2 of 8 gates are unread by "
            "deterministic_bins) -- do not invert this field. (4) `descriptor_blind` is currently "
            "identical to `absent from SALIENCE_SPECS` because all 61 spec'd types happen to carry "
            "a measurement-role field; the role test is still computed, so a label-only spec would "
            "classify as blind rather than covered. (5) The axis->type edge is DECLARED "
            "(composition.measurement_types_pulled), a self-declaration that has drifted from "
            "cards_used before. The card->measurement_type back-ref lives in target-contracts, so "
            "the derived-vs-declared reconcile is the CONSUMER's half of this dimension and is "
            "deliberately NOT computed here -- doing so would make a sibling repo's card edit red "
            "an unrelated skills PR. `declared_types_by_axis` + `cards_by_axis` are published to "
            "make that reconcile pure set membership. (6) AXIS_DIM_EXCLUSIONS rationales are NOT "
            "copied here, only their `state`: each is a paragraph of reviewed reasoning and a copy "
            "in a second repo is a copy that drifts. Read them in risk_projection. (7) `clinical` "
            "and `commercial` read 0 of 1 axes covered, and that is NOT blindness -- their bins "
            "come from the clinical-precedent / competitor-landscape CARDS, so their single "
            "declared axis is never a fan-out subskill and is named in `not_a_fanout_axes`. A "
            "consumer must branch on that list before rendering a ratio, exactly as "
            "evidence_coverage_by_dim's docstring requires: rendering 0/1 as a measured claim of "
            "blindness is the same defect on the static side that guard prevents on the per-run "
            "side. Same reason `literature_context` and `translational_readiness` are DISPLAYED "
            "under a dim but not COUNTED toward it."
        ),
        "summary": {
            "n_axes": len(axes),
            "n_fanout_axes": len(roster),
            "n_dims": len(dims),
            "n_declared_types_distinct": len(all_types),
            "n_declared_cards_distinct": len({c for cs in cards_by_axis.values() for c in cs}),
            "n_types_with_measurement_descriptor": len(all_types) - len(blind_types),
            "n_types_without_measurement_descriptor": len(blind_types),
            "n_salience_spec_types": len(catalog),
            "n_spec_types_pulled_by_no_axis": len(specs_unpulled),
            "n_gated_axes": len(gates),
            **{f"n_axes_{state}": n for state, n in state_counts.items()},
        },
        "dims": dims,
        "axes": per_axis,
        "types_without_measurement_descriptor": blind_types,
        "spec_types_pulled_by_no_axis": specs_unpulled,
        "rosters": {
            "axis_to_dim": dict(AXIS_TO_DIM),
            "coverage_only_axes": dict(COVERAGE_ONLY_AXES),
            "context_dim": dict(_CONTEXT_DIM),
            "declared_absence_states": {a: v["state"] for a, v in AXIS_DIM_EXCLUSIONS.items()},
            "declared_types_by_axis": declared_types_by_axis,
            "cards_by_axis": cards_by_axis,
            "static_states": sorted(STATIC_STATES),
            "measurement_roles": sorted(MEASUREMENT_ROLES),
            "non_measurement_roles": sorted(NON_MEASUREMENT_ROLES),
            "reconcile_rule": (
                "For each axis, resolve every `cards_by_axis[axis]` entry through "
                "target-contracts vocabularies/measurement_types.yaml to its measurement_type, "
                "then compare that DERIVED set against `declared_types_by_axis[axis]`. A derived "
                "type missing from the declared set is the drift class "
                "test_measurement_types_resolver guards; a card that resolves to NO registered "
                "type is a third outcome and must not be collapsed into either -- unresolvable is "
                "not undeclared."
            ),
        },
    }


def _canonical(report: dict) -> str:
    return json.dumps(report, indent=2, sort_keys=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Publish the static per-dim axis measurability sidecar.")
    ap.add_argument(
        "--check",
        action="store_true",
        help="fail (exit 1) if the committed measured_axes_per_dim.json differs from a fresh build",
    )
    args = ap.parse_args(argv)

    report = build()
    fresh = _canonical(report)

    if args.check:
        if not _OUT.exists():
            print(f"  MISSING {_OUT.name} — run without --check to generate.", file=sys.stderr)
            return 1
        try:
            committed = _canonical(json.loads(_OUT.read_text()))
        except json.JSONDecodeError as exc:
            print(f"  UNPARSEABLE {_OUT.name}: {exc}", file=sys.stderr)
            return 1
        if committed != fresh:
            print(
                f"  STALE {_OUT.name} — committed census differs from computed; regenerate with "
                f"`python -m _skills_common.measured_axes_per_dim_sidecar`.",
                file=sys.stderr,
            )
            return 1
        print(f"  OK {_OUT.name} (fresh)")
        return 0

    _OUT.write_text(fresh + "\n")
    s = report["summary"]
    print(
        f"  wrote {_OUT.name}: {s['n_axes']} axes over {s['n_dims']} dims, "
        f"{s['n_types_with_measurement_descriptor']}/{s['n_declared_types_distinct']} declared "
        f"measurement_types descriptor-covered"
    )
    # Say the queue out loud on every regeneration, per DIM — a per-axis flag would report 14/15
    # covered and hide it.
    for dim, d in sorted(report["dims"].items()):
        if d["n_types_without_measurement_descriptor"]:
            print(
                f"    {dim}: {d['n_axes_descriptor_covered']}/{d['n_axes_counted']} axes covered, "
                f"{d['n_types_without_measurement_descriptor']} declared type(s) with no measurement descriptor"
            )
    # A populated queue is the EXPECTED state of a coverage dimension that starts partial by
    # design, so it must not fail the producer. This harness fails only on a broken census.
    return 0


if __name__ == "__main__":
    sys.exit(main())
