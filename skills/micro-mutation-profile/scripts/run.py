#!/usr/bin/env python3
"""Micro — mutation profile for a single (target, indication).

Consumes 3 mutation-oriented cards + mut-* + mutant-* rule subsets. Emits
decision.json with a rank-ordered mutation-profile verdict.
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
    "mutation-type-counts",
    "mutation-stratified-dependency",
    "mutation-hotspot-frequency",
]

QUESTION = ("What is {target}'s mutation profile in {indication} — is it a "
            "recurrent driver, a mutation-stratified dependency biomarker, "
            "or a passenger?")


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Rank-ordered verdict from fired rules. Returns (verdict, driving_rule_id)."""
    fired_by_id = {r["rule_id"]: r for r in fired}
    # 1. Strongest — mut-vs-WT dependency biomarker
    if "mutant-strongly-dependent-supportive" in fired_by_id:
        return "biomarker_stratified_dependency", "mutant-strongly-dependent-supportive"
    if "mutant-moderately-dependent-supportive" in fired_by_id:
        return "moderate_biomarker_dependency", "mutant-moderately-dependent-supportive"
    # 2. Variant-class dominance (mutation-type-counts card)
    if "mut-lof-dominant-supportive" in fired_by_id:
        return "recurrent_lof_driver", "mut-lof-dominant-supportive"
    if "mut-missense-dominant-supportive" in fired_by_id:
        return "recurrent_missense_driver", "mut-missense-dominant-supportive"
    # 3. Mixed / neutral / passenger
    if "mut-mixed-neutral" in fired_by_id:
        return "mixed_pattern", "mut-mixed-neutral"
    if "mut-no-mutations-neutral" in fired_by_id:
        return "passenger_pattern", "mut-no-mutations-neutral"
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
        "mutation_profile":            verdict,
        "driving_rule_id":             driving_rule,
        "variant_class_pattern":       _get("mutation-type-counts",
                                            "variant_class_pattern"),
        "mut_dependency_signal":       _get("mutation-stratified-dependency",
                                            "mut_dependency_class"),
        # hotspot-frequency card has no Tier-2 rules but its summary carries
        # tumor-cohort metrics we surface as raw color:
        "hotspot_top_residue":         _get("mutation-hotspot-frequency",
                                            "top_hotspot"),
        "hotspot_frequency":           _get("mutation-hotspot-frequency",
                                            "hotspot_frequency"),
        "tumor_mutation_rate_pct":     _get("mutation-hotspot-frequency",
                                            "mutation_rate_percent"),
        "cards_available":             sum(1 for c in cards if not c.get("_missing")),
        "cards_missing":               [c["card_id"] for c in cards if c.get("_missing")],
    }
    lenses = {m: modality_lens(fired, m) for m in ("small_molecule", "degrader")}

    decision = make_decision_json(
        skill_name="micro-mutation-profile",
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
