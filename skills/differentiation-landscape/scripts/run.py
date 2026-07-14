#!/usr/bin/env python3
"""differentiation-landscape — Phase-E partial skill (graduated 2026-07-08).

Co-mutation + mutual-exclusivity landscape from panel-intersect-aware Fisher
scan across TCGA MC3 + GENIE 19.0-public.

W4c refactor (2026-07-09): calls the shared run_wired_skill dispatcher.
Skill-specific logic reduces to CARDS + verdict + headline callbacks.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill


SKILL_NAME = "differentiation-landscape"
SKILL_VERSION = "1.2.0"

CARDS = ["co-mutation-and-mutual-exclusivity"]

QUESTION = ("What genes co-occur with or are mutually exclusive to "
            "{target} mutations across TCGA MC3 + GENIE 19.0-public, "
            "and what patient-selection or combination-biology hypotheses "
            "does the pattern support in {indication}?")

PARTIAL_STATUS_NOTE = (
    "differentiation-landscape is status: partial; clinical-precedent + "
    "patent-landscape cards not wired (licensing pending). Only co-mutation "
    "signal reflected in this decision."
)


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Map fired rule_ids to a verdict, rank-ordered most-informative first.

    Must cover EVERY cooccurrence rule the target-contracts axis can fire
    (added 2026-07-14): the 5 cooccurrence_class-keyed rows + the pre-existing
    has-cooccurring-driver + data-unavailable rows. A fired rule with no
    branch here would silently fall through to `insufficient` — the exact
    decision-layer collapse this precedence list closes.
    """
    fired_by_id = {r["rule_id"]: r for r in fired}
    # (rule_id, verdict) in strict precedence order.
    precedence = [
        ("cooccurrence-both-patterns-supportive",        "both_patterns_present"),
        ("strong-mutual-exclusivity-supportive",         "strong_mutually_exclusive"),
        ("cooccurrence-strong-supportive",               "strong_cooccurring"),
        ("has-cooccurring-driver-supportive",            "has_cooccurring_driver"),
        ("cooccurrence-modest-cooccurring-neutral",      "modest_cooccurring"),
        ("cooccurrence-modest-mutually-exclusive-neutral", "modest_mutually_exclusive"),
        ("cooccurrence-ns-not-informative",              "ns"),
        ("cooccurrence-data-unavailable-insufficient",   "data_unavailable"),
    ]
    for rule_id, verdict in precedence:
        if rule_id in fired_by_id:
            return verdict, rule_id
    return "insufficient", None


def _headline(cards, fired, verdict_pair):
    def _get(cid: str, key: str):
        for c in cards:
            if c["card_id"] == cid:
                return (c["summary"] or {}).get(key)
        return None

    v, drv = verdict_pair or ("insufficient", None)
    return {
        "differentiation_verdict":          v,
        "driving_rule_id":                  drv,
        "cooccurrence_class":               _get("co-mutation-and-mutual-exclusivity",
                                                 "cooccurrence_class"),
        "n_significant_cooccurring":        _get("co-mutation-and-mutual-exclusivity",
                                                 "n_significant_cooccurring"),
        "n_significant_mutually_exclusive": _get("co-mutation-and-mutual-exclusivity",
                                                 "n_significant_mutually_exclusive"),
        "n_pairs_panel_intersect_eligible": _get("co-mutation-and-mutual-exclusivity",
                                                 "n_pairs_panel_intersect_eligible"),
        "n_pairs_per_source_only":          _get("co-mutation-and-mutual-exclusivity",
                                                 "n_pairs_per_source_only"),
        "has_cooccurring_driver":           _get("co-mutation-and-mutual-exclusivity",
                                                 "has_cooccurring_driver"),
        "has_mutually_exclusive_driver":    _get("co-mutation-and-mutual-exclusivity",
                                                 "has_mutually_exclusive_driver"),
        "top_cooccurring":                  _get("co-mutation-and-mutual-exclusivity",
                                                 "top_cooccurring"),
        "top_mutually_exclusive":           _get("co-mutation-and-mutual-exclusivity",
                                                 "top_mutually_exclusive"),
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
        partial_status_note=PARTIAL_STATUS_NOTE,
    ))
