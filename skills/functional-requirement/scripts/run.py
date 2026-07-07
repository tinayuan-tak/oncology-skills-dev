#!/usr/bin/env python3
"""functional-requirement — is target X a genetic dependency in indication Y.

Consumes 4 dependency-relevant cards + the dependency-* rule subset. Emits
a data-package output tree with a rank-ordered dependency verdict.
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

SKILL_NAME = "functional-requirement"
SKILL_VERSION = "1.0.0"

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

    for rid in ("pan-essential-killer", "rnai-pan-essential-killer"):
        if rid in fired_by_id:
            return "pan_essential_killer", rid

    if "concordant-dependent-supportive-dominant" in fired_by_id:
        return "concordant_dependent", "concordant-dependent-supportive-dominant"

    if "lineage-selective-supportive" in fired_by_id:
        return "lineage_selective", "lineage-selective-supportive"

    for rid in ("strongly-selective-supportive", "rnai-strongly-selective-supportive"):
        if rid in fired_by_id:
            return "selective_dependent", rid

    if "concordance-discordant-warning" in fired_by_id:
        return "discordant", "concordance-discordant-warning"

    for rid in ("non-dependent-killer", "rnai-non-dependent-neutral"):
        if rid in fired_by_id:
            return "non_dependent", rid

    for rid in ("broadly-dependent-neutral", "rnai-broadly-dependent-neutral"):
        if rid in fired_by_id:
            return "broadly_dependent", rid

    return "insufficient", None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--modality", default=None,
                    help="OPTIONAL post-hoc modality lens: "
                         "small_molecule | degrader | adc | bite | antibody.")
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
