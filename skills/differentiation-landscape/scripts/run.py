#!/usr/bin/env python3
"""differentiation-landscape — Phase-E partial skill (graduated 2026-07-08).

Co-mutation + mutual-exclusivity landscape from panel-intersect-aware Fisher
scan across TCGA MC3 + GENIE 19.0-public.

W4c refactor (2026-07-09): calls the shared run_wired_skill dispatcher.
Skill-specific logic reduces to CARDS + verdict + headline callbacks.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill
from _skills_common import get_card_field
from _skills_common.resolver import resolve_verdict_for_gate


SKILL_NAME = "differentiation-landscape"
SKILL_VERSION = "1.2.0"

CARDS = [
    "co-mutation-and-mutual-exclusivity",
    "stemness-context",   # Malta 2018 (2026-08-10): per-indication tumor-stemness (mRNAsi) cohort prior
                          # — dedifferentiation/aggressiveness prognostic context. ADDITIVE, VERDICT-INERT
                          # (its rules feed NO resolver; differentiation verdict byte-stable). reads stemness_index.
    "expression-clinical-association",   # Q11 (2026-07-23 composition) — does target expression
                                         # stratify SURVIVAL (prognostic context)? A patient-selection /
                                         # clinical-context render facet + biomarker-facet stratification
                                         # input. ADDITIVE — its clinical-* rules feed NO resolver ladder
                                         # (differentiation verdict byte-stable; resolver reads only the
                                         # co-mutation rule_ids). Fills part of the clinical-precedent gap
                                         # this skill's status-partial note flags.
]

QUESTION = ("What genes co-occur with or are mutually exclusive to "
            "{target} mutations across TCGA MC3 + GENIE 19.0-public, "
            "and what patient-selection or combination-biology hypotheses "
            "does the pattern support in {indication}?")

PARTIAL_STATUS_NOTE = (
    "differentiation-landscape is status: partial; clinical-precedent + "
    "patent-landscape cards not wired (licensing pending). Only co-mutation "
    "signal reflected in this decision."
)


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Verdict — DELEGATES to the shared declarative resolver (gap #5, 2026-07-20).
    The former if-chain now lives in resolvers/differentiation.resolver.yaml (target-contracts),
    evaluated by the ONE interpreter both engines call. Proven byte-for-byte equivalent to
    the former if-chain by the golden-oracle test. A missing spec raises (the resolver is
    the source of truth — no silent fallback to a stale copy, which would reintroduce drift)."""
    result = resolve_verdict_for_gate(fired, "differentiation")
    if result is None:
        raise RuntimeError(
            "differentiation resolver spec missing (target-contracts/resolvers/differentiation.resolver.yaml) "
            "— the verdict source of truth is absent.")
    return result

def _headline(cards, fired, verdict_pair):
    v, drv = verdict_pair or ("insufficient", None)
    return {
        "differentiation_verdict":          v,
        "driving_rule_id":                  drv,
        "cooccurrence_class":               get_card_field(cards, "co-mutation-and-mutual-exclusivity",
                                                 "cooccurrence_class"),
        "n_significant_cooccurring":        get_card_field(cards, "co-mutation-and-mutual-exclusivity",
                                                 "n_significant_cooccurring"),
        "n_significant_mutually_exclusive": get_card_field(cards, "co-mutation-and-mutual-exclusivity",
                                                 "n_significant_mutually_exclusive"),
        "n_pairs_panel_intersect_eligible": get_card_field(cards, "co-mutation-and-mutual-exclusivity",
                                                 "n_pairs_panel_intersect_eligible"),
        "n_pairs_per_source_only":          get_card_field(cards, "co-mutation-and-mutual-exclusivity",
                                                 "n_pairs_per_source_only"),
        "has_cooccurring_driver":           get_card_field(cards, "co-mutation-and-mutual-exclusivity",
                                                 "has_cooccurring_driver"),
        "has_mutually_exclusive_driver":    get_card_field(cards, "co-mutation-and-mutual-exclusivity",
                                                 "has_mutually_exclusive_driver"),
        "top_cooccurring":                  get_card_field(cards, "co-mutation-and-mutual-exclusivity",
                                                 "top_cooccurring"),
        "top_mutually_exclusive":           get_card_field(cards, "co-mutation-and-mutual-exclusivity",
                                                 "top_mutually_exclusive"),
        # Q11 expression→survival prognostic context (render facet; feeds NO resolver — the
        # differentiation verdict reads only the co-mutation rule_ids, so this is verdict-inert):
        "survival_association_class":       get_card_field(cards, "expression-clinical-association",
                                                 "survival_association_class"),
        "logrank_p":                        get_card_field(cards, "expression-clinical-association", "logrank_p"),
    }


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="intracellular_intrinsic",
        question=QUESTION,
        verdict_fn=_verdict,
        headline_fn=_headline,
        partial_status_note=PARTIAL_STATUS_NOTE,
    ))
