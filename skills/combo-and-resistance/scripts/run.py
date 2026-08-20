#!/usr/bin/env python3
"""combo-and-resistance — combination opportunities AND resistance mediators when target X is inhibited.

GRADUATED 2026-08-07 placeholder → partial (combination half). UPGRADED 2026-08-10 partial → wired:
the RESISTANCE half is now live alongside the combination half.

COMBINATION half: the combo-crispr-screen card reads DepMap 26Q1 drug-anchor CRISPR screens
(depmap-drug-anchor-combination-per-target-v1) — "when {target} is inhibited by its anchor drug,
which co-targets become MORE essential?" — via methods/combo_drug_anchor. Self-contained
combination_verdict (axis combination_opportunity).

RESISTANCE half: the resistance-emergence-signature card reads the SIGN-MIRROR product
(depmap-drug-anchor-resistance-per-target-v1, the POSITIVE arm of the SAME screens) — "which gene
knockouts RESCUE the cell under inhibition = candidate resistance mediators?" — via
methods/resistance_emergence. Self-contained resistance_verdict (axis resistance_emergence).

BOTH verdicts are self-contained and NOT wired into nomination_verdict_gate — a combination
opportunity is a co-targeting rationale and a resistance mediator is a monitoring rationale; neither
is a monotherapy nomination. The dispatcher fires the combination axis (its primary verdict); the
resistance axis is fired + resolved here in-skill (no dispatcher change), so the combination spine
is byte-identical to the pre-resistance version.

Biology-first; modality is a post-hoc lens (rules carry small_molecule/degrader signals).
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common import card_summary
from _skills_common.dispatcher import run_wired_skill


SKILL_NAME = "combo-and-resistance"
SKILL_VERSION = "3.0.0"   # 3.0.0: resistance half wired (both combination + resistance verdicts).
                          # 2.0.0 was combination-only (resistance-emergence-signature deferred).

CARDS = [
    "combo-crispr-screen",
    "resistance-emergence-signature",
]

# No deferred cards remain — both halves wired.
DEFERRED_CARDS: list[str] = []

QUESTION = ("When {target} is inhibited, what combination opportunities emerge (which co-targets "
            "become more essential) AND what resistance mediators emerge (which knockouts rescue)?")

# ── Combination half (primary; fired by the dispatcher on axis combination_opportunity) ──
_RULE_VERDICT = {
    "combo-strong-opportunity": "strong_combination_opportunity",
    "combo-supported-opportunity": "combination_opportunity",
    "combo-context-opportunity": "context_combination_opportunity",
    "combo-no-signal": "no_combination_signal",
    "combo-no-anchor-screen": "combination_insufficient",
    "combo-opportunity-data-unavailable": "combination_insufficient",
}
_PRECEDENCE = [
    "combo-strong-opportunity",
    "combo-supported-opportunity",
    "combo-context-opportunity",
    "combo-no-signal",
    "combo-no-anchor-screen",
    "combo-opportunity-data-unavailable",
]

# ── Resistance half (secondary; fired in-skill on axis resistance_emergence) ──
_RESISTANCE_VERDICT = {
    "resistance-strong-signal": "strong_resistance_signal",
    "resistance-supported-signal": "resistance_signal",
    "resistance-context-signal": "context_resistance_signal",
    "resistance-no-signal": "no_resistance_signal",
    "resistance-no-anchor-screen": "resistance_insufficient",
    "resistance-data-unavailable": "resistance_insufficient",
}
_RESISTANCE_PRECEDENCE = [
    "resistance-strong-signal",
    "resistance-supported-signal",
    "resistance-context-signal",
    "resistance-no-signal",
    "resistance-no-anchor-screen",
    "resistance-data-unavailable",
]


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Self-contained combination verdict from the fired combination-opportunity rules.
    Returns (verdict, driving_rule_id). No shared resolver."""
    fired_ids = {r.get("rule_id") for r in fired}
    for rid in _PRECEDENCE:
        if rid in fired_ids:
            return (_RULE_VERDICT[rid], rid)
    return ("combination_insufficient", None)


