#!/usr/bin/env python3
"""tumor-selectivity — tumor-vs-normal selectivity for a single (target, indication).

Reuses compose-dashboard's live-reader + rule engine via the _skills_common
harness. Zero new dispatcher logic, zero new rule content.

Output: data-package tree (decision.json + summary.yaml + tables/ +
figures/ + provenance.yaml) at --out.
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

SKILL_NAME = "tumor-selectivity"
SKILL_VERSION = "1.0.0"
CARD_ID = "tumor-vs-normal-selectivity"
QUESTION = ("How selectively is {target} expressed in {indication} tumor tissue, "
            "and how robust is that call across independent tumor-vs-normal "
            "comparators (TCGA-adjacent raw + ComBat, GTEx-population raw)?")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--modality", default=None,
                    help="OPTIONAL post-hoc modality lens: "
                         "small_molecule | degrader | adc | bite | antibody. "
                         "When supplied, adds modality_lenses to decision.json "
                         "and records the lens in provenance.yaml.")
    args = ap.parse_args()

    cards = resolve_cards([CARD_ID], args.target, args.indication)
    tvn = cards[0]["summary"] or {}

    headline = {
        "selectivity_class":   tvn.get("selectivity_class"),
        "cells_supporting":    tvn.get("cells_supporting"),
        "cells_ran":           tvn.get("cells_ran"),
        "dominant_direction":  tvn.get("dominant_direction"),
        "discordant":          tvn.get("discordant"),
        "sig_all_cells":       tvn.get("sig_all_cells"),
        "max_abs_log2fc":      tvn.get("max_abs_log2fc"),
        "data_schema":         tvn.get("_schema"),
    }

    fired = fired_rules(cards, axis="intracellular_intrinsic",
                        card_id_filter=[CARD_ID])

    # Optional modality lens (biology-first: only included when user supplies it).
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
    print(f"  decision:   {written['decision'].name}")
    print(f"  summary:    {written['summary'].name}")
    print(f"  provenance: {written['provenance'].name}")
    print(f"  tables:     {len(written['tables'])} files")
    print(f"  figures:    {len(written['figures'])} files")
    print()
    print(json.dumps(headline, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
