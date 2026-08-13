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


# ── D1b: opt-in evidence-package envelope emission for a focused subskill ──────────────
# governance.data_mode is a CLOSED enum (latest_approved | pinned | exploratory). A subskill
# envelope is exploratory-grade by construction (no concurrence, no manifest pinning yet), so a
# free-form --data-mode value (default "live") is mapped to a schema-valid governance value;
# recognized enum values pass through unchanged.
_GOVERNANCE_DATA_MODE = {
    "latest_approved": "latest_approved",
    "pinned": "pinned",
    "exploratory": "exploratory",
}


def _availability_state_for(card: dict) -> "tuple[str, str]":
    """Map a resolve_cards `_missing` card to a schema-valid (availability_state, reason).

    Mirrors the card_unavailable enum: an honest data_unavailable answer is `insufficient`
    (looked, genuinely absent); dispatcher-None is `not_wired`; a live_read_error is
    `read_error`; anything else is a `data_blocked` coverage gap.
    """
    reason = str(card.get("_missing_reason", "unavailable"))
    if card.get("_data_unavailable"):
        return "insufficient", reason
    if reason == "dispatcher_returned_none":
        return "not_wired", reason
    if reason.startswith("live_read_error"):
        return "read_error", reason
    return "data_blocked", reason


def _envelope_card_present(card: dict) -> dict:
    """Normalize a subskill resolve_cards output into an evidence_package `card_present` entry.

    resolve_cards emits a lean shape (card_id / summary / interpretation_call); the envelope
    schema's card_present requires validation_state + provenance and forbids extra keys
    (unevaluatedProperties: false), so we build a fresh, schema-shaped dict.
    """
    return {
        "card_id": card["card_id"],
        "card_version": card.get("card_version", "1.0.0"),
        "validation_state": "pass",
        "summary": card.get("summary", {}) or {},
        "interpretation_call": card.get("interpretation_call") or "uninterpreted",
        "caveats": card.get("caveats", []),
        "provenance": card.get("provenance", {"method_calls": [], "input_manifest_ids": []}),
    }


