"""translational-readiness QUESTION TABLE — the leading per-question (data · signal · confidence) hero,
computed deterministically from the already-emitted claim_vector (MODEL / GENOTYPE / ORGANOID / PDX).

Sibling of mechanism_question_table / differentiation_question_table (same shape + shared vocab; no new
scoring model). Verdict-INERT: a one-way projection over decision['headline'] — never a rule, gate, or
a verdict (translational-readiness is gateless / DESCRIPTIVE).

translational-readiness is a CONTEXT skill: its signals INFORM preclinical-validation readiness (can I
validate the nomination in patient-derived models, does it reproduce ex-vivo / in-vivo) — descriptive,
NOT a good/bad push on the nomination. So the Signal polarity is `informs` (never supports/opposes).

  Q1 patient-derived (HCMI) models available to validate?   primary claim MODEL
  Q2 does an available model carry THIS target's alteration? primary claim GENOTYPE
  Q3 dependency reproduces EX VIVO (patient-derived organoid)? primary claim ORGANOID
  Q4 tractability reproduces IN VIVO (PDX population trials)?  primary claim PDX

Signal reuses the claim_vector tier vocabulary (strong>moderate>weak>absent, unmeasured); Confidence
reuses the corroboration vocabulary (high>moderate>low, unmeasured).
"""

from __future__ import annotations

from typing import Optional

from _skills_common.question_table_core import build_cv_question_table

_QUESTIONS = [
    ("Q1", "Are patient-derived (HCMI) models available to preclinically validate the nomination?", "MODEL"),
    ("Q2", "Does an available patient-derived model carry a functional alteration in THIS target?", "GENOTYPE"),
    (
        "Q3",
        "Does the target's dependency reproduce EX VIVO in patient-derived organoid (3D CRISPR) models?",
        "ORGANOID",
    ),
    ("Q4", "Does the target's tractability reproduce IN VIVO in PDX population trials?", "PDX"),
]


def translational_readiness_question_table(headline: dict, cards: Optional[list] = None) -> list:
    """Per-question rows for translational-readiness, from headline.claim_vector. Verdict-inert;
    tolerant of an absent/partial claim_vector (an absent axis → an unmeasured row, never omitted, so the
    hero always shows the full ladder + names the gap)."""
    return build_cv_question_table(headline, _QUESTIONS)


__all__ = ["translational_readiness_question_table"]
