#!/usr/bin/env python3
"""differentiation-landscape — placeholder skill for un-wired Phase-E question.

Emits a structured decision.json naming the wiring gaps. See SKILL.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common import emit_placeholder

SKILL_NAME = "differentiation-landscape"
SKILL_VERSION = "1.0.0"
PHASE = "E"
QUESTION = 'How does target X differentiate from portfolio + competitive landscape — precedent, patents, novelty, paralog buffering, co-occurrence?'
REQUIRED_CARDS = [
    'clinical-precedent',
    'patent-landscape',
    'paralog-buffering',
    'co-occurrence-and-mutual-exclusivity',
]
UNWIRED_CARDS = [
    'clinical-precedent',
    'patent-landscape',
    'paralog-buffering',
    'co-occurrence-and-mutual-exclusivity',
]
DATA_GAPS = [
    'Clinical-precedent feed (Cortellis / IQVIA) not licensed',
    'Patent landscape (PatBase or similar) not wired',
    'Paralog-buffering — adjacent SL work produces some of this; needs wiring into a dedicated card',
    'Co-occurrence/mutual-exclusivity partial (mutation-hotspot-frequency card shows lists but no dedicated skill)',
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
