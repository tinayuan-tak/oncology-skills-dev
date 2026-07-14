#!/usr/bin/env python3
"""tractability-small-molecule — chemical-genetic small-molecule druggability.

Consumes the 3 chemical-genetic cards (prism-compound-activity,
prism-crispr-concordance, dependency-predictability) + the prism-* /
predictability-* / E7 rule subsets. Emits a data-package output tree with a
rank-ordered small-molecule druggability snapshot.

SPLIT 2026-07-14: this is the small-molecule half of the former
`tractability-and-modality` skill. That skill had grown to 9 cards, but 6 of
them (surface topology / family / structure / density / adc-tce-fit / cohort-
ranking) could NOT change its verdict — the `_snapshot()` keys entirely off
the 3 chemical-genetic rules. Those 6 surface cards were split out into the
sibling `surface-modality-fit` skill, which makes the biologics-modality call
this skill previously only displayed. See docs/SKILLS_SCOPE_REVIEW_2026-07-14.md.

W4d refactor (2026-07-09): calls the shared run_wired_skill dispatcher.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill


SKILL_NAME = "tractability-small-molecule"
SKILL_VERSION = "3.0.0"     # major bump: split from tractability-and-modality 2.1.0

CARDS = [
    "prism-compound-activity",
    "prism-crispr-concordance",
    "dependency-predictability",
]

QUESTION = ("Does {target} in {indication} show small-molecule chemical-genetic "
            "druggability evidence — is there a compound that hits it, and does "
            "the chemical signal agree with the genetic dependency?")


def _snapshot(fired: list[dict]) -> tuple[str, str | None]:
    """Rank-ordered small-molecule druggability resolution (first match wins).

    Unchanged from tractability-and-modality: this verdict always keyed off the
    e7-* / prism-* chemical-genetic rules only.
    """
    fired_by_id = {r["rule_id"]: r for r in fired}
    if "e7-triangulated-target-engaged-supportive" in fired_by_id:
        return "well_covered", "e7-triangulated-target-engaged-supportive"
    if "e7-crispr-confirmed-supportive-sm" in fired_by_id:
        return "chemically_confirmed_genetic", "e7-crispr-confirmed-supportive-sm"
    if "prism-clinically-active-supportive-sm" in fired_by_id:
        return "chemically_active", "prism-clinically-active-supportive-sm"
    if "prism-tool-compound-only-weak-supportive-sm" in fired_by_id:
        return "tool_compound_only", "prism-tool-compound-only-weak-supportive-sm"
    if "prism-weakly-active-weak-supportive-sm" in fired_by_id:
        return "weakly_active", "prism-weakly-active-weak-supportive-sm"
    if "e7-discordant-off-target-warning" in fired_by_id:
        return "discordant", "e7-discordant-off-target-warning"
    if "prism-no-compounds-found-neutral" in fired_by_id:
        return "chemically_unhit", "prism-no-compounds-found-neutral"
    return "insufficient", None


def _headline(cards, fired, verdict_pair):
    def _get(cid: str, key: str):
        for c in cards:
            if c["card_id"] == cid:
                return (c["summary"] or {}).get(key)
        return None

    v, drv = verdict_pair or ("insufficient", None)
    return {
        "druggability_snapshot":     v,
        "driving_rule_id":           drv,
        "prism_activity_class":      _get("prism-compound-activity", "activity_class"),
        "prism_crispr_concord":      _get("prism-crispr-concordance", "concordance_class"),
        "predictability_class":      _get("dependency-predictability", "predictability_class"),
    }


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="intracellular_intrinsic",
        question=QUESTION,
        verdict_fn=_snapshot,
        headline_fn=_headline,
    ))
