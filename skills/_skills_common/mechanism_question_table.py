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

from _skills_common.question_table_core import conf as _conf, row as _row

# Signal tier → (meter fill 0-5, polarity). Mechanism is DESCRIPTIVE: a present signal INFORMS the MoA
# picture; it never "supports"/"opposes" the nomination.
_SIG_META = {"strong": (5, "informs"), "moderate": (3, "informs"), "weak": (2, "informs"),
             "absent": (1, "informs"), "unmeasured": (0, "none")}


def _sig(tier: str, label: str) -> dict:
    fill, pol = _SIG_META.get(tier, (0, "none"))
    return {"tier": tier, "fill": fill, "polarity": pol, "label": label}


def _axis_row(qid: str, question: str, cv: dict, key: str) -> dict:
    """One row driven by a claim_vector axis atom (signal × corroboration × evidence)."""
    atom = (cv or {}).get(key) or {}
    tier = atom.get("signal", "unmeasured")
    corr = atom.get("corroboration", "unmeasured")
    primary = atom.get("evidence") or "data_unavailable"
    return _row(qid, question, primary, "", _sig(tier, str(tier)),
                _conf(corr, f"corroboration: {corr}"))


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
    cv = (headline or {}).get("claim_vector") or {}
    return [_axis_row(qid, q, cv, key) for qid, q, key in _QUESTIONS]


__all__ = ["mechanism_question_table"]
