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
from _skills_common.resolver import resolve_verdict_for_gate

SKILL_NAME = "genomic-alteration-profile"
SKILL_VERSION = "2.0.0"      # major bump: reframed from mutation-profile 1.0.0

CARDS = [
    # SNV / indel (mutation)
    "mutation-type-counts",
    "mutation-stratified-dependency",
    "mutation-hotspot-frequency",
    # Copy number (amplification / deletion) — card + rules already existed
    "copy-number-distribution",
    # Fusion / rearrangement — LIVE 2026-07-23 (tcga-fusion-consensus-v1, pan-TCGA 3-caller
    # consensus). fusion_class {recurrent_fusion_driver|sporadic_fusion|no_recurrent_fusion|
    # data_unavailable}. ADDITIVE signal-only: reaches the LLM/matrix + headline, touches NO
    # resolver rung (the genomic verdict spine stays byte-stable). Recurrent-fusion driver
    # corroborates the genomic alteration call; graceful data_unavailable for TCGA-absent targets.
    "fusion-rearrangement-landscape",
    # Typed driver-ROLE call (OncoKB × IntOGen) — the functional-role layer on the descriptive
    # cards above (frequency ≠ function). Its alteration_role signals feed genomic interpretation;
    # ADDITIVE (rules touch no resolver rung — the skill's inline verdict stays byte-stable). Also
    # in target-profile SUB_SKILL_CARDS[genomic-alteration-profile] (composer-consistency).
    "alteration-role",
    # Harmonized two-hit / biallelic-inactivation state (M6, functional_gene_state). The ALLELE-COUNT
    # layer: is the gene biallelically inactivated (completed two-hit → LoF) or only monoallelically
    # hit — mutation + allele-specific CN, patient (TCGA) + model (DepMap) arms. ADDITIVE signal-only:
    # its state signals + headline reach the LLM/matrix but touch NO resolver rung (the genomic
    # verdict spine stays byte-stable — wiring INTO the verdict is a later, riskier step). Phase-1
    # genetic-only vocab {wt, monoallelic, biallelic-genetic, uncertain}.
    "functional-gene-state",
    # Patient↔model genomic-event correspondence (M11, genomic_event_model_match — the canonical P3
    # join). Which DepMap models carry the SAME functional event as the tumors, and which are
    # dependent? The genomic sibling of recommended-models (expression-Q4). ADDITIVE signal-only:
    # feeds LLM/matrix + headline, touches NO resolver rung (verdict spine byte-stable). Corroborates
    # Required (C) — genotype-matched + dependent in-lineage models = a genotype-backed dependency basis.
    "genomic-event-model-match",
]

QUESTION = ("How is {target} genomically altered in {indication} — by SNV/indel "
            "(driver, biomarker-stratified dependency, or passenger), by copy-"
            "number (amplification/deletion), or a mix — and which class drives?")


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Multi-class genomic-alteration verdict — DELEGATES to the shared declarative resolver
    (gap #5 conversion, 2026-07-22). The former inline multi-axis if-chain (SNV/indel priority ×
    copy-number, combined into multi_class_driver) now lives in
    resolvers/genomic_alteration.resolver.yaml (target-contracts), evaluated by the ONE interpreter
    both engines call. Proven byte-for-byte equivalent to the former if-chain across all 256 (2^8)
    fired-set combinations by the pre-swap oracle + frozen in the golden snapshot. A missing spec
    raises (the resolver is the source of truth — NO silent fallback to a stale copy, which would
    reintroduce the drift this refactor eliminates)."""
    result = resolve_verdict_for_gate(fired, "genomic_alteration")
    if result is None:
        raise RuntimeError(
            "genomic_alteration resolver spec missing (target-contracts/resolvers/"
            "genomic_alteration.resolver.yaml) — the verdict source of truth is absent.")
    return result


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

    headline = {
        "genomic_alteration_profile":    verdict,
        "driving_rule_id":               driving_rule,
        # SNV / indel axis
        "mutation_landscape_class":      get_card_field(cards, "mutation-type-counts",
                                              "mutation_landscape_class"),
        "mutation_stratification_class": get_card_field(cards, "mutation-stratified-dependency",
                                              "mutation_stratification_class"),
        "overall_mutation_frequency":    get_card_field(cards, "mutation-hotspot-frequency",
                                              "overall_mutation_frequency"),
        # Copy-number axis
        "copy_number_class":             get_card_field(cards, "copy-number-distribution",
                                              "copy_number_class"),
        # Typed driver-role axis (OncoKB × IntOGen)
        "alteration_role":               get_card_field(cards, "alteration-role", "alteration_role"),
        "functional_direction":          get_card_field(cards, "alteration-role", "functional_direction"),
        # Allele-count / biallelic-inactivation axis (M6, functional_gene_state) — signal-only,
        # does NOT feed the verdict (additive; the resolver spine is byte-stable).
        "functional_state_class":        get_card_field(cards, "functional-gene-state", "functional_state_class"),
        # Patient↔model genomic-event correspondence (M11) — signal-only, does NOT feed the verdict.
        "event_correspondence_class":    get_card_field(cards, "genomic-event-model-match", "event_correspondence_class"),
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
