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
# 4th arm (2026-08-25): quantitative normal-PROTEIN abundance liability (TPHP DIA-MS). Fires on the
# normal-tissue-protein-abundance-tphp card's tphp_normal_protein_liability_class == broad_and_abundant
# (abundance-gated Floor-C, NOT DIA detection). Like the sc-normal arm it is SELECTIVITY-PRESERVING ->
# selective_with_normal_liability (a named normal-protein liability, not the housekeeping KILL).
_TPHP_NORMAL_PROTEIN_VETO_RULE = "tvn-tphp-broad-abundant-normal-protein-veto"
_NORMAL_BREADTH_VETO_RULES = (_WINDOW_VETO_RULE, _FULL_NORMAL_VETO_RULE, _SC_NORMAL_VETO_RULE,
                              _TPHP_NORMAL_PROTEIN_VETO_RULE)

# The INT-axis (tumor-cell-INTRINSIC) veto — the stromal-confound arm (2026-08-31). Distinct from the
# four SAFE-axis normal-breadth arms above: it fires when the bulk axis-A selective signal is driven by
# CAF/stroma rather than the malignant cells (tumor-scrna-celltype-expression stromal_confound_class ==
# stromal_confounded), a FALSE window for tumor-cell-targeted modalities. Symmetric instrument, orthogonal
# axis. Provenance-gated in the reader (only a trustworthy cube emits stromal_confounded), so the clamp
# never fires on a weak-annotation cube.
_STROMAL_CONFOUND_VETO_RULE = "tvn-stromal-confound-veto"

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
_VETO_VERDICT = "selective_but_broadly_normal"          # housekeeping / no-window KILL (SAFE axis)
_LIABILITY_VERDICT = "selective_with_normal_liability"  # sc-normal critical-organ: selectivity-preserving
_STROMAL_CONFOUND_VERDICT = "selective_but_stromal_confound"  # INT-axis KILL: axis-A signal is in the WRONG cells
# rule_id → the verdict its firing produces. Precedence is the _NORMAL_BREADTH_VETO_RULES order below:
# when BOTH a window veto AND the sc-normal arm fire (e.g. TACSTD2/TROP2), the window KILL wins — a gene
# with no window at all is not rescued by also having a named-organ liability.
_VETO_RULE_VERDICT = {
    _STROMAL_CONFOUND_VETO_RULE: _STROMAL_CONFOUND_VERDICT,   # INT-axis KILL (wrong cells)
    _WINDOW_VETO_RULE: _VETO_VERDICT,
    _FULL_NORMAL_VETO_RULE: _VETO_VERDICT,
    _SC_NORMAL_VETO_RULE: _LIABILITY_VERDICT,
    _TPHP_NORMAL_PROTEIN_VETO_RULE: _LIABILITY_VERDICT,   # normal-PROTEIN abundance liability (selectivity-preserving)
}

# FULL precedence order across ALL selectivity veto arms — first firing wins the verdict + driving label.
# OPTION B (2026-08-31): the INT-axis stromal-confound KILL OUTRANKS the SAFE-axis normal-breadth window
# KILL. When a gene is BOTH stroma-driven AND broadly-normal (FAP/POSTN/collagen), "the antigen is not on
# the tumor cells" is the more fundamental disqualifier for a tumor-cell-targeted modality — and the more
# actionable nomination signal — than "broadly expressed in normal tissue". Then the two SAFE-axis KILLs,
# then the two selectivity-preserving SAFE-axis liabilities. All arms only DOWNGRADE a selective axis-A call.
_SELECTIVITY_VETO_PRECEDENCE = (
    _STROMAL_CONFOUND_VETO_RULE,
    _WINDOW_VETO_RULE, _FULL_NORMAL_VETO_RULE, _SC_NORMAL_VETO_RULE, _TPHP_NORMAL_PROTEIN_VETO_RULE,
)
# All clamp outcomes still had axis-A over-expression hold; consumers asking "did any selectivity veto
# fire?" should test membership here (now incl. the INT-axis stromal-confound outcome).
_VETO_OUTCOMES = frozenset(_VETO_RULE_VERDICT.values())


def apply_normal_breadth_veto(verdict, driving_rule_id, fired):
    """Post-resolver clamp: downgrade a SELECTIVE axis-A ``(verdict, driving_rule_id)`` when ANY
    selectivity veto rule is in ``fired``. The INT-axis stromal-confound arm → ``selective_but_stromal_
    confound`` (the axis-A signal is in the WRONG cells — CAF/stroma, not malignant); the SAFE-axis window
    arms → ``selective_but_broadly_normal`` (the housekeeping/no-window KILL); the sc-normal critical-organ
    AND tphp normal-protein arms → ``selective_with_normal_liability`` (selectivity-PRESERVING named
    liabilities). Precedence (Option B): stromal-confound > window > full-normal > sc-normal >
    tphp-normal-protein — the stromal-confound KILL (not on the tumor cells) outranks the normal-breadth
    KILL when both fire, and both KILLs outrank the named liabilities. Returns the input pair unchanged
    when the verdict is not a selective axis-A class or no veto fired. One-directional.

    ``fired`` is the flat list of fired-rule dicts (each with ``rule_id``)."""
    if verdict not in _AXIS_A_SELECTIVE:
        return verdict, driving_rule_id
    fired_ids = {r.get("rule_id") for r in fired}
    for veto_rule in _SELECTIVITY_VETO_PRECEDENCE:
        if veto_rule in fired_ids:
            return _VETO_RULE_VERDICT[veto_rule], veto_rule
    return verdict, driving_rule_id
