"""Regression guard for gap-#5 step 5 — compose-dashboard's signal matrix converged onto
the ONE shared rule matcher (`_skills_common.fired_rules`), same matcher target-profile uses.

Two invariants this pins (a future edit that breaks either fails CI):

1. **Byte-identical to the old inline matcher.** `_build_signal_matrix` no longer
   re-implements when.card_id/field/equals/in matching — it pivots the shared matcher's
   output. Firing every scalar rule (one card per rule, built from the rule's own `when`)
   must reproduce the pre-convergence matrix exactly.

2. **Per-modality projection.** compose-dashboard is the per-MODALITY consumer. The shared
   matcher is channel-agnostic and also fires target-first / `subtype_fit_*` rules
   (e.g. the `in_record` subtype-non-dependence rule) that belong to target-profile's
   per-gate resolver. Those non-modality channels must be filtered OUT of this matrix so
   its (card_id, modality) contract stays exact — the reason the old inline matcher (which
   had no in_record handling) and the new path agree even though fired_rules fires more rules.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR.parent))
SKILLS_DIR = SCRIPTS_DIR.parent.parent
if str(SKILLS_DIR) not in sys.path:
    sys.path.insert(0, str(SKILLS_DIR))

import pytest

from scripts._synthesis import _build_signal_matrix, _MODALITY_CHANNELS  # noqa: E402
from _skills_common.rules_loader import load_interpretation_rules  # noqa: E402

AXES = ["intracellular_intrinsic", "surface_intrinsic"]


def _old_inline_matcher(card_outputs, rules):
    """The pre-convergence inline matcher, verbatim (equals/in only, ALL channels, no
    in_record) — the golden reference the converged path must reproduce."""
    if not rules:
        return {}
    card_by_id = {c["card_id"]: c for c in card_outputs
                  if c.get("card_id") and not c.get("excluded_by_applies_when")}
    matrix = {}
    for rule in rules:
        w = rule.get("when") or {}
        cid, field = w.get("card_id"), w.get("field")
        equals, in_list = w.get("equals"), w.get("in") or []
        signals = rule.get("signals") or {}
        dom, km = bool(rule.get("dominant")), rule.get("killer_message")
        if not cid or not field:
            continue
        card = card_by_id.get(cid)
        if card is None:
            continue
        summ = card.get("summary") or {}
        actual = (card.get("interpretation_call") if field == "interpretation_call"
                  else (summ.get(field) if field in summ else card.get(field)))
        matched = (actual == equals) if equals is not None else (actual in in_list if in_list else False)
        if not matched:
            continue
        for mod, sig in signals.items():
            e = {"signal": sig, "rule_id": rule.get("rule_id", "<no-id>"), "dominant": dom}
            if sig == "killer" and km:
                e["killer_message"] = km
            matrix.setdefault((cid, mod), []).append(e)
    return matrix


def _norm(mx):
    return {k: sorted(v, key=lambda e: (e["signal"], e["rule_id"])) for k, v in sorted(mx.items())}


def _one_card_per_scalar_rule(rules):
    """Build one card per scalar (equals/in) rule that satisfies its `when` predicate, so
    every scalar rule in the axis fires. in_record rules are handled separately."""
    cards = {}
    for r in rules:
        w = r.get("when") or {}
        cid, field = w.get("card_id"), w.get("field")
        if not cid or not field or w.get("in_record"):
            continue
        val = w.get("equals") if w.get("equals") is not None else (w.get("in") or [None])[0]
        if val is None:
            continue
        c = cards.setdefault(cid, {"card_id": cid, "summary": {}})
        if field == "interpretation_call":
            c["interpretation_call"] = val
        else:
            c["summary"][field] = val
    return list(cards.values())


@pytest.mark.parametrize("axis", AXES)
def test_converged_matrix_byte_identical_to_old_inline_matcher(axis):
    """Invariant 1: firing every scalar rule reproduces the pre-convergence matrix exactly."""
    rules = load_interpretation_rules(axis) or []
    cards = _one_card_per_scalar_rule(rules)
    assert cards, f"[{axis}] fixture built no cards — rule shape changed?"
    old = _norm(_old_inline_matcher(cards, rules))
    new = _norm(_build_signal_matrix(cards, rules))
    assert new == old, (
        f"[{axis}] converged _build_signal_matrix diverged from the old inline matcher.\n"
        f"  only in OLD: {set(old) - set(new)}\n  only in NEW: {set(new) - set(old)}")
    assert old, f"[{axis}] expected a non-empty matrix (rules should have fired)"


@pytest.mark.parametrize("axis", AXES)
def test_matrix_keys_are_only_modality_channels(axis):
    """Invariant 2: every matrix key's channel is one of the five delivery modalities —
    non-modality channels (subtype_fit_*, target_*) are the resolver's, filtered out here."""
    rules = load_interpretation_rules(axis) or []
    cards = _one_card_per_scalar_rule(rules)
    matrix = _build_signal_matrix(cards, rules)
    offenders = [k for k in matrix if k[1] not in _MODALITY_CHANNELS]
    assert not offenders, f"[{axis}] non-modality channels leaked into the matrix: {offenders}"


def test_in_record_subtype_channel_is_filtered_out():
    """The subtype-non-dependence in_record rule (subtype_fit_genomic) fires in the shared
    matcher but must NOT appear in compose-dashboard's per-modality matrix. This is the
    concrete case the modality filter guards (the old inline matcher never fired it because
    it had no in_record handling; the shared matcher does)."""
    rules = load_interpretation_rules("intracellular_intrinsic") or []
    # A measured, floor-cleared not_dependent stratum → the in_record rule matches.
    metrics = [{"stratum": "MSS", "class": "not_dependent",
                "evidence_state": "measured", "subgroup_n_floor_met": True}]
    cards = [{"card_id": "subgroup-stratified-dependency",
              "summary": {"per_subgroup_metrics": metrics},
              "per_subgroup_metrics": metrics}]
    matrix = _build_signal_matrix(cards, rules)
    assert ("subgroup-stratified-dependency", "subtype_fit_genomic") not in matrix
    # And no modality-keyed entry is spuriously produced for this subtype-only card.
    assert all(k[0] != "subgroup-stratified-dependency" for k in matrix), matrix
