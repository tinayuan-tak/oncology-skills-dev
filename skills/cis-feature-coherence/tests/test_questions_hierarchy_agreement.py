"""Guard: the hand-maintained questions.yaml agrees with the generated question_hierarchy.yaml.

The whole cis-feature-coherence review (2026-09-12) started from an UNTESTED drift — questions.yaml
placed `amp_expr_stratified_dependency` under CONJOINT while the generated question_hierarchy.yaml (mirror
of the governed target_profiling_axes.yaml) placed it under CIS_DOSAGE. The two files are both consumed by
the evidence_graph / literature-axis-crosswalk layer, so a divergence silently mis-routes cards to the
wrong axis. `test_question_hierarchy_drift.py` only guards the hierarchy vs the governed source; nothing
guarded questions.yaml against the hierarchy. This test closes that gap for THIS skill: for every question,
the (sub_group, measurement_types) assignment in questions.yaml must match the hierarchy (measurement_types
+ context_types, order-insensitive).
"""

from __future__ import annotations

from pathlib import Path

import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent


def _load(name: str) -> dict:
    return yaml.safe_load((SKILL_DIR / name).read_text()) or {}


def test_questions_yaml_agrees_with_hierarchy():
    questions = _load("questions.yaml")
    hierarchy = _load("question_hierarchy.yaml")

    # hierarchy: axis_id (sub_group id) -> set of measurement_types (measurement_types + context_types)
    hier_by_axis: dict[str, set] = {}
    for sg in hierarchy.get("sub_groups", []):
        mts = set(sg.get("context_types", []) or [])
        for q in sg.get("questions", []) or []:
            mts.update(q.get("measurement_types", []) or [])
        hier_by_axis[sg["id"]] = mts

    # questions.yaml: axis_id -> set of measurement_types (union across questions on that axis)
    q_by_axis: dict[str, set] = {}
    for q in questions.get("questions", []) or []:
        axis = q.get("axis_id")
        if axis is None:
            continue
        q_by_axis.setdefault(axis, set()).update(q.get("measurement_types", []) or [])

    assert set(q_by_axis) == set(hier_by_axis), (
        f"axis sets differ: questions.yaml={sorted(q_by_axis)} hierarchy={sorted(hier_by_axis)}"
    )
    mismatches = {
        axis: {"questions_yaml": sorted(q_by_axis[axis]), "hierarchy": sorted(hier_by_axis[axis])}
        for axis in q_by_axis
        if q_by_axis[axis] != hier_by_axis[axis]
    }
    assert not mismatches, f"questions.yaml measurement_types diverge from the hierarchy per axis: {mismatches!r}"
