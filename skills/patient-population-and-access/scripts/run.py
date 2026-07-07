#!/usr/bin/env python3
"""patient-population-and-access — mutation prevalence in an indication cohort.

Thin-scoped Phase-H skill: consumes only the mutation-hotspot-frequency card
(TCGA MC3 MAF). No rules currently target this card_id so `fired_rules` will
be empty; the skill surfaces raw cohort metrics directly to the headline.

Subgroup-stratified expression + RWD-stratified expression cards are declared
in the dispatch table but not wired — those Phase-H subquestions are named
in the SKILL.md coverage-gaps section.
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

SKILL_NAME = "patient-population-and-access"
SKILL_VERSION = "1.0.0"

CARDS = ["mutation-hotspot-frequency"]

QUESTION = ("How prevalent is {target}'s mutation footprint in {indication}'s "
            "patient population, and what are the top recurrent hotspots?")


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

    hotspot = cards[0].get("summary") or {}
    top_hs = None
    if isinstance(hotspot.get("hotspot_frequencies"), list) \
       and hotspot["hotspot_frequencies"]:
        top_hs = hotspot["hotspot_frequencies"][0]

    headline = {
        "overall_mutation_frequency":  hotspot.get("overall_mutation_frequency"),
        "n_samples_in_indication":     hotspot.get("n_samples_in_indication"),
        "n_samples_mutated":           hotspot.get("n_samples_mutated"),
        "top_hotspot_residue":         (top_hs or {}).get("protein_change"),
        "top_hotspot_n_samples":       (top_hs or {}).get("n_samples"),
        "top_hotspot_frequency":       (top_hs or {}).get("frequency"),
        "n_recurrent_hotspots":        len(hotspot.get("hotspot_frequencies") or []),
        "top_cooccurring_genes":       hotspot.get("top_cooccurring_genes") or [],
        "top_mutually_exclusive_genes": hotspot.get("top_mutually_exclusive_genes") or [],
        "cards_available":             sum(1 for c in cards if not c.get("_missing")),
        "cards_missing":               [c["card_id"] for c in cards if c.get("_missing")],
        "coverage_note": ("Thin-scoped Phase-H skill. Subgroup-stratified + "
                          "RWD-stratified prevalence not covered — see "
                          "SKILL.md coverage-gaps section."),
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
    # Print headline minus long lists.
    printable = {k: v for k, v in headline.items()
                 if k not in ("top_cooccurring_genes", "top_mutually_exclusive_genes")}
    printable["cooccurring_count"] = len(headline["top_cooccurring_genes"])
    printable["mutually_excl_count"] = len(headline["top_mutually_exclusive_genes"])
    print(json.dumps(printable, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
