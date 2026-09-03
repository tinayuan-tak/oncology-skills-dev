"""cis-feature-coherence QUESTION TABLE — the leading per-question (data · signal · confidence) hero,
computed deterministically from the already-emitted claim_vector (CIS_DOSAGE / SILENCING / EXPR_DEP /
CONJOINT).

Sibling of mechanism_question_table / differentiation_question_table (same shape + shared vocab; no new
scoring model). Verdict-INERT: a one-way projection over decision['headline'] — never a rule, gate, or a
verdict. cis-feature-coherence is INERT (its verdict is verdict-shaped but explicitly NOT a call), so the
Signal polarity is `informs` (never supports/opposes the nomination). Signal reuses the claim_vector tier
vocabulary (strong>moderate>weak>absent, unmeasured); Confidence reuses the corroboration vocabulary.
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
    ("Q1", "Does copy-number drive expression (cis-dosage coupling)?", "CIS_DOSAGE"),
    ("Q2", "Does promoter methylation silence expression?", "SILENCING"),
    ("Q3", "Does expression track dependency (expression→dependency coherence)?", "EXPR_DEP"),
    ("Q4", "Is there amplification∩over-expression addiction (conjoint)?", "CONJOINT"),
]


def cis_coherence_question_table(headline: dict, cards: Optional[list] = None) -> list:
    """Per-question rows from headline.claim_vector. Verdict-inert; tolerant of an absent/partial
    claim_vector (an absent axis -> an unmeasured row, never omitted, so the hero always shows the full
    ladder + names the gap)."""
    cv = (headline or {}).get("claim_vector") or {}
    return [_axis_row(qid, q, cv, key) for qid, q, key in _QUESTIONS]


__all__ = ["cis_coherence_question_table"]
