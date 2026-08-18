"""Shared normal-breadth VETO clamp for the tumor-selectivity gate.

The selectivity axis-A verdict (from target-contracts/resolvers/selectivity.resolver.yaml) is
NECESSARY but NOT SUFFICIENT: a gene over-expressed vs its tissue of origin but with NO therapeutic
window vs the worst critical normal (a housekeeping archetype — GAPDH/ACTB, or the TROP2/TACSTD2
broadly-normal surface archetype) is not a real target regardless of its axis-A fold-change. This
POST-RESOLVER clamp downgrades a selective axis-A verdict to `selective_but_broadly_normal` when ANY
normal-breadth veto rule fired (worst-case conjunction). One-directional: it can only DOWNGRADE a
selective call, never upgrade.

WHY SHARED: the clamp is single-sourced here and applied in BOTH consumers — tumor-selectivity's
run.py::_verdict AND the compose-dashboard engine (_skills_common.compose_core.resolve_gate_spine) —
so the two apply it identically. (The engine resolves selectivity via the raw resolver, which has no
veto rungs; without this shared clamp it would report `strong_tumor_selective` for a broadly-normal
gene that the standalone skill downgrades.) The clamp is a NO-OP unless a veto rule actually fired AND
the verdict is a selective axis-A class, so non-veto targets are byte-unchanged in both engines.
"""
from __future__ import annotations

SELECTIVITY_GATE = "selectivity"

# The axis-A "selective" verdicts the normal-breadth veto can downgrade.
_AXIS_A_SELECTIVE = frozenset({
    "strong_tumor_selective", "modest_tumor_selective", "field_effect_tumor_selective",
})

# All normal-breadth veto rule_ids — ANY firing downgrades a selective axis-A call. Ordered by the
# precedence used for the driving_rule LABEL when several fire (all yield the same verdict): essential-
# organ window > pan-normal window > sc-normal cell-type (the bulk window vetoes are the longer-standing
# instruments). Mirrors modality-therapeutic-window (2 arms) + sc-normal-celltype-expression (1 arm).
_WINDOW_VETO_RULE = "tvn-no-therapeutic-window-veto"
_FULL_NORMAL_VETO_RULE = "tvn-no-full-normal-window-veto"
_SC_NORMAL_VETO_RULE = "tvn-sc-normal-critical-organ-veto"
_NORMAL_BREADTH_VETO_RULES = (_WINDOW_VETO_RULE, _FULL_NORMAL_VETO_RULE, _SC_NORMAL_VETO_RULE)

_VETO_VERDICT = "selective_but_broadly_normal"


def apply_normal_breadth_veto(verdict, driving_rule_id, fired):
    """Post-resolver clamp: downgrade a SELECTIVE axis-A ``(verdict, driving_rule_id)`` to
    ``selective_but_broadly_normal`` when ANY normal-breadth veto rule is in ``fired``. Returns the
    input pair unchanged when the verdict is not a selective axis-A class or no veto fired.

    Byte-identical to the historical tumor-selectivity/run.py::_verdict clamp (precedence-ordered
    driving-rule label). ``fired`` is the flat list of fired-rule dicts (each with ``rule_id``)."""
    if verdict not in _AXIS_A_SELECTIVE:
        return verdict, driving_rule_id
    fired_ids = {r.get("rule_id") for r in fired}
    for veto_rule in _NORMAL_BREADTH_VETO_RULES:
        if veto_rule in fired_ids:
            return _VETO_VERDICT, veto_rule
    return verdict, driving_rule_id
