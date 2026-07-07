#!/usr/bin/env python3
"""Micro — tumor-vs-normal selectivity for a single (target, indication).

Reuses compose-dashboard's live-reader + rule engine via the _micro_common
harness. Zero new dispatcher logic, zero new rule content.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Skill is at .../skills/micro-tumor-selectivity/scripts/run.py;
# _micro_common is at .../skills/_micro_common/
SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _micro_common import (
    resolve_cards, fired_rules, modality_lens,
    make_decision_json, write_decision,
)

CARD_ID = "tumor-vs-normal-selectivity"
QUESTION = ("How selectively is {target} expressed in {indication} tumor tissue, "
            "and how robust is that call across independent tumor-vs-normal "
            "comparators (TCGA-adjacent raw + ComBat, GTEx-population raw)?")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--out", required=True, type=Path)
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
    lenses = {m: modality_lens(fired, m) for m in ("small_molecule", "degrader")}

    decision = make_decision_json(
        skill_name="micro-tumor-selectivity",
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
