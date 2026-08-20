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
from _skills_common.differentiation_claims import differentiation_claim_vector, differentiation_key_signals
from _skills_common.resolver import resolve_or_raise


SKILL_NAME = "differentiation-landscape"
SKILL_VERSION = "1.3.0"

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
    "precog-prognostic-association",     # PRECOG (2026-08-10): pan-cancer META-ANALYTIC expression→survival
                                         # meta-Z (Gentles 2015 + 2026 NAR; 166 datasets / ~18k patients).
                                         # The better-powered pan-cancer CORROBORATION of the single-cohort
                                         # expression-clinical-association card above. ADDITIVE, VERDICT-INERT
                                         # (no resolver rung; differentiation verdict byte-stable). reads precog_prognostic.
    "pathway-node-leverage",             # WS3 (2026-08-17): COMPARATIVE node-leverage — is the target the best
                                         # NODE to hit in its complex/pathway neighbourhood, or dominated? ADDITIVE,
                                         # VERDICT-INERT (its rules emit soft axis_fit signals + fired_rule_ids for
                                         # the cross-evidence hypothesis agent; feed NO resolver → differentiation
                                         # verdict byte-stable). reads node_leverage_class + evidence_scope.
    "alteration-clinical-association",   # Q11-alteration (2026-08-20): does {target} MUTATION status
                                         # stratify OS (prognostic context)? The alteration analog of
                                         # expression-clinical-association. ADDITIVE, VERDICT-INERT (its
                                         # alteration-* rules feed NO resolver; differentiation verdict
                                         # byte-stable). reads alteration_survival_association_class.
    "subtype-survival-association",      # Q2-subtype (2026-08-20): does OS differ ACROSS the indication's
                                         # molecular subtypes? Target-independent patient-selection context.
                                         # ADDITIVE, VERDICT-INERT (subtype-* rules feed NO resolver;
                                         # differentiation verdict byte-stable). reads subtype_survival_association_class.
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
    return resolve_or_raise(fired, "differentiation")

def _headline(cards, fired, verdict_pair):
    v, drv = verdict_pair or ("insufficient", None)
    hl = {
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
        # PRECOG pan-cancer META-ANALYTIC corroboration of the single-cohort survival call above
        # (render facet; verdict-inert — no resolver rung). Surface the class + both meta-Z views so a
        # reader can compare the single-cohort log-rank vs the pan-cancer meta-analysis at a glance:
        "precog_prognostic_class":          get_card_field(cards, "precog-prognostic-association",
                                                 "prognostic_class"),
        "precog_meta_z":                    get_card_field(cards, "precog-prognostic-association", "meta_z"),
        "precog_pan_cancer_meta_z":         get_card_field(cards, "precog-prognostic-association",
                                                 "pan_cancer_meta_z"),
        "precog_indication_approx":         get_card_field(cards, "precog-prognostic-association",
                                                 "precog_indication_approx"),
        # WS3 comparative node-leverage (soft/verdict-inert differentiation context; feeds NO resolver —
        # its axis_fit signals + fired_rule_ids are consumed by the cross-evidence hypothesis agent):
        "node_leverage_class":              get_card_field(cards, "pathway-node-leverage",
                                                 "node_leverage_class"),
        "node_leverage_evidence_scope":     get_card_field(cards, "pathway-node-leverage",
                                                 "evidence_scope"),
    }
    # verdict-INERT claim-vector projection (7th concrete) — COMUT/SURVIVAL/PROGNOSIS/NODE decomposition
    # + citable atoms the composed fan-out lifts to the cross-evidence agent.
    hl["claim_vector"] = differentiation_claim_vector(hl, cards)
    hl["key_signals"] = differentiation_key_signals(hl, cards)
    return hl


_SYNTHESIS_FACET_KEYS = (
    "differentiation_verdict", "driving_rule_id", "cooccurrence_class",
    "survival_association_class", "precog_prognostic_class", "node_leverage_class",
    "claim_vector", "key_signals",
)


def _synthesis_facet(cards, fired, verdict_pair):
    """Compact, VERDICT-INERT differentiation facet for the composed target-profile synthesis. Reuses
    _headline (single source) + returns the DESCRIPTIVE claim_vector (COMUT/SURVIVAL/PROGNOSIS/NODE) +
    its citable atoms. Never moves the verdict; safe to omit."""
    h = _headline(cards, fired, verdict_pair)
    facet = {k: h.get(k) for k in _SYNTHESIS_FACET_KEYS}
    facet["_facet_note"] = ("Deterministic differentiation-landscape facet; claim_vector is a DESCRIPTIVE "
                            "decomposition (direction in the atoms). Verdict owned by the resolver.")
    return facet


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
