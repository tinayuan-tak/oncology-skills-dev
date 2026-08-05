"""dispatcher — shared graduated-skill runner.

W4 fix rollup (2026-07-09): factors the canonical wired-skill flow
(resolve_cards → fired_rules → verdict → write_package) into a single
`run_wired_skill(...)` entry point. Replaces the ~130-line hand-written
main() body in each wired skill with a ~30-40-line configuration.

Purpose: enforce the compositional-architecture pillar (Layered
separation) at the code layer, not just at the SKILL.md metadata layer.
Every graduated skill's dispatcher is now a single shared code path;
the SKILL.md ↔ scripts drift class of bug (fix rollup findings #3, #4,
#5) becomes structurally impossible because there is only one
dispatcher implementation.

Also lands the arch A4 runtime consumer: when a card in `cards_used`
resolves to `missing=True`, the dispatcher applies the
`on_dependency_status[card_id]` behavior (skip_section /
emit_with_caveat / fail) declared in the SKILL.md front-matter.

Usage from a skill's run.py:

    from _skills_common.dispatcher import run_wired_skill

    def _verdict(fired):
        ...

    def _headline(cards, fired, verdict_pair):
        v, drv = verdict_pair or ("insufficient", None)
        return {"my_verdict": v, "driving_rule_id": drv, ...}

    if __name__ == "__main__":
        sys.exit(run_wired_skill(
            skill_name="my-skill",
            skill_version="1.0.0",
            cards=["my-card-1", "my-card-2"],
            axis="intracellular_intrinsic",
            question="Does {target} do X in {indication}?",
            verdict_fn=_verdict,
            headline_fn=_headline,
        ))
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, Optional

from . import (
    resolve_cards, fired_rules, modality_lens,
    make_decision_json, write_package,
)


# Types
VerdictFn = Callable[[list[dict]], tuple[str, Optional[str]]]
HeadlineFn = Callable[[list[dict], list[dict], Optional[tuple[str, Optional[str]]]], dict]


# ARCH A4 — behaviors when a `cards_used` dep is missing at runtime.
# Sourced from _skills_common.composition_schema.DEPENDENCY_STATUS_BEHAVIORS.
_A4_SKIP = "skip_section"
_A4_FAIL = "fail"
_A4_CAVEAT = "emit_with_caveat"


def _apply_on_dependency_status(
    cards: list[dict],
    on_dependency_status: dict[str, str],
) -> tuple[list[dict], list[str], list[str]]:
    """Apply arch-A4 behavior when a card comes back missing.

    Returns (surviving_cards, skipped_card_ids, caveat_messages).
    Raises RuntimeError on `fail` behavior.
    """
    if not on_dependency_status:
        return cards, [], []

    surviving: list[dict] = []
    skipped: list[str] = []
    caveats: list[str] = []

    for c in cards:
        cid = c.get("card_id")
        if not c.get("_missing"):
            surviving.append(c)
            continue

        behavior = on_dependency_status.get(cid)
        if behavior is None:
            # No behavior declared — keep the missing card (default);
            # the headline will surface `cards_missing` for the caller.
            surviving.append(c)
            continue

        if behavior == _A4_SKIP:
            skipped.append(cid)
            # Drop from the surviving-cards list; consumer sees only wired cards.
            continue
        if behavior == _A4_CAVEAT:
            caveats.append(
                f"Card '{cid}' is declared in cards_used but its data product "
                f"is unavailable at runtime. Per arch A4 on_dependency_status: "
                f"emit_with_caveat — the card is retained in the output but "
                f"downstream consumers should treat its summary_fields as "
                f"data_unavailable."
            )
            surviving.append(c)
            continue
        if behavior == _A4_FAIL:
            raise RuntimeError(
                f"Card '{cid}' is unavailable at runtime and its "
                f"on_dependency_status behavior is 'fail'. Skill run aborts "
                f"per the composition contract."
            )
        # Unknown behavior — treat as no-op (defensive)
        surviving.append(c)

    return surviving, skipped, caveats


def run_wired_skill(
    *,
    skill_name: str,
    skill_version: str,
    cards: list[str],
    axis: str,
    question: str,
    verdict_fn: Optional[VerdictFn] = None,
    headline_fn: Optional[HeadlineFn] = None,
    on_dependency_status: Optional[dict[str, str]] = None,
    partial_status_note: Optional[str] = None,
    isoform_check_target: bool = False,
    argv: Optional[list[str]] = None,
) -> int:
    """Run a wired compositional skill end-to-end.

    Parameters:
        skill_name: canonical HGNC-kebab skill identifier (e.g. "tumor-presence").
        skill_version: SemVer of THIS run.py (bumps when verdict/headline logic
            changes).
        cards: list of card_ids the skill consumes. Must match SKILL.md's
            composition.cards_used exactly (regression test enforces).
        axis: rules-axis to load (e.g. "intracellular_intrinsic",
            "surface_intrinsic").
        question: template string with {target} + {indication} placeholders.
        verdict_fn: optional callback (fired) → (verdict_str, driving_rule_id).
            Skills without a verdict function (e.g. tumor-selectivity, which
            uses selectivity_class directly) can omit this.
        headline_fn: optional callback (cards, fired, verdict_pair) → dict.
            When omitted, a minimal default headline is emitted.
        on_dependency_status: arch A4 behavior map card_id → behavior. Passed
            through from SKILL.md composition.on_dependency_status. When
            None or empty, missing cards are retained + surfaced in headline.
        partial_status_note: optional string surfaced in headline when the
            skill has status: partial (e.g. "gnomad wired; HPA IHC pending").
        isoform_check_target: when True, the dispatcher calls
            isoform_selective_targets.check_target(args.target) and injects
            two fields (isoform_selective_warning + isoform_selective_
            dominant_isoform) into the headline. Enables arch A3 discipline
            for skills that emit modality-relevant fields.
        argv: optional argv override (for tests / programmatic invocation).

    Returns:
        exit code (0 on success). Raises RuntimeError under arch A4 fail.
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, help="HGNC gene symbol")
    # --indication is OPTIONAL (2026-08-05): TARGET-INTRINSIC skills (e.g. target-intrinsic) fan out
    # over tier:target cards that take no indication, so they invoke with --target alone. When omitted,
    # a pan-cancer sentinel is passed to resolve_cards — target-grain card readers ignore it, and an
    # indication-scoped reader invoked without a real indication degrades to data_unavailable (its
    # honest gap posture). BACKWARD-COMPATIBLE: every existing focused skill still passes --indication,
    # so their behavior is unchanged.
    ap.add_argument("--indication", required=False, default=None, help="OncoTree code (optional for target-intrinsic skills)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--modality", default=None,
                    help="OPTIONAL post-hoc modality lens.")
    args = ap.parse_args(argv)

    # A target-intrinsic invocation (no --indication) passes a pan-cancer sentinel so the resolve_cards
    # signature is unchanged; tier:target readers ignore it (see the --indication help above).
    _indication = args.indication if args.indication is not None else "PANCANCER"

    # 1. Resolve cards via compose-dashboard live-readers
    card_outputs = resolve_cards(cards, args.target, _indication)

    # 2. Apply arch A4 on_dependency_status behavior
    card_outputs, skipped_card_ids, a4_caveats = _apply_on_dependency_status(
        card_outputs, on_dependency_status or {}
    )

    # 3. Fire rules against surviving cards only
    surviving_card_ids = [c["card_id"] for c in card_outputs]
    fired = fired_rules(card_outputs, axis=axis,
                        card_id_filter=surviving_card_ids)

    # 4. Verdict (optional callback)
    verdict_pair = verdict_fn(fired) if verdict_fn else None

    # 5. Isoform-selective A3 check (optional)
    isoform_warning = None
    if isoform_check_target:
        from .isoform_selective_targets import check_target
        isoform_warning = check_target(args.target)

    # 6. Headline (optional callback; default is a minimal skeleton)
    if headline_fn:
        headline = headline_fn(card_outputs, fired, verdict_pair)
    else:
        headline = {
            "verdict": verdict_pair[0] if verdict_pair else "insufficient",
            "driving_rule_id": verdict_pair[1] if verdict_pair else None,
        }

    # Attach arch A4 provenance + isoform-selective flags uniformly
    headline["cards_available"] = sum(1 for c in card_outputs
                                       if not c.get("_missing"))
    headline["cards_missing"] = [c["card_id"] for c in card_outputs
                                  if c.get("_missing")]
    if skipped_card_ids:
        headline["_a4_skipped_sections"] = skipped_card_ids
    if a4_caveats:
        headline["_a4_caveats"] = a4_caveats
    if partial_status_note:
        headline["_partial_status_note"] = partial_status_note
    if isoform_check_target:
        headline["isoform_selective_warning"] = isoform_warning is not None
        headline["isoform_selective_dominant_isoform"] = (
            isoform_warning.dominant_isoform if isoform_warning else None
        )

    # 7. Optional modality lens
    lenses = None
    invoked_lenses: dict = {}
    if args.modality:
        lenses = {args.modality: modality_lens(fired, args.modality)}
        invoked_lenses["modality"] = args.modality

    # 8. Compose decision.json
    decision = make_decision_json(
        skill_name=skill_name,
        target=args.target, indication=_indication,
        question=question.format(target=args.target, indication=_indication),
        card_outputs=card_outputs, fired=fired,
        headline=headline, modality_lenses=lenses,
    )

    # 9. Emit standard data-package tree
    written = write_package(
        out_dir=args.out,
        decision=decision,
        card_outputs=card_outputs,
        target=args.target,
        indication=_indication,
        skill_name=skill_name,
        skill_version=skill_version,
        invoked_lenses=invoked_lenses,
    )
    print(f"wrote data-package to {args.out}")
    print(f"  tables: {len(written['tables'])}  figures: {len(written['figures'])}")
    if skipped_card_ids:
        print(f"  arch A4 skipped: {skipped_card_ids}")
    print()
    print(json.dumps(headline, indent=2, default=str))
    return 0
