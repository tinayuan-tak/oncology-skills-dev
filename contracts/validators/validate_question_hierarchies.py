#!/usr/bin/env python3
"""validate_question_hierarchies.py — connectivity + reference checks for the governed question
hierarchies (target_profiling_axes.yaml `question_hierarchies`), the MIDDLE levels of the
objective → axis → sub-group → question → measurement_type → card decomposition.

WHY: the sub-group/question layer became load-bearing (it drives the signals-first subgroup_signals
fleet-wide) but its card binding depends on measurement_types.yaml. Consolidating it here as the single
source of truth is only a hardening if the two are RECONCILED by CI. This validator asserts, over the
whole section:
  * every sub-group has >= 1 question;
  * every question declares >= 1 measurement_type, and EVERY declared measurement_type (including a
    sub-group's context_types and a skill's other_lenses) EXISTS in measurement_types.yaml — so a
    renamed/retired type can no longer silently orphan a question;
  * `axis` (when not null) names a real questions[].short axis above.

VERDICT-NEUTRAL: taxonomy only; no resolver/gate logic. Exit 0 = clean; 1 = a connectivity/reference
defect (with the offending skill/question named).
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

VOCAB = Path(__file__).resolve().parent.parent / "vocabularies"
AXES = VOCAB / "target_profiling_axes.yaml"
MTYPES = VOCAB / "measurement_types.yaml"


def _load():
    axes = yaml.safe_load(AXES.read_text()) or {}
    mt = yaml.safe_load(MTYPES.read_text()) or {}
    known_types = set((mt.get("measurement_types") or {}).keys())
    axis_shorts = {q.get("short") for q in (axes.get("questions") or [])}
    return axes.get("question_hierarchies") or {}, known_types, axis_shorts


def validate() -> list:
    hierarchies, known_types, axis_shorts = _load()
    errors: list = []
    if not hierarchies:
        return ["question_hierarchies section is missing or empty"]
    for skill, spec in sorted(hierarchies.items()):
        axis = spec.get("axis")
        if axis is not None and axis not in axis_shorts:
            errors.append(f"{skill}: axis {axis!r} is not a questions[].short axis")
        sub_groups = spec.get("sub_groups") or []
        if not sub_groups:
            errors.append(f"{skill}: no sub_groups")
            continue
        for sg in sub_groups:
            sgid = sg.get("id", "<no-id>")
            questions = sg.get("questions") or []
            if not questions:
                errors.append(f"{skill}/{sgid}: sub-group has no questions")
            for ctx in sg.get("context_types") or []:
                if ctx not in known_types:
                    errors.append(f"{skill}/{sgid}: context_type {ctx!r} not in measurement_types.yaml")
            for q in questions:
                qid = q.get("id", "<no-id>")
                mts = q.get("measurement_types") or []
                if not mts:
                    errors.append(f"{skill}/{sgid}/{qid}: question declares no measurement_types")
                for t in mts:
                    if t not in known_types:
                        errors.append(f"{skill}/{sgid}/{qid}: measurement_type {t!r} not in measurement_types.yaml")
        for lens in spec.get("other_lenses") or []:
            for t in lens.get("measurement_types") or []:
                if t not in known_types:
                    errors.append(f"{skill}: other_lens measurement_type {t!r} not in measurement_types.yaml")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("validate_question_hierarchies: FAIL")
        for e in errors:
            print(f"  - {e}")
        return 1
    hierarchies, _, _ = _load()
    print(
        f"validate_question_hierarchies: OK — {len(hierarchies)} skills, "
        "every question sourced by a known measurement_type"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
