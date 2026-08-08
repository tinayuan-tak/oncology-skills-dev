#!/usr/bin/env python3
"""combo-and-resistance — combination opportunities (+ resistance, deferred) when target X is inhibited.

GRADUATED 2026-08-07 placeholder → partial. The COMBINATION half is now wired: the combo-crispr-screen
card reads DepMap 26Q1 drug-anchor CRISPR screens (depmap-drug-anchor-combination-per-target-v1) —
"when {target} is inhibited by its anchor drug, which co-targets become MORE essential?" — via
methods/combo_drug_anchor. Emits a self-contained combination_verdict.

The RESISTANCE half (resistance-emergence-signature: genes whose loss RESCUES under inhibition —
candidate resistance mediators) is DEFERRED: the positive-shift arm of the same screens is not yet
distilled into a product. The skill reports it as an explicit remaining gap (status: partial).

SELF-CONTAINED verdict (run.py _verdict): maps the fired combination-opportunity rules → the skill's
own combination_verdict. NOT wired into nomination_verdict_gate — a combination opportunity is a
co-targeting rationale, not a monotherapy nomination. Dedicated rules axis combination_opportunity.

Biology-first; modality is a post-hoc lens (rules carry small_molecule/degrader co-targeting signals).
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill


SKILL_NAME = "combo-and-resistance"
SKILL_VERSION = "2.0.0"   # 2.0.0: graduated not_wired → partial (combination half wired;
                          #        resistance-emergence-signature deferred).

CARDS = [
    "combo-crispr-screen",
]

# The resistance half — documented remaining gap (status: partial), not yet a card/product.
DEFERRED_CARDS = [
    "resistance-emergence-signature",   # positive-shift / rescued-gene arm of the drug-anchor screens
]

QUESTION = ("When {target} is inhibited, what combination opportunities emerge — which co-targets "
            "become more essential? (Resistance-signature half deferred.)")

_RULE_VERDICT = {
    "combo-strong-opportunity": "strong_combination_opportunity",
    "combo-supported-opportunity": "combination_opportunity",
    "combo-context-opportunity": "context_combination_opportunity",
    "combo-no-signal": "no_combination_signal",
    "combo-no-anchor-screen": "combination_insufficient",
    "combo-data-unavailable": "combination_insufficient",
}
_PRECEDENCE = [
    "combo-strong-opportunity",
    "combo-supported-opportunity",
    "combo-context-opportunity",
    "combo-no-signal",
    "combo-no-anchor-screen",
    "combo-data-unavailable",
]


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Self-contained combination verdict from the fired combination-opportunity rules.
    Returns (verdict, driving_rule_id). No shared resolver."""
    fired_ids = {r.get("rule_id") for r in fired}
    for rid in _PRECEDENCE:
        if rid in fired_ids:
            return (_RULE_VERDICT[rid], rid)
    return ("combination_insufficient", None)


def _headline(cards, fired, verdict_pair):
    def _summary(cid):
        for c in cards:
            if c.get("card_id") == cid:
                return c.get("summary") or {}
        return {}
    s = _summary("combo-crispr-screen")
    verdict, driving = verdict_pair
    return {
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
        # explicit half-wired honesty:
        "resistance_half_status": "deferred — resistance-emergence-signature (rescued-gene arm) not yet wired",
    }


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="combination_opportunity",
        question=QUESTION,
        verdict_fn=_verdict,
        headline_fn=_headline,
    ))
