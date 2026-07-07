#!/usr/bin/env python3
"""Micro — dependency-in-indication for a single (target, indication).

Consumes 4 dependency-relevant cards + the dependency-* rule subset. Emits
decision.json with a rank-ordered verdict.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _micro_common import (
    resolve_cards, fired_rules, modality_lens,
    make_decision_json, write_decision,
)

CARDS = [
    "pan-cancer-crispr-dependency-distribution",
    "pan-cancer-rnai-dependency-distribution",
    "crispr-rnai-dependency-concordance",
    "dependency-lineage-selectivity",
]

QUESTION = ("Is {target} a genetic dependency in {indication}, and how does "
            "the call hold up across CRISPR, RNAi, concordance, and lineage-"
            "selectivity views?")


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Rank-ordered verdict resolution. Returns (verdict, driving_rule_id)."""
    fired_by_id = {r["rule_id"]: r for r in fired}

    # 1. Any killer-dominant rule fires → pan-essential-killer or rnai variant
    for rid in ("pan-essential-killer", "rnai-pan-essential-killer"):
        if rid in fired_by_id:
            return "pan_essential_killer", rid

    # 2. Concordant-dependent (dominant) → highest-confidence positive
    if "concordant-dependent-supportive-dominant" in fired_by_id:
        return "concordant_dependent", "concordant-dependent-supportive-dominant"

    # 3. Lineage-selective
    if "lineage-selective-supportive" in fired_by_id:
        return "lineage_selective", "lineage-selective-supportive"

    # 4. Selective per CRISPR or RNAi alone (both individually meaningful)
    for rid in ("strongly-selective-supportive", "rnai-strongly-selective-supportive"):
        if rid in fired_by_id:
            return "selective_dependent", rid

    # 5. Discordant between CRISPR + RNAi
    if "concordance-discordant-warning" in fired_by_id:
        return "discordant", "concordance-discordant-warning"

    # 6. Non-dependent (CRISPR-side killer OR RNAi-side neutral)
    for rid in ("non-dependent-killer", "rnai-non-dependent-neutral"):
        if rid in fired_by_id:
            return "non_dependent", rid

    # 7. Broadly dependent (non-specific — not a differentiator)
    for rid in ("broadly-dependent-neutral", "rnai-broadly-dependent-neutral"):
        if rid in fired_by_id:
            return "broadly_dependent", rid

    return "insufficient", None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    cards = resolve_cards(CARDS, args.target, args.indication)
    fired = fired_rules(cards, axis="intracellular_intrinsic",
                        card_id_filter=CARDS)
    verdict, driving_rule = _verdict(fired)

    def _get(cid: str, key: str):
        for c in cards:
            if c["card_id"] == cid:
                return (c["summary"] or {}).get(key)
        return None

    headline = {
        "dependency_verdict":   verdict,
        "driving_rule_id":      driving_rule,
        "crispr_call":          _get("pan-cancer-crispr-dependency-distribution",
                                     "dependency_class"),
        "rnai_call":            _get("pan-cancer-rnai-dependency-distribution",
                                     "dependency_class"),
        "concordance_call":     _get("crispr-rnai-dependency-concordance",
                                     "concordance_class"),
        "lineage_selectivity":  _get("dependency-lineage-selectivity",
                                     "lineage_selectivity_class"),
        "cards_available":      sum(1 for c in cards if not c.get("_missing")),
        "cards_missing":        [c["card_id"] for c in cards if c.get("_missing")],
    }
    lenses = {m: modality_lens(fired, m) for m in ("small_molecule", "degrader")}

    decision = make_decision_json(
        skill_name="micro-dependency-in-indication",
        target=args.target, indication=args.indication,
        question=QUESTION.format(target=args.target, indication=args.indication),
        card_outputs=cards, fired=fired,
        headline=headline, modality_lenses=lenses,
    )
    out_path = write_decision(decision, args.out)
    print(f"wrote {out_path}")
    print(json.dumps(headline, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
