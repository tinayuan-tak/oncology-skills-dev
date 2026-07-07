#!/usr/bin/env python3
"""mutation-profile — mutation profile for a single (target, indication).

Consumes 3 mutation-oriented cards + mut-* + mutant-* rule subsets. Emits
a data-package output tree with a rank-ordered mutation-profile verdict.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common import (
    resolve_cards, fired_rules, modality_lens,
    make_decision_json, write_package,
)

SKILL_NAME = "mutation-profile"
SKILL_VERSION = "1.0.0"

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
    if "mutant-strongly-dependent-supportive" in fired_by_id:
        return "biomarker_stratified_dependency", "mutant-strongly-dependent-supportive"
    if "mutant-moderately-dependent-supportive" in fired_by_id:
        return "moderate_biomarker_dependency", "mutant-moderately-dependent-supportive"
    if "mut-lof-dominant-supportive" in fired_by_id:
        return "recurrent_lof_driver", "mut-lof-dominant-supportive"
    if "mut-missense-dominant-supportive" in fired_by_id:
        return "recurrent_missense_driver", "mut-missense-dominant-supportive"
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
    ap.add_argument("--modality", default=None,
                    help="OPTIONAL post-hoc modality lens.")
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

    # Use ACTUAL summary field names from live card outputs (verified via
    # smoke test earlier — see mutation-profile smoke on TP53).
    headline = {
        "mutation_profile":              verdict,
        "driving_rule_id":               driving_rule,
        "mutation_landscape_class":      _get("mutation-type-counts",
                                              "mutation_landscape_class"),
        "mutation_stratification_class": _get("mutation-stratified-dependency",
                                              "mutation_stratification_class"),
        "overall_mutation_frequency":    _get("mutation-hotspot-frequency",
                                              "overall_mutation_frequency"),
        "cards_available":               sum(1 for c in cards if not c.get("_missing")),
        "cards_missing":                 [c["card_id"] for c in cards if c.get("_missing")],
    }

    lenses = None
    invoked_lenses: dict = {}
    if args.modality:
        lenses = {args.modality: modality_lens(fired, args.modality)}
        invoked_lenses["modality"] = args.modality

    decision = make_decision_json(
        skill_name=SKILL_NAME,
        target=args.target, indication=args.indication,
        question=QUESTION.format(target=args.target, indication=args.indication),
        card_outputs=cards, fired=fired,
        headline=headline, modality_lenses=lenses,
    )

    written = write_package(
        out_dir=args.out,
        decision=decision,
        card_outputs=cards,
        target=args.target,
        indication=args.indication,
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        invoked_lenses=invoked_lenses,
    )
    print(f"wrote data-package to {args.out}")
    print(f"  tables: {len(written['tables'])}  figures: {len(written['figures'])}")
    print()
    print(json.dumps(headline, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
