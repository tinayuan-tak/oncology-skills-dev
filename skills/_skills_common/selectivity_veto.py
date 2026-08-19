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

# The clamp produces two DISTINCT downgrade outcomes (the sc-normal-liability SPLIT, 2026-08-19):
#   - the therapeutic-window arms (tumor BELOW the worst critical/full normal — housekeeping GAPDH,
#     the TROP2 broadly-normal surface archetype) → the KILL: no real tumor-vs-normal window at all.
#   - the sc-normal critical-organ arm → a SELECTIVITY-PRESERVING named-organ flag: the target IS
#     tumor-selective (a real window vs origin) but is also expressed in an essential cell type of a
#     NON-origin critical organ that bulk medians dilute. Approved antigens (DLL3 forebrain neuron,
#     ERBB2 cardiomyocyte/nephron, FOLR1 renal) land here — their normal expression is REAL but they
#     are drugs via modality/accessibility/clinical precedent, so this is a SAFETY/therapeutic-index
#     concern (owned by on-target-safety-liability + modality-fit), NOT loss of selectivity. Measured
#     on the #416 backtest panel: the old single-verdict clamp collapsed these into the housekeeping
#     KILL — a false-negative for approved drugs (the CD19 "over-eager clamp kills good targets" lesson).
_VETO_VERDICT = "selective_but_broadly_normal"          # housekeeping / no-window KILL
_LIABILITY_VERDICT = "selective_with_normal_liability"  # sc-normal critical-organ: selectivity-preserving
# rule_id → the verdict its firing produces. Precedence is the _NORMAL_BREADTH_VETO_RULES order below:
# when BOTH a window veto AND the sc-normal arm fire (e.g. TACSTD2/TROP2), the window KILL wins — a gene
# with no window at all is not rescued by also having a named-organ liability.
_VETO_RULE_VERDICT = {
    _WINDOW_VETO_RULE: _VETO_VERDICT,
    _FULL_NORMAL_VETO_RULE: _VETO_VERDICT,
    _SC_NORMAL_VETO_RULE: _LIABILITY_VERDICT,
}
# Both clamp outcomes are still "selective" in the sense that axis-A over-expression held; consumers
# that ask "did the normal-breadth clamp fire?" should test membership in this set.
_VETO_OUTCOMES = frozenset(_VETO_RULE_VERDICT.values())


def apply_normal_breadth_veto(verdict, driving_rule_id, fired):
    """Post-resolver clamp: downgrade a SELECTIVE axis-A ``(verdict, driving_rule_id)`` when ANY
    normal-breadth veto rule is in ``fired``. The window arms → ``selective_but_broadly_normal`` (the
    housekeeping/no-window KILL); the sc-normal critical-organ arm → ``selective_with_normal_liability``
    (a selectivity-PRESERVING named-organ flag). Precedence: window > full-normal > sc-normal (a
    no-window KILL outranks a named-organ liability when both fire). Returns the input pair unchanged
    when the verdict is not a selective axis-A class or no veto fired. One-directional.

    ``fired`` is the flat list of fired-rule dicts (each with ``rule_id``)."""
    if verdict not in _AXIS_A_SELECTIVE:
        return verdict, driving_rule_id
    fired_ids = {r.get("rule_id") for r in fired}
    for veto_rule in _NORMAL_BREADTH_VETO_RULES:
        if veto_rule in fired_ids:
            return _VETO_RULE_VERDICT[veto_rule], veto_rule
    return verdict, driving_rule_id
