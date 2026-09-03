"""literature-context QUESTION TABLE — the leading per-question (data · signal · confidence) hero,
computed deterministically from the already-emitted claim_vector (VOLUME / RECENCY / RELATION).

Sibling of mechanism_question_table / translational_readiness_question_table (same shape + shared vocab;
no new scoring model). Verdict-INERT: a one-way projection over decision['headline'] — never a rule,
gate, or verdict (literature-context is gateless / DESCRIPTIVE / context-tier).

literature-context is a CONTEXT skill: its signals INFORM the literature picture (how much/how recent/
what typed relations) — descriptive, NOT a good/bad push on the nomination. Signal polarity is `informs`.

  Q1 co-occurrence volume (how much is written)?  primary claim VOLUME
  Q2 recent literature activity?                   primary claim RECENCY
  Q3 typed mechanistic relations (PubTator3)?      primary claim RELATION

Signal reuses the claim_vector tier vocabulary (strong>moderate>weak>absent, unmeasured); Confidence
reuses the corroboration vocabulary (high>moderate>low, unmeasured).
"""
from __future__ import annotations

from typing import Optional

from _skills_common.question_table_core import conf as _conf, row as _row

_SIG_META = {"strong": (5, "informs"), "moderate": (3, "informs"), "weak": (2, "informs"),
             "absent": (1, "informs"), "unmeasured": (0, "none")}


def _sig(tier: str, label: str) -> dict:
    fill, pol = _SIG_META.get(tier, (0, "none"))
    return {"tier": tier, "fill": fill, "polarity": pol, "label": label}


def _axis_row(qid: str, question: str, cv: dict, key: str) -> dict:
    atom = (cv or {}).get(key) or {}
    tier = atom.get("signal", "unmeasured")
    corr = atom.get("corroboration", "unmeasured")
    primary = atom.get("evidence") or "data_unavailable"
    return _row(qid, question, primary, "", _sig(tier, str(tier)),
                _conf(corr, f"corroboration: {corr}"))


_QUESTIONS = [
    ("Q1", "How much is written about this gene × indication (co-occurrence volume)?", "VOLUME"),
    ("Q2", "Is the cited literature recent / currently active?", "RECENCY"),
    ("Q3", "What typed mechanistic relations are reported (PubTator3 associate/cause/inhibit/…)?", "RELATION"),
]


def literature_context_question_table(headline: dict, cards: Optional[list] = None) -> list:
    """Per-question rows for literature-context, from headline.claim_vector. Verdict-inert; tolerant of
    an absent/partial claim_vector (an absent axis → an unmeasured row, never omitted)."""
    cv = (headline or {}).get("claim_vector") or {}
    return [_axis_row(qid, q, cv, key) for qid, q, key in _QUESTIONS]


__all__ = ["literature_context_question_table"]
