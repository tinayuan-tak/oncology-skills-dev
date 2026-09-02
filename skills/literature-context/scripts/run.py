#!/usr/bin/env python3
"""literature-context — verdict-INERT descriptive skill (wired 2026-09-02).

Composes ONE card, cited-literature-evidence (OT europepmc co-occurrence + PubTator3 relation
direction), into a "what does the literature SAY about {target} in {indication}, with citations" read.

DESCRIPTIVE (verdict_fn=None): like target-intrinsic / translational-readiness, this skill emits no
nomination verdict — cited literature is CONTEXT/CONFIDENCE that informs the synthesis, never a gate
(RISK_ASSESSMENT_INTEGRATION.md §4). Uses the shared run_wired_skill dispatcher; skill-specific logic
reduces to CARDS + a headline callback.

PROMOTES the former cited_literature_evidence.json side-channel (the target-profile
tp_grounding.auto_cited_evidence bolt-on, now REMOVED) to a first-class fan-out member composing a
governed card — so the card/skill validators + the emission guard see it. Distinct from the sibling
literature-risk-assessment skill (live PubMed + LLM 6-dimension RISK read); this reads pinned,
catalogued products (reproducible, no LLM).
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill
from _skills_common import get_card_field


SKILL_NAME = "literature-context"
SKILL_VERSION = "1.0.0"

CARDS = [
    "cited-literature-evidence",   # OT europepmc co-occurrence (volume/recency + top cited statements)
                                   # + PubTator3 BioREx typed relation direction. gene×indication.
                                   # VERDICT-INERT descriptive literature context (composes both readers
                                   # via analysis-methods cited_literature_evidence.read).
]

QUESTION = ("What does the literature say about {target} in {indication} — co-occurrence volume/recency, "
            "the top cited statements (Open Targets europePMC), and typed relation direction (PubTator3 "
            "associate/cause/inhibit/…) — with citations?")


def _headline(cards, fired, verdict_pair):
    """Descriptive cited-literature context — the flat summary fields from the composed card. No verdict
    spine (verdict_fn=None): cited literature informs confidence/context, not a nomination. A composed
    consumer reads these as gene×indication literature context."""
    return {
        "cited_evidence_status":       get_card_field(cards, "cited-literature-evidence",
                                            "cited_evidence_status"),
        "literature_scope":            get_card_field(cards, "cited-literature-evidence",
                                            "literature_scope"),
        "paper_disease_mentions":      get_card_field(cards, "cited-literature-evidence",
                                            "paper_disease_mentions"),
        "recent_mentions":             get_card_field(cards, "cited-literature-evidence",
                                            "recent_mentions"),
        "n_diseases":                  get_card_field(cards, "cited-literature-evidence", "n_diseases"),
        "earliest_year":               get_card_field(cards, "cited-literature-evidence", "earliest_year"),
        "latest_year":                 get_card_field(cards, "cited-literature-evidence", "latest_year"),
        "top_cited":                   get_card_field(cards, "cited-literature-evidence", "top_cited"),
        "relation_types":              get_card_field(cards, "cited-literature-evidence", "relation_types"),
        "total_relation_publications": get_card_field(cards, "cited-literature-evidence",
                                            "total_relation_publications"),
    }


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="intracellular_intrinsic",   # rules axis for loading; literature-context emits no verdict
        question=QUESTION,
        verdict_fn=None,                   # DESCRIPTIVE — cited literature is context, not a gate
        headline_fn=_headline,
    ))
