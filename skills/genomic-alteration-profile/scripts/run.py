#!/usr/bin/env python3
"""genomic-alteration-profile — genomic alteration profile for a (target, indication).

Answers "how is this gene genomically altered in indication Y, and which
alteration class drives?" — spanning SNV/indel (mutation) + copy-number
(amplification/deletion), with fusion/rearrangement as a declared placeholder
until that data lands.

REFRAMED 2026-07-14 from `mutation-profile` (which was SNV/indel only). The
copy-number-distribution card + its 11 rules already existed but were never
composed into a skill — the same gene is often a driver via DIFFERENT
alteration classes across indications (ERBB2 amp in breast/gastric vs mutation
in a lung subset; MET exon14-skip + amplification), so a mutation-only skill
implied "not a driver" for amplification-driven targets. This skill reports the
alteration MIX and which class drives. See docs/SKILLS_SCOPE_REVIEW_2026-07-14.md.

Consumes 4 cards: 3 mutation-oriented + copy-number-distribution. Fusion card
is a declared placeholder (fusion-rearrangement-landscape) pending data.
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

SKILL_NAME = "genomic-alteration-profile"
SKILL_VERSION = "2.0.0"      # major bump: reframed from mutation-profile 1.0.0

CARDS = [
    # SNV / indel (mutation)
    "mutation-type-counts",
    "mutation-stratified-dependency",
    "mutation-hotspot-frequency",
    # Copy number (amplification / deletion) — card + rules already existed
    "copy-number-distribution",
    # Fusion / rearrangement — declared placeholder card (data not yet landed);
    # resolve_cards flags it _missing until the card + method exist.
    "fusion-rearrangement-landscape",
]

QUESTION = ("How is {target} genomically altered in {indication} — by SNV/indel "
            "(driver, biomarker-stratified dependency, or passenger), by copy-"
            "number (amplification/deletion), or a mix — and which class drives?")


def _mutation_verdict(fired_by_id: dict) -> tuple[str | None, str | None]:
    """The SNV/indel axis — unchanged from mutation-profile's rank-order."""
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
    return None, None


def _cn_driver_fired(fired_by_id: dict) -> tuple[bool, str | None]:
    """The copy-number axis — is there a recurrent CN driver event?"""
    if "cn-recurrently-amplified-supportive" in fired_by_id:
        return True, "cn-recurrently-amplified-supportive"
    if "cn-recurrently-deleted-supportive" in fired_by_id:
        return True, "cn-recurrently-deleted-supportive"
    return False, None


# SNV/indel verdicts that represent a genuine driver signal (vs passenger/mixed)
_MUT_DRIVER_VERDICTS = {
    "biomarker_stratified_dependency", "moderate_biomarker_dependency",
    "recurrent_lof_driver", "recurrent_missense_driver",
}


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Multi-class genomic-alteration verdict.

    Primary axis is SNV/indel (carries the strongest therapeutic signals);
    copy-number is layered as a modifier so an amplification/deletion-driven
    target (few mutations) is reported as a CN driver rather than collapsing to
    passenger. Returns (verdict, driving_rule_id).
    """
    fired_by_id = {r["rule_id"]: r for r in fired}
    mut_verdict, mut_rule = _mutation_verdict(fired_by_id)
    cn_driver, cn_rule = _cn_driver_fired(fired_by_id)

    mut_is_driver = mut_verdict in _MUT_DRIVER_VERDICTS

    # Both classes drive → multi-class. Report the mutation rule as primary
    # driver (stronger signal) but flag multi_class.
    if mut_is_driver and cn_driver:
        return "multi_class_driver", mut_rule
    # Only mutation drives → the mutation verdict stands.
    if mut_is_driver:
        return mut_verdict, mut_rule
    # Only CN drives (mutation passenger/mixed/absent) → CN driver.
    if cn_driver:
        cls = "recurrent_amplification_driver" if "amplified" in (cn_rule or "") \
            else "recurrent_deletion_driver"
        return cls, cn_rule
    # Neither class drives → fall back to whatever the mutation axis said
    # (mixed_pattern / passenger_pattern), else insufficient.
    if mut_verdict is not None:
        return mut_verdict, mut_rule
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
        "genomic_alteration_profile":    verdict,
        "driving_rule_id":               driving_rule,
        # SNV / indel axis
        "mutation_landscape_class":      _get("mutation-type-counts",
                                              "mutation_landscape_class"),
        "mutation_stratification_class": _get("mutation-stratified-dependency",
                                              "mutation_stratification_class"),
        "overall_mutation_frequency":    _get("mutation-hotspot-frequency",
                                              "overall_mutation_frequency"),
        # Copy-number axis
        "copy_number_class":             _get("copy-number-distribution",
                                              "copy_number_class"),
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
