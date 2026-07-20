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
from _skills_common.resolver import resolve_verdict_for_gate


SKILL_NAME = "tumor-selectivity"
SKILL_VERSION = "1.1.0"

CARDS = ["tumor-vs-normal-selectivity"]

QUESTION = ("How selectively is {target} expressed in {indication} tumor "
            "tissue, and how robust is that call across independent tumor-vs-"
            "normal comparators (TCGA-adjacent raw + ComBat, GTEx-population "
            "raw)?")


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Tumor-vs-normal selectivity verdict — DELEGATES to the shared declarative
    resolver (gap #5, 2026-07-20). The if-chain that used to live here is now
    resolvers/selectivity.resolver.yaml (target-contracts), evaluated by the ONE
    interpreter both engines call. Proven byte-for-byte equivalent to the former
    if-chain by the golden-oracle test (test_resolver_flat_gates_oracle.py). A missing
    spec raises (the resolver is now the source of truth — NO silent fallback to a stale
    copy, which would reintroduce the drift this refactor eliminates)."""
    result = resolve_verdict_for_gate(fired, "selectivity")
    if result is None:
        raise RuntimeError(
            "selectivity resolver spec missing (target-contracts/resolvers/"
            "selectivity.resolver.yaml) — the verdict source of truth is absent.")
    return result


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
