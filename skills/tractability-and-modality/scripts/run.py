#!/usr/bin/env python3
"""tractability-and-modality — chemical-genetic druggability snapshot.

Consumes 3 chemical-genetic cards + the prism-* / predictability-* / E7 rule
subsets. Emits a data-package output tree with a rank-ordered druggability
snapshot and optional modality-lensed viability tally.
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

SKILL_NAME = "tractability-and-modality"
SKILL_VERSION = "1.0.0"

CARDS = [
    "prism-compound-activity",
    "prism-crispr-concordance",
    "dependency-predictability",
]

QUESTION = ("Does {target} in {indication} show chemical-genetic druggability "
            "evidence — is there a compound that hits it, and does the "
            "compound signal concord with the CRISPR/RNAi dependency?")


def _snapshot(fired: list[dict]) -> tuple[str, str | None]:
    """Rank-ordered snapshot resolution."""
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
    snapshot, driving_rule = _snapshot(fired)

    def _get(cid: str, key: str):
        for c in cards:
            if c["card_id"] == cid:
                return (c["summary"] or {}).get(key)
        return None

    headline = {
        "druggability_snapshot":   snapshot,
        "driving_rule_id":         driving_rule,
        "prism_activity_class":    _get("prism-compound-activity",
                                        "activity_class"),
        "prism_crispr_concord":    _get("prism-crispr-concordance",
                                        "concordance_class"),
        "predictability_class":    _get("dependency-predictability",
                                        "predictability_class"),
        "cards_available":         sum(1 for c in cards if not c.get("_missing")),
        "cards_missing":           [c["card_id"] for c in cards if c.get("_missing")],
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
