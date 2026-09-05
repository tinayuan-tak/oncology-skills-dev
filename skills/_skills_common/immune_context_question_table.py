"""immune-context QUESTION TABLE — the leading per-question (data · signal · confidence) hero, computed
deterministically from the already-emitted claim_vector. immune-context is a TCE effector-arm CONTEXT
skill (CD8 infiltration companion to surface-modality-fit).

DESCRIPTIVE skill → the rows come from the shared `build_cv_question_table` (informs polarity, never
supports/opposes the nomination). Verdict-INERT: a one-way projection over decision['headline'].
"""
from __future__ import annotations

from typing import Optional

from _skills_common.question_table_core import build_cv_question_table

_QUESTIONS = [
    ("Q1", "Is the tumor immune-hot for a TCE effector arm (CD8 infiltration / effector state)?", "IMMUNE"),
]


def immune_context_question_table(headline: dict, cards: Optional[list] = None) -> list:
    """Per-question rows from headline.claim_vector (verdict-inert; an absent axis -> an unmeasured row)."""
    return build_cv_question_table(headline, _QUESTIONS)


__all__ = ["immune_context_question_table"]
