"""target-intrinsic QUESTION TABLE — the leading per-question (data · signal · confidence) hero, computed
deterministically from the already-emitted claim_vector (MODALITY_ROUTING / TRACTABILITY_PRECEDENT).

Sibling of mechanism_question_table / differentiation_question_table (same shape + shared vocab; no new
scoring model). Verdict-INERT: a one-way projection over decision['headline'] — never a rule, gate, or a
verdict (target-intrinsic is gateless / DESCRIPTIVE). DESCRIPTIVE skill → Signal polarity is `informs`
(never supports/opposes the nomination). Signal reuses the claim_vector tier vocabulary
(strong>moderate>weak>absent, unmeasured); Confidence reuses the corroboration vocabulary.
"""

from __future__ import annotations

from typing import Optional

from _skills_common.question_table_core import build_cv_question_table

_QUESTIONS = [
    ("Q1", "Do the target's domains / family imply a modality route (SM / degrader / biologic)?", "MODALITY_ROUTING"),
    ("Q2", "What is the target's development-level precedent (Pharos / IDG Tclin→Tdark)?", "TRACTABILITY_PRECEDENT"),
]


def target_intrinsic_question_table(headline: dict, cards: Optional[list] = None) -> list:
    """Per-question rows from headline.claim_vector. Verdict-inert; tolerant of an absent/partial
    claim_vector (an absent axis -> an unmeasured row, never omitted, so the hero always shows the full
    ladder + names the gap)."""
    return build_cv_question_table(headline, _QUESTIONS)


__all__ = ["target_intrinsic_question_table"]