def _resistance_verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Self-contained resistance verdict from the fired resistance-emergence rules."""
    fired_ids = {r.get("rule_id") for r in fired}
    for rid in _RESISTANCE_PRECEDENCE:
        if rid in fired_ids:
            return (_RESISTANCE_VERDICT[rid], rid)
    return ("resistance_insufficient", None)


def _headline(cards, fired, verdict_pair):
    def _summary(cid):
        return card_summary(cards, cid)  # shared helper (_skills_common)

    # combination half
    s = _summary("combo-crispr-screen")
    verdict, driving = verdict_pair

    # resistance half — the dispatcher fires the resistance_emergence axis as an EXTRA AUDIT axis
    # (run_wired_skill(extra_axes=["resistance_emergence"])), so its rules are already merged into
    # `fired` and land in decision['fired_rules'] + run_health. Derive the self-contained resistance
    # verdict from that SAME fired list — so resistance_verdict/driving_rule_id are traceable to an
    # emitted fired rule (previously the in-skill firing was dropped from the audit spine).
    r_verdict, r_driving = _resistance_verdict(fired)
    rs = _summary("resistance-emergence-signature")

    return {
        # ── combination half (unchanged) ──
        "combination_verdict": verdict,
        "driving_rule_id": driving,
        "combination_opportunity_class": s.get("combination_opportunity_class"),
        "anchor_drug": s.get("anchor_drug"),
        "anchor_mechanism": s.get("anchor_mechanism"),
        "n_co_targets": s.get("n_co_targets"),
        "strongest_co_target": s.get("strongest_co_target"),
        "strongest_co_target_shift": s.get("strongest_co_target_shift"),
        "strongest_co_target_class": s.get("strongest_co_target_class"),
        "top_co_targets": s.get("top_co_targets"),
        "combination_context": s.get("combination_context"),
        # ── resistance half (newly wired) ──
        "resistance_verdict": r_verdict,
        "resistance_driving_rule_id": r_driving,
        "resistance_emergence_class": rs.get("resistance_emergence_class"),
        "n_resistance_mediators": rs.get("n_resistance_mediators"),
        "strongest_resistance_mediator": rs.get("strongest_mediator"),
        "strongest_resistance_mediator_shift": rs.get("strongest_mediator_shift"),
        "strongest_resistance_mediator_class": rs.get("strongest_mediator_class"),
        "top_resistance_mediators": rs.get("top_resistance_mediators"),
        "resistance_context": rs.get("resistance_context"),
        # orthogonal, verdict-inert Tahoe transcriptional-adaptation sub-signal (which resistance
        # programs the anchor drug INDUCES). Enriches the picture; does NOT drive resistance_verdict.
        "tahoe_adaptation_class": rs.get("tahoe_adaptation_class"),
        "tahoe_induced_programs": rs.get("tahoe_induced_programs"),
        "tahoe_adaptation_note": rs.get("tahoe_adaptation_note"),
        "resistance_half_status": "wired — resistance-emergence-signature (DepMap genetic-rescue verdict + Tahoe transcriptional-adaptation facet) live",
    }


# The uniform opt-in the target-profile fan-out looks for via getattr(module, "_synthesis_facet").
# combo-and-resistance is DUAL-verdict: the fan-out lifts the COMBINATION verdict via _verdict (its
# primary, axis combination_opportunity), but the RESISTANCE verdict is computed in _headline (secondary,
# axis resistance_emergence) and would otherwise be dropped from the composed profile. This facet reuses
# _headline (single source of truth) and surfaces BOTH verdicts + their key signals, so the composed
# synthesis sees the resistance mediators (NF1/KEAP1/NF2-style rescues) it was previously blind to.
# VERDICT-INERT: both verdicts are gateless (absent from _SHORT_TO_GATE); nothing here enters the
# nomination spine. Closes arch-review R9.
_SYNTHESIS_FACET_KEYS = (
    # combination half
    "combination_verdict", "driving_rule_id", "combination_opportunity_class",
    "anchor_drug", "anchor_mechanism", "strongest_co_target", "top_co_targets",
    # resistance half (the previously-dropped verdict)
    "resistance_verdict", "resistance_driving_rule_id", "resistance_emergence_class",
    "n_resistance_mediators", "strongest_resistance_mediator", "top_resistance_mediators",
    "tahoe_adaptation_class",
)


def _synthesis_facet(cards, fired, verdict_pair):
    """Compact, VERDICT-INERT combination+resistance facet for the composed target-profile synthesis.
    Reuses `_headline` (single source of truth) so BOTH the combination verdict AND the resistance
    verdict (+ mediators) reach the cross-lens layer. Never moves the verdict; safe to omit."""
    h = _headline(cards, fired, verdict_pair)
    facet = {k: h.get(k) for k in _SYNTHESIS_FACET_KEYS}
    facet["_facet_note"] = (
        "Deterministic combination + resistance facet from combo-and-resistance (DEPmap drug-anchor "
        "CRISPR screens). combination_verdict = which co-targets become MORE essential under {target} "
        "inhibition (co-targeting rationale); resistance_verdict = which knockouts RESCUE (candidate "
        "resistance mediators). Both are gateless/verdict-inert to the nomination spine — combination "
        "biology, not a monotherapy nomination signal.")
    return facet


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="combination_opportunity",
        question=QUESTION,
        verdict_fn=_verdict,
        headline_fn=_headline,
        # Fire the resistance axis for the AUDIT spine (decision['fired_rules'] + run_health) —
        # the combination verdict stays keyed on `axis` above; resistance is verdict-independent.
        extra_axes=["resistance_emergence"],
    ))
