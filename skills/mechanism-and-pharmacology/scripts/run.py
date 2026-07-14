#!/usr/bin/env python3
"""mechanism-and-pharmacology — Phase-D wired skill (graduated 2026-07-08).

Signaling-network mechanism + candidate MoA hooks + PD-marker suggestions.
Consumes the signaling-network-mechanism card (SIGNOR-tagged edges from
OmniPath, classified into a 21-class MoA ontology). Emits a data-package
output tree with rule-derived per-modality signals.

W4c refactor (2026-07-09): now uses the shared
_skills_common.dispatcher.run_wired_skill(...) entry point. Skill-
specific logic (CARDS list + verdict + headline) shrinks to a few
callbacks; boilerplate (arg parsing, resolve_cards, fired_rules,
modality-lens wiring, write_package) moves into the dispatcher. The
previous inline implementation is removed; behavior is equivalent.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill


SKILL_NAME = "mechanism-and-pharmacology"
SKILL_VERSION = "1.2.0"                       # bumped for W4c dispatcher refactor

CARDS = [
    "signaling-network-mechanism",
]

QUESTION = ("For {target} in {indication}, what upstream regulators + "
            "downstream effectors are catalogued in SIGNOR, and which MoA "
            "classes are candidate hooks for SM / degrader / molecular-glue "
            "programs?")


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Rank-ordered verdict from fired rules.

    Precedence (most-informative first):
      1. well_characterized (>=3 upstream AND >=3 downstream partners)
      2. has_pd_marker (>=1 downstream effector; supportive signal)
      3. partial (some context, between sparse and well_characterized)
      4. sparse (0-1 total edges — reviewer-added warning signal)
      5. data_unavailable (target not in SIGNOR snapshot)

    The `partial` branch was added 2026-07-14 alongside the
    mechanism-partial-neutral rule: the reader emits network_class=partial as
    its fall-through class, but with no branch here a partial-network target
    fired the rule yet still collapsed to `insufficient`.
    """
    fired_by_id = {r["rule_id"]: r for r in fired}

    if "mechanism-well-characterized-supportive" in fired_by_id:
        return "well_characterized", "mechanism-well-characterized-supportive"
    if "has-pd-marker-supportive" in fired_by_id:
        return "has_pd_marker", "has-pd-marker-supportive"
    if "mechanism-partial-neutral" in fired_by_id:
        return "partial", "mechanism-partial-neutral"
    if "mechanism-sparse-warning" in fired_by_id:
        return "sparse", "mechanism-sparse-warning"
    if "mechanism-data-unavailable-insufficient" in fired_by_id:
        return "data_unavailable", "mechanism-data-unavailable-insufficient"

    return "insufficient", None


def _headline(cards, fired, verdict_pair):
    """Skill-specific headline: SIGNOR-network descriptive fields."""
    def _get(cid: str, key: str):
        for c in cards:
            if c["card_id"] == cid:
                return (c["summary"] or {}).get(key)
        return None

    v, drv = verdict_pair or ("insufficient", None)
    return {
        "mechanism_verdict":         v,
        "driving_rule_id":           drv,
        "network_class":             _get("signaling-network-mechanism",
                                          "network_class"),
        "n_upstream_regulators":     _get("signaling-network-mechanism",
                                          "n_upstream_regulators"),
        "n_downstream_effectors":    _get("signaling-network-mechanism",
                                          "n_downstream_effectors"),
        "moa_classes_present":       _get("signaling-network-mechanism",
                                          "moa_classes_present"),
        "pd_marker_classes_present": _get("signaling-network-mechanism",
                                          "pd_marker_classes_present"),
        "has_actionable_moa":        _get("signaling-network-mechanism",
                                          "has_actionable_moa"),
        "has_pd_marker":             _get("signaling-network-mechanism",
                                          "has_pd_marker"),
        "moa_ontology_version":      _get("signaling-network-mechanism",
                                          "moa_ontology_version"),
    }


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="intracellular_intrinsic",
        question=QUESTION,
        verdict_fn=_verdict,
        headline_fn=_headline,
        isoform_check_target=True,          # arch A3: warn on p95HER2 / AR-V7 / etc.
    ))
