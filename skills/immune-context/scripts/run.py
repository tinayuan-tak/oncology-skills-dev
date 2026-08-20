#!/usr/bin/env python3
"""immune-context — EFFECTOR-arm wired skill (new 2026-08-06, biologics-augment).

The effector companion to surface-modality-fit. A T-cell engager redirects cytotoxic T cells to the
antigen, so it can only work where T cells are PRESENT. surface-modality-fit answers "is there a
surface target?"; this answers the orthogonal "is the tumor immune-hot — is there a CD8 effector
population to redirect?" (IO-target-ID seed note method #2). Consumes the immune-context card
(CIBERSORT LM22 T-cell infiltration from gdc-pancanatlas-immune-2018).

Deliberately a STANDALONE skill, NOT a card inside surface-modality-fit: immune context is the
effector axis, orthogonal to surface biology — a TCE needs BOTH. It composes into the TCE story
ALONGSIDE surface-modality-fit.

v1 is per-indication / target-INDEPENDENT (tier: indication); the antigen-conditioned join (are the
ANTIGEN-HIGH patients also T-cell-high?) is a deferred v2 facet. The verdict is a direct read of the
immune_context_class categorical (a descriptive effector-context call — no cross-card resolver).
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill
from _skills_common import get_card_field
from _skills_common.immune_context_claims import (
    immune_context_claim_vector, immune_context_key_signals)

SKILL_NAME = "immune-context"
SKILL_VERSION = "1.0.0"

CARDS = [
    "immune-context",
]

QUESTION = ("For {indication}, is the tumor immune-hot or immune-cold — is there a CD8 T-cell "
            "effector population present for a T-cell engager to redirect (independent of {target})?")

# The immune-context rules (surface-intrinsic.rules.yaml) that fire on immune_context_class, mapped to
# this skill's effector-context verdict. The skill's verdict IS the immune-context class, resolved from
# the FIRED rule (the standard framework pattern — the categorical drives a rule, the rule drives the
# verdict), so the signal is also visible to any downstream composer, not just this skill.
_RULE_TO_VERDICT = {
    "immune-context-hot-tce-supportive":       "immune_hot",
    "immune-context-intermediate-tce-neutral": "immune_intermediate",
    "immune-context-cold-tce-opposing":        "immune_cold",
}


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Resolve the effector-context verdict from the fired immune-context rule. Exactly one of the
    three class rules fires per run (the class is mutually exclusive); data_unavailable fires none →
    honest insufficient."""
    for r in fired:
        rid = r.get("rule_id")
        if rid in _RULE_TO_VERDICT:
            return (_RULE_TO_VERDICT[rid], rid)
    return ("insufficient", None)


def _headline(cards, fired, verdict_pair):
    v, drv = verdict_pair or ("insufficient", None)
    hl = {
        "immune_context_verdict":        v,
        "driving_rule_id":               drv,
        "immune_context_class":          get_card_field(cards, "immune-context", "immune_context_class"),
        "median_cd8_fraction":           get_card_field(cards, "immune-context", "median_cd8_fraction"),
        "median_total_t_cell_fraction":  get_card_field(cards, "immune-context", "median_total_t_cell_fraction"),
        "n_samples":                     get_card_field(cards, "immune-context", "n_samples"),
        "tumor_studies":                 get_card_field(cards, "immune-context", "tumor_studies"),
    }
    # verdict-INERT claim-vector projection (TCE effector axis) + citable CD8-fraction atom for the
    # cross-evidence reasoner. immune-context is gateless (absent from _SHORT_TO_GATE); verdict-inert.
    hl["claim_vector"] = immune_context_claim_vector(hl, cards)
    hl["key_signals"] = immune_context_key_signals(hl, cards)
    return hl


_SYNTHESIS_FACET_KEYS = (
    "immune_context_verdict", "driving_rule_id", "immune_context_class", "median_cd8_fraction",
    "median_total_t_cell_fraction", "n_samples", "claim_vector", "key_signals",
)


def _synthesis_facet(cards, fired, verdict_pair):
    """Compact, VERDICT-INERT immune-context facet for the composed synthesis. Reuses _headline (single
    source) + returns the IMMUNE claim_vector (TCE effector axis) with its citable CD8-fraction atom.
    immune-context is gateless — this never moves the nomination spine."""
    h = _headline(cards, fired, verdict_pair)
    facet = {k: h.get(k) for k in _SYNTHESIS_FACET_KEYS}
    facet["_facet_note"] = ("Deterministic immune-context facet; claim_vector is the TCE EFFECTOR axis "
                            "(indication-level, target-independent). Gateless — no verdict on the spine.")
    return facet


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="surface_intrinsic",     # effector context reads on the biologics (surface/TCE) side
        question=QUESTION,
        verdict_fn=_verdict,
        headline_fn=_headline,
    ))
