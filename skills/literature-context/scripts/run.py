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
from _skills_common.literature_context_claims import (
    literature_context_claim_vector, literature_context_key_signals)
from _skills_common.literature_context_question_table import literature_context_question_table
from _skills_common.headline_core import build_headline, HeadlineSpec
from _skills_common.skill_report import build_skill_report, ROLE_DESCRIPTIVE


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


# Canonical headline spec (DESCRIPTIVE MODE — verdict_token=None). VOLUME (how much is written) is the
# coverage-critical axis that floors confidence.
_LITERATURE_HEADLINE_SPEC = HeadlineSpec(
    gate="literature_context",
    axis_labels={"VOLUME": "co-occurrence volume", "RECENCY": "recent activity",
                 "RELATION": "typed relations"},
    axis_keys=("VOLUME", "RECENCY", "RELATION"),
    critical_axes=("VOLUME",),
)


def _build_headline_block(headline: dict) -> dict:
    """Canonical Headline block in DESCRIPTIVE MODE — literature-context is gateless (verdict_fn=None), so
    verdict_token=None and the deterministic key_signals.headline is the descriptive_phrase (call stays
    None, polarity neutral). Never moves a spine (there is none)."""
    ks = headline.get("key_signals") or {}
    return build_headline(headline, headline.get("claim_vector"), headline.get("key_signals"),
                          spec=_LITERATURE_HEADLINE_SPEC, verdict_token=None,
                          descriptive_phrase=ks.get("headline"))


def _headline(cards, fired, verdict_pair):
    """Descriptive cited-literature context — the flat summary fields from the composed card. No verdict
    spine (verdict_fn=None): cited literature informs confidence/context, not a nomination. A composed
    consumer reads these as gene×indication literature context."""
    hl = {
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
    # ── verdict-INERT signals-first projections (mirrors the other descriptive skills) ─────────────
    hl["claim_vector"] = literature_context_claim_vector(hl, cards)
    hl["key_signals"] = literature_context_key_signals(hl, cards)
    # The per-question LEADING table + the DESCRIPTIVE headline block + the UNIFIED skill_report. All
    # best-effort + verdict-INERT — a formatting/read fault must NEVER discard the literature-context
    # fields already built in `hl` (tumor-presence degrade-on-exception discipline).
    try:
        hl["question_table"] = literature_context_question_table(hl, cards)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the context spine
        hl.setdefault("_enrichment_errors", {})["question_table"] = f"{type(exc).__name__}: {exc}"
        hl["question_table"] = None
    try:
        hl["headline_block"] = _build_headline_block(hl)
    except Exception as exc:  # noqa: BLE001
        hl.setdefault("_enrichment_errors", {})["headline_block"] = f"{type(exc).__name__}: {exc}"
        hl["headline_block"] = None
    # UNIFIED skill_report (docs/UNIFIED_OUTPUT_CONTRACT.md) — literature-context is GATELESS DESCRIPTIVE
    # (verdict_fn=None → no call) + CONTEXT-tier → role=descriptive, verdict=None → call=None,
    # polarity=not_scored. Never a gate (RISK_ASSESSMENT_INTEGRATION.md §4).
    try:
        _used = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and not c.get("_missing")]
        _missing = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and c.get("_missing")]
        hl["skill_report"] = build_skill_report(
            role=ROLE_DESCRIPTIVE,
            verdict=None,
            headline_block=hl.get("headline_block"),
            claim_vector=hl.get("claim_vector"),
            question_table=hl.get("question_table"),
            fired_rule_ids=[f.get("rule_id") for f in (fired or [])],
            cards_used=_used or CARDS,
            cards_missing=_missing,
        )
    except Exception as exc:  # noqa: BLE001
        hl.setdefault("_enrichment_errors", {})["skill_report"] = f"{type(exc).__name__}: {exc}"
        hl["skill_report"] = None
    return hl


# ── OPTIONAL cross-modal synthesis facet (lifts the claim_vector to the composed target-profile) ────
# literature-context is DESCRIPTIVE + context-tier (verdict_fn=None); this carries the verdict-INERT
# literature claim_vector + headline_block + question_table + skill_report to the composed target-profile
# synthesis (getattr(module, "_synthesis_facet")). Never moves a verdict + never a gate.
_SYNTHESIS_FACET_KEYS = (
    "cited_evidence_status", "literature_scope", "paper_disease_mentions", "recent_mentions",
    "n_diseases", "earliest_year", "latest_year", "top_cited", "relation_types",
    "total_relation_publications",
    "claim_vector", "key_signals", "question_table", "headline_block", "skill_report",
)


def _synthesis_facet(cards, fired, verdict_pair=None):
    """Compact, VERDICT-INERT cited-literature facet for the composed target-profile synthesis. Reuses
    _headline (single source). Gateless + context-tier — never a verdict, never a gate."""
    h = _headline(cards, fired, verdict_pair)
    facet = {k: h.get(k) for k in _SYNTHESIS_FACET_KEYS}
    facet["_facet_note"] = ("Deterministic literature-context facet; claim_vector is VOLUME/RECENCY/"
                            "RELATION over the cited-literature card. Context-tier — never a gate.")
    return facet


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
