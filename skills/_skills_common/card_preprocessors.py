"""Shared per-gate CARD PREPROCESSORS — mutate card summaries BEFORE fired_rules, in EVERY resolution
path.

Some skills apply a correction to their card summaries before firing rules — e.g. genomic-alteration's
family-wise FDR across the stratified-dependency classes. This lived ONLY in the skill's main() (a
pre-resolver card mutation, outside _verdict), so BOTH composed paths silently BYPASSED it:
  - target-profile fan-out builds `fired` itself (resolve_cards → fired_rules → _verdict), never main();
  - compose-dashboard resolves via compose_core.resolve_gate_spine → fired_rules on raw card_outputs.
→ the composed genomic verdict was MORE LIBERAL than standalone (an un-corrected biomarker_stratified_
dependency — the nomination veto-suppressor — could rescue a target the standalone skill would demote).

This module single-sources the preprocessors and a `preprocess_cards_for_gate(cards, gate)` entry point
that the skill's main(), target-profile's fan-out, AND resolve_gate_spine all call before firing, so the
correction travels to all three paths identically. Preprocessors MUTATE cards in place (matching the
skill's historical semantics) and return a provenance dict.
"""
from __future__ import annotations

# (card_id, class_field, p_field, firing_classes, demoted_class) — the genomic-alteration stratified-
# dependency family. Each card fires the SAME biomarker_stratified_dependency verdict from an
# INDEPENDENT Mann-Whitney test at its own per-card alpha; across the family the per-card alpha is
# uncorrected. Moved here from genomic-alteration-profile/run.py so all paths share ONE definition.
_STRATIFIED_FAMILY = [
    ("mutation-stratified-dependency", "mutation_stratification_class", "hotspot_mannwhitney_p",
     {"mutant_strongly_dependent", "mutant_moderately_dependent"}, "not_mutation_stratified"),
    ("copy-number-stratified-dependency", "cn_stratification_class", "cn_stratification_mannwhitney_p",
     {"amplified_strongly_dependent", "amplified_moderately_dependent"}, "not_cn_stratified"),
    ("fusion-stratified-dependency", "fusion_stratification_class", "fusion_stratification_mannwhitney_p",
     {"fusion_positive_strongly_dependent", "fusion_positive_moderately_dependent"}, "not_fusion_stratified"),
    ("amp-expr-stratified-dependency", "amp_expr_stratification_class", "amp_expr_mannwhitney_p",
     {"amplified_overexpressed_strongly_dependent", "amplified_overexpressed_moderately_dependent"},
     "not_amp_expr_stratified"),
]


def _bh_qvalues(pvals: list[float]) -> list[float]:
    """Benjamini-Hochberg adjusted q-values (order preserved)."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    q = [0.0] * m
    prev = 1.0
    for rank, idx in enumerate(reversed(order), start=1):
        k = m - rank + 1
        val = min(prev, pvals[idx] * m / k)
        q[idx] = val
        prev = val
    return q


def apply_family_wise_fdr(cards: list[dict], alpha: float = 0.05) -> dict:
    """BH-correct the genomic stratified-dependency family and DEMOTE (mutate class in place) any FIRING
    class whose family-wise q >= alpha. Bites only when >=2 classes FIRE (single-class calls stay
    byte-stable). Returns a provenance dict.

    The BH denominator is the number of TESTED classes (every family card that produced a valid p,
    whether or not it fired), NOT just the firing subset: conditioning multiplicity on the firing
    subset under-corrects (a gene tested on all 4 classes with 2 firing at p~0.03 would get m=2,
    q~0.03, both survive — instead of m=4, q~0.06-0.12, both demote). Family-wise multiplicity is the
    number of tests PERFORMED. The correction TRIGGER stays at >=2 firing: correcting single firing
    calls against m=tested is a larger recalibration, decided separately."""
    card_by_id = {c["card_id"]: c for c in cards}
    tested = []
    for card_id, class_field, p_field, firing_classes, demoted in _STRATIFIED_FAMILY:
        c = card_by_id.get(card_id)
        if not c:
            continue
        summ = c.get("summary") or {}
        cls, p = summ.get(class_field), summ.get(p_field)
        if isinstance(p, (int, float)):   # a valid p → this class was TESTED (fired or not)
            tested.append({"card_id": card_id, "class_field": class_field, "p": float(p),
                           "fired": cls in firing_classes, "demoted": demoted, "summary": summ})
    firing = [t for t in tested if t["fired"]]
    if len(firing) < 2:
        return {"family_size": len(tested), "n_firing": len(firing),
                "tested": [t["card_id"] for t in tested], "demoted": [],
                "family_wise_q": {}, "corrected": False}
    qs = _bh_qvalues([t["p"] for t in tested])   # m = TESTED classes, not the firing subset
    demoted, fam_q = [], {}
    for t, q in zip(tested, qs):
        fam_q[t["card_id"]] = round(q, 6)
        if t["fired"] and q >= alpha:
            t["summary"][t["class_field"]] = t["demoted"]
            t["summary"]["_family_wise_fdr_demoted"] = True
            t["summary"]["_family_wise_q"] = round(q, 6)
            demoted.append(t["card_id"])
    return {"family_size": len(tested), "n_firing": len(firing),
            "tested": [t["card_id"] for t in tested], "demoted": demoted,
            "family_wise_q": fam_q, "corrected": True}


# Per-gate registry: gate → preprocessor(cards) -> provenance. Applied before fired_rules in ALL paths.
CARD_PREPROCESSORS = {
    "genomic_alteration": apply_family_wise_fdr,
}


def preprocess_cards_for_gate(cards: list[dict], gate: "str | None") -> dict:
    """Apply the registered card preprocessor for `gate` (mutates `cards` in place). Returns the
    preprocessor's provenance dict, or {} when no preprocessor is registered / gate is None. Safe to
    call for any gate — a no-op unless registered. The genomic FDR mutates only the genomic
    stratified-dependency cards, so calling it before a shared fired_rules cannot perturb other gates."""
    fn = CARD_PREPROCESSORS.get(gate) if gate else None
    return fn(cards) if fn else {}