def _emit_subskill_envelope(*, args, skill_name: str, skill_version: str,
                            emitted_cards: list[dict], headline: dict,
                            verdict_pair: "Optional[tuple[str, Optional[str]]]",
                            fired: list[dict]) -> Path:
    """Assemble + write evidence_package.json around a subskill's resolver verdict (D1b, opt-in).

    PURELY ADDITIVE: consumes the already-computed decision outputs (emitted_cards, headline,
    verdict_pair, fired) and writes a sibling evidence_package.json in args.out. Never touches
    decision.json — the verdict spine is byte-identical whether or not --emit-envelope is set.
    """
    from .envelope import assemble_evidence_package
    from .gitmeta import skills_repo_sha

    _indication = args.indication if args.indication is not None else "PANCANCER"

    # Verdict + driving rule: prefer the resolver-derived verdict_pair (verdict_fn output);
    # otherwise read the decision headline dict (skills that carry the verdict there).
    if verdict_pair:
        verdict, driving_rule_id = verdict_pair
    else:
        verdict = headline.get("verdict", "insufficient")
        driving_rule_id = headline.get("driving_rule_id")
    verdict = verdict or "insufficient"
    fired_rule_ids = sorted({f.get("rule_id") for f in fired if f.get("rule_id")})

    # synthesis slot — verdict-shaped. Schema-minimal (required `headline` str 5-2000; extra keys
    # allowed), so the resolver verdict rides in the headline plus structured sibling keys.
    synthesis_block = {
        "headline": f"{skill_name}: {verdict}" + (f" ({driving_rule_id})" if driving_rule_id else ""),
        "caveats_summary": (
            f"Exploratory subskill envelope emitted by {skill_name}@{skill_version} around its own "
            f"deterministic resolver verdict; not a composed target-profile and not "
            f"concurrence-reviewed. cards_missing={headline.get('cards_missing', [])}."
        ),
        "gate": skill_name,
        "verdict": verdict,
        "driving_rule_id": driving_rule_id,
        "fired_rule_ids": fired_rule_ids,
    }

    # Split emitted cards into present (normalized) + reasoned absences (card_unavailable).
    env_present: list[dict] = []
    env_unavailable: list[dict] = []
    for c in emitted_cards:
        if c.get("_missing"):
            state, reason = _availability_state_for(c)
            env_unavailable.append({
                "card_id": c["card_id"],
                "card_version": c.get("card_version", "n/a"),
                "availability_state": state,
                "availability_reason": reason,
            })
        else:
            env_present.append(_envelope_card_present(c))

    # Resolve the foundational target-identity-summary card so context.target carries a real
    # hgnc_id (schema requires >= 1). This is a SEPARATE read for the envelope's context block
    # only — it is NOT added to decision.json. Best-effort: on failure the writer emits the
    # hgnc_id=-1 sentinel (honest "identity not resolved") and the run still completes.
    try:
        for c in resolve_cards(["target-identity-summary"], args.target, _indication):
            if not c.get("_missing"):
                env_present.append(_envelope_card_present(c))
    except Exception as e:  # noqa: BLE001 — identity read is best-effort; never break emit
        print(f"[dispatcher] --emit-envelope: target-identity read failed ({type(e).__name__}); "
              f"context.target.hgnc_id will be the unresolved sentinel.", file=sys.stderr)

    input_context = {
        "target_symbol": args.target,
        "indication": _indication,
        "subgroup_spec": None,
        "data_mode": _GOVERNANCE_DATA_MODE.get(args.data_mode, "exploratory"),
        "release_pin": args.release_pin,
    }
    validation_summary = {
        "n_cards_attempted": len(emitted_cards),
        "n_cards_passed": len(env_present),
        "n_cards_passed_with_warnings": 0,
        "n_cards_failed": len(env_unavailable),
        "n_cards_excluded_by_applies_when": 0,
    }
    try:
        # COMPOSE_SCRIPTS was added to sys.path by resolve_cards()'s dispatcher import above.
        from compose_phase1 import FRAMEWORK_VERSION as _fv
    except Exception:  # noqa: BLE001 — fall back to the iter-1 framework version
        _fv = "2.0.0"

    ep = assemble_evidence_package(
        input_context=input_context,
        dashboard_spec_ref=f"skill:{skill_name}",
        card_outputs=env_present,
        unavailable_cards=env_unavailable,
        validation_summary=validation_summary,
        synthesis_block=synthesis_block,
        deterministic_timestamps=False,
        framework_version=_fv,
        generated_by=f"skills/{skill_name}@{skills_repo_sha()}",
    )
    out_path = Path(args.out) / "evidence_package.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(ep, indent=2, default=str))
    return out_path


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
    extra_axes: Optional[list[str]] = None,
    verdict_cards: Optional[list[str]] = None,
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
        verdict_cards: OPTIONAL subset of `cards` that can MOVE the verdict — the resolver's
            referenced cards, from reachability.verdict_relevant_cards(gate). When --verdict-only is
            passed AND this is a non-empty SUBSET of `cards`, ONLY these cards are read: the verdict
            is byte-identical (resolve_verdict_for_gate ignores fired rules no rung references) while
            the verdict-inert enrichment reads are skipped. Default None ⇒ --verdict-only reads ALL
            cards (a complete no-op). A guard test enforces verdict_cards ⊆ cards.
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
    ap.add_argument("--verdict-only", action="store_true",
                    help="FAST/lean mode: read ONLY the verdict-relevant cards (the resolver's "
                         "referenced cards, passed by the skill as verdict_cards) and skip the "
                         "verdict-inert enrichment reads + any --synthesize narration. The verdict "
                         "spine (verdict + driving_rule_id) is byte-identical to a full run. No-op "
                         "for a skill that declares no verdict_cards subset (reads all cards).")
    ap.add_argument("--emit-envelope", action="store_true",
                    help="OPT-IN (default OFF ⇒ complete no-op): ALSO write a governance-grade "
                         "evidence_package.json envelope (beside decision.json) around THIS "
                         "subskill's resolver verdict, via the shared _skills_common.envelope "
                         "writer. PURELY ADDITIVE — decision.json is byte-identical whether or not "
                         "this flag is set. The synthesis slot carries the verdict as its headline.")
    ap.add_argument("--data-mode", default="live",
                    help="Data-provenance posture, carried into the emitted envelope's "
                         "input_context/governance ONLY (mapped to the governance data_mode enum; "
                         "a subskill envelope is exploratory-grade). D1b does NOT implement manifest "
                         "pinning / resolve_release — that is a data-catalog follow-on. Inert unless "
                         "--emit-envelope is set.")
    ap.add_argument("--release-pin", default=None,
                    help="Optional catalog release pin, carried into the envelope governance block "
                         "ONLY (no manifest resolution yet — follow-on). Inert unless --emit-envelope.")
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

    # 1. Resolve cards via compose-dashboard live-readers. --verdict-only reads ONLY the
    # verdict-relevant subset (verdict_cards) so enrichment reads are skipped; the verdict is
    # byte-identical because resolve_verdict_for_gate ignores fired rules no resolver rung references.
    # SAFETY: lean ONLY when verdict_cards is a non-empty SUBSET of cards; else read ALL (an
    # absent-resolver / incomplete derivation returns empty and must never silently read nothing).
    _lean = bool(args.verdict_only and verdict_cards and set(verdict_cards) <= set(cards))
    if args.verdict_only and not _lean:
        print("[dispatcher] --verdict-only: no proven verdict-card subset for this skill "
              "(verdict_cards empty or not a subset of cards) — reading ALL cards (no-op).",
              file=sys.stderr)
    _cards_to_read = list(verdict_cards) if _lean else cards
    if _lean:
        args.synthesize = False   # verdict-only skips narration too
        print(f"[dispatcher] --verdict-only: reading {len(_cards_to_read)}/{len(cards)} "
              f"verdict-relevant cards (enrichment reads skipped; verdict byte-identical)",
              file=sys.stderr)
    card_outputs = resolve_cards(_cards_to_read, args.target, _indication)
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

    # 4. Verdict (optional callback) — the PRIMARY `axis` alone drives the verdict.
    verdict_pair = verdict_fn(fired) if verdict_fn else None

    # 4a. Extra AUDIT axes (optional). A skill may fire a SECOND, self-contained axis (e.g.
    # combo-and-resistance's resistance_emergence) whose rules belong in the emitted audit spine
    # (decision['fired_rules']) + run_health.cards_fired, but must NOT touch the primary verdict.
    # Fired AFTER verdict_fn and merged into `fired`, so the resistance verdict a skill computes in
    # its headline_fn is traceable to a fired rule. Default (no extra_axes) is byte-identical.
    for _extra_axis in (extra_axes or []):
        fired = fired + fired_rules(card_outputs, axis=_extra_axis,
                                    card_id_filter=surviving_card_ids)

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

    # 8. Compose decision.json — with the run-level PROVENANCE block (2026-08-13). resolve_cards now
    # stamps each card with its declared input_manifest_ids, so the subskill default output records
    # WHICH CODE + POSTURE + DATA produced it (skills sha, data_mode/release_pin, resolved_release +
    # content digests, per-family drift) — reproducible/auditable without the opt-in envelope. Single-
    # sourced via build_subskill_provenance (same digest the envelope uses). Best-effort; never raises.
    from .envelope import build_subskill_provenance
    from .gitmeta import skills_repo_sha
    _identity = next((c for c in emitted_cards if c.get("card_id") == "target-identity-summary"), None)
    _resolver_pin = (_identity.get("summary") or {}).get("resolver_release_pin") if _identity else None
    provenance = build_subskill_provenance(
        emitted_cards, args.data_mode, args.release_pin, skills_repo_sha(),
        resolver_release_pin=_resolver_pin,
    )
    decision = make_decision_json(
        skill_name=skill_name,
        target=args.target, indication=_indication,
        question=question.format(target=args.target, indication=_indication),
        card_outputs=emitted_cards, fired=fired,
        headline=headline, modality_lenses=lenses, provenance=provenance,
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

    # 10. OPT-IN evidence-package envelope (D1b). Default OFF ⇒ this whole block is skipped ⇒
    # zero behavior change for every existing invocation. When set, assemble + write a sibling
    # evidence_package.json around the verdict already computed above (decision.json untouched —
    # byte-identical). A failure here degrades to a note; it must never break the deterministic run.
    if args.emit_envelope:
        try:
            _ep_path = _emit_subskill_envelope(
                args=args, skill_name=skill_name, skill_version=skill_version,
                emitted_cards=emitted_cards, headline=headline,
                verdict_pair=verdict_pair, fired=fired,
            )
            print(f"  emitted evidence_package.json → {_ep_path}")
        except Exception as e:  # noqa: BLE001 — envelope is additive; never break the spine
            print(f"[dispatcher] --emit-envelope: envelope emission failed "
                  f"({type(e).__name__}: {e}); decision.json is unaffected.", file=sys.stderr)

    print()
    print(json.dumps(headline, indent=2, default=str))
    return 0
