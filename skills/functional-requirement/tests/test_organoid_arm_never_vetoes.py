"""Guard H5 (2026-09-19): the ORGANOID arm is verdict-inert BY CONSTRUCTION — no dependency-resolver
rung references an organoid rule id, so the organoid read can never move (still less VETO) the dependency
verdict. The audit confirmed this structurally, but it was only COMMENT-asserted (run.py's Phase-3 note +
the rules-file caveat "CORROBORATING facet only"). A comment does not stop a future rung from wiring the
organoid rule into a veto; this test does.

The organoid arm exists as a real interpretation rule (`organoid-selective-dependency-supportive`, keyed
on organoid-crispr-dependency.organoid_dependency_class), so a naive "no organoid rule anywhere" guard
would be vacuous the moment someone renamed the arm. Instead we take the organoid rule ids from the RULES
file by card binding, assert the set is non-empty (anti-vacuity), and assert none of them is referenced by
any resolver rung.

S3-free: pure over the resolver spec + the rules file. Skips gracefully if target-contracts is absent.
"""

from __future__ import annotations

import pytest
from _skills_common import load_interpretation_rules
from _skills_common.resolver import load_resolver

_ORGANOID_CARD_ID = "organoid-crispr-dependency"


def _resolver_referenced_rule_ids(spec: dict) -> set[str]:
    """Every rule_id any rung can key on, across all three when-forms plus an explicit driving_rule."""
    ids: set[str] = set()
    for rung in spec.get("resolve", []):
        if "when_fired" in rung:
            ids.add(rung["when_fired"])
        ids.update(rung.get("when_any_fired", []) or [])
        ids.update(rung.get("when_all_fired", []) or [])
        if rung.get("driving_rule"):
            ids.add(rung["driving_rule"])
    return ids


def _organoid_rule_ids() -> set[str] | None:
    rules = load_interpretation_rules("intracellular_intrinsic")
    if not rules:
        return None
    return {
        r["rule_id"]
        for r in rules
        if isinstance(r, dict) and (r.get("when") or {}).get("card_id") == _ORGANOID_CARD_ID and r.get("rule_id")
    }


def test_organoid_arm_is_never_a_resolver_rung():
    spec = load_resolver("dependency")
    organoid = _organoid_rule_ids()
    if spec is None or organoid is None:
        pytest.skip("target-contracts resolver / rules not available")

    # anti-vacuity: the organoid arm must actually EXIST as a rule, or this guard proves nothing.
    assert organoid, (
        f"no interpretation rule binds to {_ORGANOID_CARD_ID} — the guard would be vacuous. If the "
        "organoid arm was retired, delete this guard; otherwise restore the rule."
    )

    referenced = _resolver_referenced_rule_ids(spec)
    wired = organoid & referenced
    assert not wired, (
        f"organoid rule(s) {sorted(wired)} are referenced by a dependency-resolver rung — the organoid "
        "arm must stay a CORROBORATING facet only (verdict-inert), never a rung that can move or veto the "
        "dependency verdict. See run.py Phase-3 and the E1-organoid rules caveat."
    )
