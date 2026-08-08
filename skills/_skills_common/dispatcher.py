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
import time
from pathlib import Path
from typing import Callable, Optional

from . import (
    resolve_cards, fired_rules, modality_lens,
    make_decision_json, write_package,
)


# Types
VerdictFn = Callable[[list[dict]], tuple[str, Optional[str]]]
HeadlineFn = Callable[[list[dict], list[dict], Optional[tuple[str, Optional[str]]]], dict]
# A skill-specific two-slot synthesizer: (decision, model_id, subtype_query) -> llm_synthesis dict.
# Each single-lens skill declares its OWN narrator (presence / selectivity / genomic-alteration),
# each with its own tool schema + prompt. When --synthesize is passed but no synthesize_fn is
# provided, the dispatcher falls back to synthesize_presence (backward-compat for tumor-presence,
# which relied on the former hardcoded import).
SynthesizeFn = Callable[[dict, Optional[str], Optional[str]], dict]
# A skill-specific subtype-PANORAMA resolver: (target, indication, [stratum_ids]) -> dict with
#   {"cards": [<resolved subtype card outputs>], "scope_subtypes": [...], "<axis>": {<panorama>}}.
# ONLY invoked when the caller both (a) passes subtype_panorama_fn AND (b) the run receives
# --subtypes. The returned cards are APPENDED to the emitted package + the returned panorama block
# is merged into the headline, but they are NOT in `fired` — the panorama touches NO resolver rung,
# so the verdict spine is byte-identical whether or not --subtypes is passed. This is the shared-
# dispatcher equivalent of genomic-alteration-profile's hand-rolled --subtypes path.
SubtypePanoramaFn = Callable[[str, Optional[str], list], dict]


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
    synthesize_fn: Optional[SynthesizeFn] = None,
    subtype_panorama_fn: Optional["SubtypePanoramaFn"] = None,
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
        subtype_panorama_fn: optional (target, indication, [stratum_ids]) -> dict resolver for
            a DESCRIPTIVE per-subtype panorama (e.g. dependency by MSI status). Invoked ONLY when
            the run receives --subtypes AND this fn is supplied. Its cards are appended to the
            emitted package + its panorama block merged into the headline, but they never enter
            `fired` — the verdict spine is byte-identical with or without --subtypes. When None
            (every existing caller), --subtypes is inert: a complete no-op.
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
    ap.add_argument("--synthesize", action="store_true",
                    help="OPT-IN: attach an LLM narration of the deterministic verdict + "
                         "contextualized axes under decision['llm_synthesis']. NEVER alters the "
                         "verdict spine (the decision is byte-identical without this flag).")
    ap.add_argument("--synthesis-model", default=None,
                    help="Override the Bedrock synthesis model id (default: framework Opus).")
    ap.add_argument("--subtype", default=None,
                    help="OPTIONAL synthesis-grain selector: name a molecular subtype (e.g. MSI_H) to "
                         "have the narration FOREGROUND that stratum's position, in addition to the "
                         "across-subtype omnibus. Emphasis-only — no spine change; if the subtype is "
                         "not among the computed strata, synthesis says so honestly.")
    ap.add_argument("--subtypes", default=None,
                    help="OPTIONAL comma-separated molecular subtype/stratum ids (e.g. 'MSI_H,MSS'). "
                         "When set AND the skill supplies a subtype_panorama_fn, resolves a DESCRIPTIVE "
                         "per-stratum panorama across those strata (e.g. dependency by MSI status) and "
                         "appends it to the package + headline. Does NOT affect the verdict (byte-stable "
                         "regardless). Distinct from --subtype (singular), which only steers synthesis "
                         "emphasis over already-computed strata.")
    args = ap.parse_args(argv)

    # A target-intrinsic invocation (no --indication) passes a pan-cancer sentinel so the resolve_cards
    # signature is unchanged; tier:target readers ignore it (see the --indication help above).
    _indication = args.indication if args.indication is not None else "PANCANCER"

    # ── run-health instrumentation (per-subskill; every wired skill flows through here) ──
    # perf_counter is monotonic wall-clock; splits DATA-READ (resolve_cards → the S3/parquet
    # reads) from COMPUTE (rules + verdict + headline). Timings are OBSERVABILITY only — they
    # never touch the verdict spine, and they land in decision['run_health'] (a sibling key,
    # like llm_synthesis). Written per subskill, so the health probe can read real read/compute
    # latency + liveness for EACH subskill's own run — not just compose-dashboard's package.
    _t0 = time.perf_counter()

    # 1. Resolve cards via compose-dashboard live-readers
    card_outputs = resolve_cards(cards, args.target, _indication)
    _read_secs = time.perf_counter() - _t0
    _compute_start = time.perf_counter()

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

    # 4b. OPTIONAL subtype panorama (DESCRIPTIVE, --subtypes-gated). Resolved on a SEPARATE path
    # from the whole-cohort spine: its cards are NOT in `fired` and touch no resolver rung, so the
    # verdict is byte-identical whether or not --subtypes is passed. Only runs when the skill both
    # supplies subtype_panorama_fn AND the run receives --subtypes. A panorama-resolution failure
    # degrades to None (never breaks the deterministic run — same discipline as synthesis).
    subtype_result = None
    _subtypes = [s.strip() for s in (args.subtypes or "").split(",") if s.strip()]
    if subtype_panorama_fn is not None and _subtypes:
        try:
            subtype_result = subtype_panorama_fn(args.target, args.indication, _subtypes)
        except Exception as e:  # noqa: BLE001 — the panorama is a display facet; never load-bearing
            subtype_result = {"cards": [], "scope_subtypes": _subtypes,
                              "_subtype_panorama_error": f"{type(e).__name__}: {e}"}

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

    # Attach the subtype panorama to the headline (DESCRIPTIVE; verdict-inert). The skill's
    # panorama_fn returns a dict with a "scope_subtypes" list + one panorama block keyed by axis
    # name; surface both for the LLM/render. Never present unless --subtypes was passed.
    if subtype_result is not None:
        headline["subtype_scope"] = subtype_result.get("scope_subtypes")
        for k, v in subtype_result.items():
            if k not in ("cards", "scope_subtypes"):   # the panorama block(s) + any error note
                headline[k] = v

    # 7. Optional modality lens
    lenses = None
    invoked_lenses: dict = {}
    if args.modality:
        lenses = {args.modality: modality_lens(fired, args.modality)}
        invoked_lenses["modality"] = args.modality

    # The whole-cohort cards drive the verdict; the subtype panorama cards (if any) are appended for
    # the emitted package + LLM only — they are NOT in `fired`, so they touch no rung (spine stable).
    emitted_cards = card_outputs + (subtype_result.get("cards", []) if subtype_result else [])
    if subtype_result is not None:
        invoked_lenses["subtypes"] = subtype_result.get("scope_subtypes")

    # 8. Compose decision.json
    decision = make_decision_json(
        skill_name=skill_name,
        target=args.target, indication=_indication,
        question=question.format(target=args.target, indication=_indication),
        card_outputs=emitted_cards, fired=fired,
        headline=headline, modality_lenses=lenses,
    )

    # 8a. Per-subskill RUN-HEALTH record (observability; sibling key, never touches the spine).
    # status: ok = all consumed cards resolved; degraded = some card missing/skipped (arch A4)
    # but the run completed. (A hard failure raises before here, so a written decision.json is
    # never 'error' — the ABSENCE of a fresh run_health is itself the error signal downstream.)
    _cards_missing = [c["card_id"] for c in card_outputs if c.get("_missing")]
    _cards_fired_ids = sorted({f.get("card_id") for f in fired if f.get("card_id")})
    decision["run_health"] = {
        "skill_name": skill_name,
        "skill_version": skill_version,
        "status": "degraded" if (_cards_missing or skipped_card_ids) else "ok",
        "n_cards_consumed": len(cards),
        "n_cards_resolved": sum(1 for c in card_outputs if not c.get("_missing")),
        "n_cards_fired": len(_cards_fired_ids),
        "cards_fired": _cards_fired_ids,
        "cards_missing": sorted(_cards_missing),
        "cards_skipped_a4": sorted(skipped_card_ids),
        "read_secs": round(_read_secs, 4),
        "compute_secs": round(time.perf_counter() - _compute_start, 4),
        # total is stamped at the very end (below) so it includes synthesis + write.
    }

    # 8b. OPT-IN LLM synthesis (two-slot design). Attaches a provenance-tagged narration
    # as a SIBLING key decision['llm_synthesis'] AFTER the deterministic decision is composed,
    # so it is structurally impossible for the LLM to alter the verdict spine. Never runs
    # without --synthesize; a synthesis failure degrades to a note (the deterministic run must
    # never break because the narration layer is unavailable — Bedrock auth, network, etc.).
    if args.synthesize:
        # Each single-lens skill narrates through its OWN synthesizer (its tool schema + prompt
        # match its evidence). synthesize_fn is passed by the skill's run.py; when omitted, fall
        # back to synthesize_presence (backward-compat for tumor-presence). This is the fix for the
        # former hardcoded `from .synthesis import synthesize_presence` — a --synthesize selectivity
        # run used to be narrated by the PRESENCE narrator (wrong lens).
        _synth = synthesize_fn
        if _synth is None and verdict_fn is None:
            # DESCRIPTIVE skill (synthesis: none — e.g. target-intrinsic passes verdict_fn=None AND
            # no synthesize_fn): there is no verdict to narrate and no lens for this grain. The former
            # blanket fallback ran the PRESENCE narrator here, producing garbage on an indication-
            # independent dossier ("Complete absence of presence data — the lens cannot be evaluated";
            # 2026-08-08 synthesis review). Refuse honestly rather than mis-lens: emit a note, leave the
            # descriptive decision intact. (A skill that WANTS narration supplies synthesize_fn.)
            decision["llm_synthesis"] = {
                "_synthesis_skipped": "descriptive_skill_no_narrator",
                "_note": ("This skill is descriptive (no verdict spine) and declares no synthesis "
                          "narrator, so --synthesize is a no-op — there is no lens-appropriate "
                          "narration for this grain. The deterministic dossier above is complete."),
            }
        else:
            if _synth is None:
                # A VERDICT-bearing skill that didn't supply its own narrator → the presence narrator
                # is the backward-compat default (tumor-presence). A skill with a non-presence verdict
                # should pass its own synthesize_fn (tumor-selectivity/functional-requirement do).
                from .synthesis import synthesize_presence
                _synth = synthesize_presence
            try:
                decision["llm_synthesis"] = _synth(
                    decision, args.synthesis_model, args.subtype)
            except Exception as e:  # noqa: BLE001 — synthesis is optional; never break the spine
                decision["llm_synthesis"] = {
                    "_synthesis_error": f"{type(e).__name__}: {e}",
                    "_note": "LLM synthesis unavailable; the deterministic verdict above is unaffected.",
                }

    # Stamp total wall-clock (read + compute + optional synthesis) BEFORE write_package
    # serializes the decision — write time itself is not a data-access signal.
    decision["run_health"]["total_secs"] = round(time.perf_counter() - _t0, 4)

    # 9. Emit standard data-package tree (include the subtype panorama cards when present)
    written = write_package(
        out_dir=args.out,
        decision=decision,
        card_outputs=emitted_cards,
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
