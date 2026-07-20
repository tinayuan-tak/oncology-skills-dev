#!/usr/bin/env python3
"""functional-requirement — is target X a genetic dependency in indication Y.

Consumes 5 dependency-relevant cards (CRISPR + RNAi + concordance +
lineage-selectivity + paralog-buffering) + the dependency-* rule subset.

W4d refactor (2026-07-09): calls the shared run_wired_skill dispatcher.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill
from _skills_common.resolver import resolve_verdict_for_gate


SKILL_NAME = "functional-requirement"
SKILL_VERSION = "1.1.0"

CARDS = [
    "pan-cancer-crispr-dependency-distribution",
    "pan-cancer-rnai-dependency-distribution",
    "crispr-rnai-dependency-concordance",
    "dependency-lineage-selectivity",
    "paralog-buffering",                        # Layer 6d addition
    "prism-crispr-concordance",                 # E-PRISM re-home 2026-07-20 — chemical-genetic
                                                # CONFIRMATION arm (gate C). Its triangulated_target_engaged
                                                # class fires e7-triangulated-target-engaged-supportive, which
                                                # the dependency resolver now reads as
                                                # chemical_genetic_confirmed_dependent (a positive-only,
                                                # veto-safe confirmation). The card is ALSO in tractability-
                                                # small-molecule's CARDS (E1: "a compound was found") — one
                                                # measurement routes many-to-many to gates; each gate's
                                                # resolver/snapshot reads only its own rule_ids.
]

QUESTION = ("Is {target} a genetic dependency in {indication}, and how does "
            "the call hold up across CRISPR, RNAi, concordance, lineage-"
            "selectivity, and paralog-buffering views?")


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Verdict — DELEGATES to the shared declarative resolver (gap #5, 2026-07-20).
    The former if-chain now lives in resolvers/dependency.resolver.yaml (target-contracts),
    evaluated by the ONE interpreter both engines call. Proven byte-for-byte equivalent to
    the former if-chain by the golden-oracle test. A missing spec raises (the resolver is
    the source of truth — no silent fallback to a stale copy, which would reintroduce drift)."""
    result = resolve_verdict_for_gate(fired, "dependency")
    if result is None:
        raise RuntimeError(
            "dependency resolver spec missing (target-contracts/resolvers/dependency.resolver.yaml) "
            "— the verdict source of truth is absent.")
    return result

def _headline(cards, fired, verdict_pair):
    def _get(cid: str, key: str):
        for c in cards:
            if c["card_id"] == cid:
                return (c["summary"] or {}).get(key)
        return None

    v, drv = verdict_pair or ("insufficient", None)
    return {
        "dependency_verdict":       v,
        "driving_rule_id":          drv,
        "crispr_call":              _get("pan-cancer-crispr-dependency-distribution",
                                          "dependency_class"),
        "rnai_call":                _get("pan-cancer-rnai-dependency-distribution",
                                          "dependency_class"),
        "concordance_call":         _get("crispr-rnai-dependency-concordance",
                                          "concordance_class"),
        "lineage_selectivity":      _get("dependency-lineage-selectivity",
                                          "lineage_selectivity_class"),
        "paralog_buffering_class":  _get("paralog-buffering",
                                          "paralog_buffering_class"),
        "strongest_paralog_symbol": _get("paralog-buffering",
                                          "strongest_paralog_symbol"),
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
