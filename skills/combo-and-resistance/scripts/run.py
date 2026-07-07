#!/usr/bin/env python3
"""combo-and-resistance — placeholder skill for un-wired Phase-I question.

Emits a structured decision.json naming the wiring gaps. See SKILL.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common import emit_placeholder

SKILL_NAME = "combo-and-resistance"
SKILL_VERSION = "1.0.0"
PHASE = "I"
QUESTION = 'When target X is inhibited, what emerges — combination opportunities, resistance signatures?'
REQUIRED_CARDS = [
    'combo-crispr-screen',
    'resistance-emergence-signature',
]
UNWIRED_CARDS = [
    'combo-crispr-screen',
    'resistance-emergence-signature',
]
DATA_GAPS = [
    'Combo CRISPR screens (some exist in DepMap; method not written)',
    'Resistance-emergence-signature source (paired pre/post-tx expression / mutation) not catalogued',
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    path = emit_placeholder(
        out_dir=args.out,
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        target=args.target,
        indication=args.indication,
        phase=PHASE,
        question=QUESTION,
        required_cards=REQUIRED_CARDS,
        unwired_cards=UNWIRED_CARDS,
        data_gaps=DATA_GAPS,
    )
    print(f"wrote placeholder decision.json to {path}")
    print(f"phase: Phase-{PHASE}, status: not_wired")
    print(f"data gaps ({len(DATA_GAPS)}):")
    for g in DATA_GAPS:
        print(f"  - {g}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
