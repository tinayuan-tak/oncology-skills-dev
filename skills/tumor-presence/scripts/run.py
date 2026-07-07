#!/usr/bin/env python3
"""tumor-presence — expression status for a single (target, indication).

Consumes 2 expression cards + expression-* rule subset. Emits a data-package
output tree with a rank-ordered presence verdict.
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

SKILL_NAME = "tumor-presence"
SKILL_VERSION = "1.0.0"

CARDS = [
    "expression-distribution",
    "expression-tumor-vs-adjacent",
]

QUESTION = ("Is {target} expressed in {indication} tumor tissue, and how "
            "does its expression distribute across cancer cell lines vs. "
            "paired tumor/adjacent samples?")


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Rank-ordered verdict from fired rules."""
    fired_by_id = {r["rule_id"]: r for r in fired}

    # Broadly high (highest confidence positive)
    if "expression-broadly-high-supportive" in fired_by_id:
        return "broadly_high_expression", "expression-broadly-high-supportive"
    # Strongly upregulated in tumor
    if "expression-strong-upregulation-supportive" in fired_by_id:
        return "strongly_upregulated_in_tumor", "expression-strong-upregulation-supportive"
    # Lineage-restricted (also supportive)
    if "expression-lineage-restricted-supportive" in fired_by_id:
        return "lineage_restricted", "expression-lineage-restricted-supportive"
    # Modestly upregulated (neutral tier)
    if "expression-modest-upregulation-neutral" in fired_by_id:
        return "modestly_upregulated_in_tumor", "expression-modest-upregulation-neutral"
    # Broadly moderate expression
    if "expression-broadly-moderate-neutral" in fired_by_id:
        return "broadly_moderate_expression", "expression-broadly-moderate-neutral"
    # Broadly low expression (degrader-killer signal)
    if "expression-broadly-low-degrader-killer" in fired_by_id:
        return "broadly_low_expression", "expression-broadly-low-degrader-killer"
    # Call not informative
    if "expression-call-not-informative-degrader-killer" in fired_by_id:
        return "not_informative", "expression-call-not-informative-degrader-killer"
    # Data unavailable
    for rid in ("expression-data-unavailable-insufficient",
                "expression-call-data-unavailable-insufficient"):
        if rid in fired_by_id:
            return "data_unavailable", rid

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

    headline = {
        "presence_verdict":       verdict,
        "driving_rule_id":        driving_rule,
        "median_log2tpm_panel":   _get("expression-distribution",
                                       "median_log2tpm_panel"),
        "expression_call_class":  _get("expression-distribution",
                                       "expression_call_class"),
        "tva_log2_fc":            _get("expression-tumor-vs-adjacent", "log2_fc"),
        "tva_q_value":            _get("expression-tumor-vs-adjacent", "q_value"),
        "tva_expression_call":    _get("expression-tumor-vs-adjacent",
                                       "expression_call_class"),
        "cards_available":        sum(1 for c in cards if not c.get("_missing")),
        "cards_missing":          [c["card_id"] for c in cards if c.get("_missing")],
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
