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


def apply_promiscuous_amplicon_fusion_demotion(cards: list[dict]) -> dict:
    """#983 copy-number gate on the fusion driver call. A `recurrent_fusion_driver` whose confidence tier
    is `moderate_promiscuous` (the target recurs but with NO recurrent 5'/3' partner — a MIXED bucket) AND
    whose locus is ALSO recurrently focally AMPLIFIED (copy-number-distribution.patient_focal_cn_class ==
    recurrent_focal_amplification) is an amplicon PASSENGER SV (ERBB2/STAD, MDM2/SARC), not a competent
    fusion driver. DEMOTE fusion_class -> `promiscuous_amplicon_fusion` (mutate in place) so the
    `fusion-landscape-recurrent-driver-supportive` rung no longer fires and the multi-class framing stops
    naming a fusion co-driver.

    Copy-number is the ORTHOGONAL signal the card caveat calls for: no STRUCTURAL feature separates an
    amplicon passenger from a genuine promiscuous kinase fusion (ROS1/NTRK1/FGFR2), but the passenger
    co-localises with focal amplification and the kinase fusion does not — so ROS1/NTRK1/FGFR2 (not
    amplified) are SPARED. Verdict-moving ONLY for the amplified amplicon-passenger subset, whose
    amplification-driver rung already carries the verdict (the fusion contribution was redundant). Idempotent
    (a second pass sees the already-demoted class and no-ops). Returns a provenance dict."""
    by = {c["card_id"]: c for c in cards}
    fus = by.get("fusion-rearrangement-landscape")
    if not fus:
        return {"demoted": False, "reason": "no_fusion_card"}
    fsum = fus.get("summary") or {}
    csum = ((by.get("copy-number-distribution") or {}).get("summary") or {})
    if (fsum.get("fusion_class") == "recurrent_fusion_driver"
            and fsum.get("fusion_recurrence_confidence") == "moderate_promiscuous"
            and csum.get("patient_focal_cn_class") == "recurrent_focal_amplification"):
        fsum["fusion_class"] = "promiscuous_amplicon_fusion"
        fsum["_amplicon_fusion_demoted"] = True
        return {"demoted": True, "from": "recurrent_fusion_driver", "to": "promiscuous_amplicon_fusion",
                "co_signal": "recurrent_focal_amplification"}
    return {"demoted": False, "fusion_class": fsum.get("fusion_class"),
            "fusion_recurrence_confidence": fsum.get("fusion_recurrence_confidence"),
            "patient_focal_cn_class": csum.get("patient_focal_cn_class")}


def _genomic_alteration_preprocess(cards: list[dict]) -> dict:
    """Composite genomic_alteration preprocessor applied (in ALL resolution paths that use the registry)
    before fired_rules: (1) family-wise FDR on the stratified-dependency family, then (2) the #983
    copy-number-gated promiscuous-amplicon fusion demotion. The two mutate disjoint cards; provenance is
    namespaced. (The skill's hand-rolled main() calls the two functions directly — the demotion is
    idempotent, so standalone and composed converge on the same cards.)"""
    return {"family_wise_fdr": apply_family_wise_fdr(cards),
            "amplicon_fusion_demotion": apply_promiscuous_amplicon_fusion_demotion(cards)}


# Per-gate registry: gate → preprocessor(cards) -> provenance. Applied before fired_rules in ALL paths.
CARD_PREPROCESSORS = {
    "genomic_alteration": _genomic_alteration_preprocess,
}


def preprocess_cards_for_gate(cards: list[dict], gate: "str | None") -> dict:
    """Apply the registered card preprocessor for `gate` (mutates `cards` in place). Returns the
    preprocessor's provenance dict, or {} when no preprocessor is registered / gate is None. Safe to
    call for any gate — a no-op unless registered. The genomic FDR mutates only the genomic
    stratified-dependency cards, so calling it before a shared fired_rules cannot perturb other gates."""
    fn = CARD_PREPROCESSORS.get(gate) if gate else None
    return fn(cards) if fn else {}
