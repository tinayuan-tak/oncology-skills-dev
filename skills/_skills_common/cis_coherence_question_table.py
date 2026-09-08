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

from _skills_common.question_table_core import build_cv_question_table

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
    return build_cv_question_table(headline, _QUESTIONS)


__all__ = ["cis_coherence_question_table"]
