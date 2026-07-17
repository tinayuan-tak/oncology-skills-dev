#!/usr/bin/env python3
"""tumor-selectivity — tumor-vs-normal selectivity for a single (target, indication).

W4d refactor (2026-07-09): calls the shared run_wired_skill dispatcher.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill


SKILL_NAME = "tumor-selectivity"
SKILL_VERSION = "1.1.0"

CARDS = ["tumor-vs-normal-selectivity"]

QUESTION = ("How selectively is {target} expressed in {indication} tumor "
            "tissue, and how robust is that call across independent tumor-vs-"
            "normal comparators (TCGA-adjacent raw + ComBat, GTEx-population "
            "raw)?")


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Rank-ordered tumor-vs-normal selectivity verdict (first match wins).

    Added 2026-07-17: tumor-selectivity previously passed NO verdict_fn, so
    _run_sub_skills recorded verdict=None and the entire Phase-B selectivity
    signal — a first-order nomination criterion (a non-tumor-selective target is
    an on-target-toxicity liability) — never reached synthesis, the nomination
    gate, or the 6-category risk table. It was computed (selectivity_class) and
    silently dropped.

    Keys off the tvn-* rules that fire on the card's selectivity_class (mirrors
    tractability-small-molecule's _snapshot pattern). Verdict strings are the
    selectivity_class values verbatim so the risk-table reshape's _biological()
    — which already checks for strong_tumor_selective / not_selective — picks
    them up without a translation layer.
    """
    fired_by_id = {r["rule_id"]: r for r in fired}
    if "tvn-strong-selective-supportive" in fired_by_id:
        return "strong_tumor_selective", "tvn-strong-selective-supportive"
    if "tvn-modest-selective-supportive" in fired_by_id:
        return "modest_tumor_selective", "tvn-modest-selective-supportive"
    if "tvn-discordant-neutral-flagged" in fired_by_id:
        return "discordant_across_comparators", "tvn-discordant-neutral-flagged"
    if "tvn-not-selective-neutral" in fired_by_id:
        return "not_selective", "tvn-not-selective-neutral"
    if "tvn-not-informative-neutral" in fired_by_id:
        return "not_informative", "tvn-not-informative-neutral"
    if "tvn-data-unavailable-insufficient" in fired_by_id:
        return "data_unavailable", "tvn-data-unavailable-insufficient"
    return "insufficient", None


def _headline(cards, fired, verdict_pair):
    tvn = (cards[0]["summary"] or {}) if cards else {}
    return {
        "selectivity_class":  tvn.get("selectivity_class"),
        "cells_supporting":   tvn.get("cells_supporting"),
        "cells_ran":          tvn.get("cells_ran"),
        "dominant_direction": tvn.get("dominant_direction"),
        "discordant":         tvn.get("discordant"),
        "sig_all_cells":      tvn.get("sig_all_cells"),
        "max_abs_log2fc":     tvn.get("max_abs_log2fc"),
        "data_schema":        tvn.get("_schema"),
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
    ))
