"""Mechanism-and-pharmacology QUESTION TABLE — the leading per-question (data · signal · confidence)
hero for the mechanism-and-pharmacology skill, computed deterministically from its already-emitted
claim_vector (NETWORK / PHOSPHO / PATHWAY / PERTURBATION / PREDICTABILITY).

Sibling of dependency_question_table / differentiation_question_table (same shape + shared vocab; no new
scoring model). Verdict-INERT: a one-way projection over decision['headline'] — never a rule, resolver,
gate, or the mechanism_verdict.

Mechanism is a MoA-CONTEXT skill: its signals INFORM the mechanism/engagement picture (candidate MoA
hooks, measured signaling-state, PD-marker context) — they are descriptive, NOT a good/bad push on the
nomination. So the Signal polarity is `informs` (never supports/opposes), matching the skill's
DESCRIPTIVE claim_vector (NETWORK is capped at moderate — annotation density, not biology; PHOSPHO is the
one measured-activity signal).

  Q1 signaling-network topology + MoA hooks?   primary claim NETWORK
  Q2 phospho-activity (measured signaling-state)? primary claim PHOSPHO
  Q3 cohort-relative pathway activity context?  primary claim PATHWAY
  Q4 target engagement under drug perturbation? primary claim PERTURBATION
  Q5 dependency predictability (own-omics/driver-predictable)? primary claim PREDICTABILITY

Signal reuses the claim_vector tier vocabulary (strong>moderate>weak>absent, unmeasured); Confidence
reuses the corroboration vocabulary (high>moderate>low, unmeasured).
"""
from __future__ import annotations

from typing import Optional

from _skills_common.question_table_core import build_cv_question_table


_QUESTIONS = [
    ("Q1", "Signaling-network topology + MoA hooks (upstream regulators / downstream effectors)?", "NETWORK"),
    ("Q2", "Phospho-activity — measured activation / signaling-state (beyond abundance)?", "PHOSPHO"),
    ("Q3", "Cohort-relative pathway activity context?", "PATHWAY"),
    ("Q4", "Target engagement under drug perturbation (MoA, not dependency)?", "PERTURBATION"),
    ("Q5", "Is the dependency own-omics / driver-predictable?", "PREDICTABILITY"),
]


def mechanism_question_table(headline: dict, cards: Optional[list] = None) -> list:
    """Per-question rows for mechanism-and-pharmacology, from headline.claim_vector. Verdict-inert;
    tolerant of an absent/partial claim_vector (an absent axis → an unmeasured row, never omitted, so the
    hero always shows the full ladder + names the gap)."""
    return build_cv_question_table(headline, _QUESTIONS)


__all__ = ["mechanism_question_table"]
