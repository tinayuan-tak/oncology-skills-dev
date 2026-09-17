"""dispatcher — shared graduated-skill runner.

Fix rollup (2026-07-09): factors the canonical wired-skill flow
(resolve_cards → fired_rules → verdict → write_package) into a single
`run_wired_skill(...)` entry point. Replaces the ~130-line hand-written
main() body in each wired skill with a ~30-40-line configuration.

Purpose: enforce the compositional-architecture pillar (Layered
separation) at the code layer, not just at the SKILL.md metadata layer.
Every graduated skill's dispatcher is now a single shared code path;
the SKILL.md ↔ scripts drift class of bug becomes structurally
impossible because there is only one dispatcher implementation.

Also lands the runtime consumer: when a card in `cards_used`
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
import inspect
import json
import os
import sys
import time
from pathlib import Path
from typing import Callable, Optional

from . import (
    card_warnings,
    fired_rules,
    make_decision_json,
    modality_lens,
    resolve_cards,
    write_package,
)
from .run_log import install_run_log, restore_run_log

# Types
VerdictFn = Callable[[list[dict]], tuple[str, Optional[str]]]
HeadlineFn = Callable[[list[dict], list[dict], Optional[tuple[str, Optional[str]]]], dict]
# A skill-specific two-slot synthesizer: (decision, model_id, subtype_query) -> llm_synthesis dict.
# Every skill now narrates through the ONE generic capsule-driven engine (narrator_engine.narrate +
# a per-lens LensConfig), passed as synthesize_fn via narrator_engine.make_synthesize_fn(<LENS>). When
# --synthesize is passed but NO synthesize_fn is provided, the dispatcher honest-skips (no narration) —
# it NEVER falls back to another lens's narrator (the former presence fallback was removed as mis-lensing).
SynthesizeFn = Callable[[dict, Optional[str], Optional[str]], dict]
# A skill-specific subtype-PANORAMA resolver: (target, indication, [stratum_ids]) -> dict with
#   {"cards": [<resolved subtype card outputs>], "scope_subtypes": [...], "<axis>": {<panorama>}}.
# ONLY invoked when the caller both (a) passes subtype_panorama_fn AND (b) the run receives
# --subtypes. The returned cards are APPENDED to the emitted package + the returned panorama block
# is merged into the headline, but they are NOT in `fired` — the panorama touches NO resolver rung,
# so the verdict spine is byte-identical whether or not --subtypes is passed. This is the shared-
# dispatcher equivalent of genomic-alteration-profile's hand-rolled --subtypes path.
SubtypePanoramaFn = Callable[[str, Optional[str], list], dict]


# Behaviors when a `cards_used` dep is missing at runtime.
# Sourced from _skills_common.composition_schema.DEPENDENCY_STATUS_BEHAVIORS.
_A4_SKIP = "skip_section"
_A4_FAIL = "fail"
_A4_CAVEAT = "emit_with_caveat"


def _apply_on_dependency_status(
    cards: list[dict],
    on_dependency_status: dict[str, str],
) -> tuple[list[dict], list[str], list[str]]:
    """Apply the dependency-status behavior when a card comes back missing.

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


# ── opt-in evidence-package envelope emission for a focused subskill ──────────────
# governance.data_mode is a CLOSED enum (latest_approved | pinned | exploratory). A subskill
# envelope is exploratory-grade by construction (no concurrence, no manifest pinning yet), so a
# free-form --data-mode value (default "live") is mapped to a schema-valid governance value;
# recognized enum values pass through unchanged.
_GOVERNANCE_DATA_MODE = {
    "latest_approved": "latest_approved",
    "pinned": "pinned",
    "exploratory": "exploratory",
}


def _provenance_warnings(provenance: dict) -> list:
    """run_health observability (2026-08-13 multi-pair review): surface any per-family
    catalog-head resolution failure that resolved_release_governance recorded fail-open in
    provenance.resolved_releases[<fam>].resolution_error. Previously that error lived ONLY in the
    provenance block, so run_health reported status='ok' for a run whose DGE family failed to resolve
    (seen live on MET-LUAD, CEACAM5-LUAD). Returns a sorted-by-family list of {family, error}; empty
    when clean. Does NOT flip run_health.status — a head-resolution failure is a GOVERNANCE gap, not a
    missing verdict card, so it is reported as a distinct signal."""
    return [
        {"family": fam, "error": entry["resolution_error"]}
        for fam, entry in sorted(((provenance or {}).get("resolved_releases") or {}).items())
        if isinstance(entry, dict) and entry.get("resolution_error")
    ]


def _rule_polarity(rule_id: "Optional[str]") -> str:
    """Coarse role/polarity of a fired rule from its rule_id suffix vocabulary.
    positive = -supportive; negative = -killer / -veto / -opposing; else neutral
    (-neutral / -insufficient / -warning / -flagged / -conditional / -context / -unavailable)."""
    r = (rule_id or "").lower()
    if "supportive" in r:
        return "positive"
    if "killer" in r or "veto" in r or "opposing" in r:
        return "negative"
    return "neutral"


def _consolidation_fidelity(fired: list, driving_rule_id: "Optional[str]") -> dict:
    """Verdict-inert observability (2026-08-14 consolidation-fidelity diagnostic): does the SINGLE
    collapsed verdict MASK a polarity conflict among the fired rules?

    A skill collapses N cards → one verdict + one driving_rule_id. That is correct when the verdict is
    a faithful summary, but lossy when the collapse buries genuinely conflicting evidence (the
    tumor-presence cell-line-vs-tumor anchor, the isoform-suppression veto, the genomic multi-class
    collapse were all this). This block makes the collapse's fidelity legible WITHOUT changing the
    verdict:
      discordant           — the fired rules span BOTH a positive and a negative role
      masked_conflict      — the DRIVING rule's polarity is opposite to >=1 OTHER fired rule that was
                             overruled (the headline says + while a - fired, or vice versa)
      overruled_opposing_rules — those dropped opposite-polarity rule_ids (what a reader would miss)
      single_card_passthrough  — the verdict rests on a single contributing card (no integration)
    A consumer seeing masked_conflict=true should read the per-card / per-modality decomposition, not
    just the one-word verdict. Never feeds a rule; the verdict spine is untouched."""
    ids = [f.get("rule_id") for f in fired if isinstance(f, dict) and f.get("rule_id")]
    cards = sorted({f.get("card_id") for f in fired if isinstance(f, dict) and f.get("card_id")})
    pol = {rid: _rule_polarity(rid) for rid in ids}
    roles = set(pol.values())
    drv_pol = _rule_polarity(driving_rule_id)
    overruled_opp = sorted(
        rid
        for rid in ids
        if rid != driving_rule_id
        and ((drv_pol == "positive" and pol[rid] == "negative") or (drv_pol == "negative" and pol[rid] == "positive"))
    )
    return {
        "discordant": ("positive" in roles) and ("negative" in roles),
        "masked_conflict": bool(overruled_opp),
        "driving_role": drv_pol,
        "overruled_opposing_rules": overruled_opp,
        "roles_present": sorted(roles),
        "n_rules_fired": len(ids),
        "n_cards_contributing": len(cards),
        "single_card_passthrough": len(cards) <= 1,
    }


# A live_read_error reason that names a DATA-ABSENCE — the reader LOOKED and the target/gene is genuinely
# not in this dataset (`target_not_in_derived_product`, `gene_not_in_ccle_rrbs`, `target_absent_from_gygi_ms`).
# Per availability_state.enum this is `insufficient` (a MEASURED gap: looked, genuinely absent), NOT
# `read_error` (a framework-coverage gap: could not look). Both count against coverage, so this is
# label-only/verdict-inert — but it stops a plain data-absence reading as an infra BUG. Markers are
# deliberately specific ("not_in"/"absent_from") so they never match resolver_not_found or a genuine
# failure string (S3 timeout, deadlock, exception); an unrecognized live_read_error stays read_error (the
# safe, visible default). The clean-clean fix is method-side (emit an honest data_unavailable summary
# rather than the error sentinel), which routes through the `_data_unavailable` branch above; until then
# this classifies at the one canonical reason→state mapper.
_DATA_ABSENCE_MARKERS = ("not_in", "absent_from")


def _availability_state_for(card: dict) -> "tuple[str, str]":
    """Map a resolve_cards `_missing` card to a schema-valid (availability_state, reason).

    Mirrors the card_unavailable enum: an honest data_unavailable answer is `insufficient`
    (looked, genuinely absent); dispatcher-None is `not_wired`; a live_read_error is `read_error`
    UNLESS its reason names a data-absence (also `insufficient`); anything else is `data_blocked`.
    """
    reason = str(card.get("_missing_reason", "unavailable"))
    if card.get("_data_unavailable"):
        return "insufficient", reason
    if reason == "dispatcher_returned_none":
        return "not_wired", reason
    if reason.startswith("live_read_error"):
        if any(m in reason for m in _DATA_ABSENCE_MARKERS):
            return (
                "insufficient",
                reason,
            )  # looked, target genuinely absent from the dataset — a coverage gap, not a bug
        return "read_error", reason  # genuine read failure (timeout / deadlock / exception) — could not look
    return "data_blocked", reason


def _envelope_card_present(card: dict) -> dict:
    """Normalize a subskill resolve_cards output into an evidence_package `card_present` entry.

    resolve_cards emits a lean shape (card_id / summary / interpretation_call); the envelope
    schema's card_present requires validation_state + provenance and forbids extra keys
    (unevaluatedProperties: false), so we build a fresh, schema-shaped dict.
    """
    summary = card.get("summary", {}) or {}
    # Stage-4 warnings: evaluate the card's authored warning_predicates against this summary. A fired,
    # discriminating (non-E2-suppressed) predicate flips validation_state to passed_with_warnings and lists
    # its warning_id. Best-effort + verdict-inert: it annotates run_health, never a verdict; the schema's
    # card_present already permits both (validation_state enum + warning_ids). A predicate that cannot be
    # decided (unknown field) never fires.
    warning_ids = card_warnings.fired_warnings(card["card_id"], summary)
    entry = {
        "card_id": card["card_id"],
        "card_version": card.get("card_version", "1.0.0"),
        "validation_state": "passed_with_warnings" if warning_ids else "pass",
        "summary": summary,
        "interpretation_call": card.get("interpretation_call") or "uninterpreted",
        "caveats": card.get("caveats", []),
        # Merge the schema-required keys into whatever provenance the card carries — a subskill
        # card that emits a provenance dict WITHOUT method_calls was passing through incomplete
        # and failing evidence_package.schema card_present validation for EVERY card (target-profile
        # --emit evidence-package). Defaults first, card values override.
        "provenance": {**{"method_calls": [], "input_manifest_ids": []}, **(card.get("provenance") or {})},
    }
    if warning_ids:
        entry["warning_ids"] = warning_ids
    return entry


def _emit_subskill_envelope(
    *,
    args,
    skill_name: str,
    skill_version: str,
    emitted_cards: list[dict],
    headline: dict,
    verdict_pair: "Optional[tuple[str, Optional[str]]]",
    fired: list[dict],
) -> Path:
    """Assemble + write evidence_package.json around a subskill's resolver verdict (opt-in).

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
            env_unavailable.append(
                {
                    "card_id": c["card_id"],
                    "card_version": c.get("card_version", "n/a"),
                    "availability_state": state,
                    "availability_reason": reason,
                }
            )
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
        print(
            f"[dispatcher] --emit-envelope: target-identity read failed ({type(e).__name__}); "
            f"context.target.hgnc_id will be the unresolved sentinel.",
            file=sys.stderr,
        )

    input_context = {
        "target_symbol": args.target,
        "indication": _indication,
        "subgroup_spec": None,
        "data_mode": _GOVERNANCE_DATA_MODE.get(args.data_mode, "exploratory"),
        "release_pin": args.release_pin,
    }
    _n_with_warnings = sum(1 for c in env_present if c.get("validation_state") == "passed_with_warnings")
    validation_summary = {
        "n_cards_attempted": len(emitted_cards),
        "n_cards_passed": len(env_present),
        "n_cards_passed_with_warnings": _n_with_warnings,
        "n_cards_failed": len(env_unavailable),
        "n_cards_excluded_by_applies_when": 0,
    }
    from . import FRAMEWORK_VERSION as _fv

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


def _emit_card_figures(card_outputs: list[dict], out_dir, target: str, indication: str) -> int:
    """OPT-IN (--figures): emit per-card figures via the shared _skills_common figure-emitter
    registry into <out_dir>/figures/cards/<card_id>/. Best-effort per card; never raises (figure
    emission is additive augmentation, not the decision spine). Returns the count of figures written.

    The registry (_skills_common/_figure_emitters/) is the SAME one every consumer uses (target-profile
    dashboard, example-gallery), so a subskill --figures run produces the identical per-card SVG (+
    interactive plotly twin) — no separate plotting code. A card with no registered emitter, a missing
    card, or a failed method data load simply contributes no figure."""
    try:
        from ._figure_emitters import emit_figures_for_card
    except Exception as e:  # noqa: BLE001 — registry import is best-effort
        print(
            f"[dispatcher] --figures: figure-emitter registry unavailable "
            f"({type(e).__name__}: {e}); no figures emitted.",
            file=sys.stderr,
        )
        return 0
    figures_root = Path(out_dir) / "figures"
    n = 0
    for c in card_outputs:
        if c.get("_missing"):
            continue  # no data to plot (honest gap)
        cid = c.get("card_id")
        try:
            descs = emit_figures_for_card(cid, c.get("summary") or {}, figures_root, target, indication)
            n += len(descs)
        except Exception as e:  # noqa: BLE001 — a figure must never break the run
            print(
                f"[dispatcher] --figures: {cid} figure emission failed ({type(e).__name__}: {e}); skipped.",
                file=sys.stderr,
            )
    return n


def _build_run_parser() -> argparse.ArgumentParser:
    """Construct the standard run_wired_skill CLI parser (extracted from run_wired_skill for
    readability — byte-identical to the inline construction). Every wired skill shares this exact
    flag surface: --target/--indication/--out + the modality/synthesize/literature/subtype(s)/
    verdict-only/emit-envelope/data-mode/release-pin/figures options."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, help="HGNC gene symbol")
    # --indication is OPTIONAL (2026-08-05): TARGET-INTRINSIC skills (e.g. target-intrinsic) fan out
    # over tier:target cards that take no indication, so they invoke with --target alone. When omitted,
    # a pan-cancer sentinel is passed to resolve_cards — target-grain card readers ignore it, and an
    # indication-scoped reader invoked without a real indication degrades to data_unavailable (its
    # honest gap posture). BACKWARD-COMPATIBLE: every existing focused skill still passes --indication,
    # so their behavior is unchanged.
    ap.add_argument(
        "--indication", required=False, default=None, help="OncoTree code (optional for target-intrinsic skills)"
    )
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--modality", default=None, help="OPTIONAL post-hoc modality lens.")
    ap.add_argument(
        "--synthesize",
        action="store_true",
        help="OPT-IN: attach an LLM narration of the deterministic verdict + "
        "contextualized axes under decision['llm_synthesis']. NEVER alters the "
        "verdict spine (the decision is byte-identical without this flag).",
    )
    ap.add_argument(
        "--synthesis-model", default=None, help="Override the Bedrock synthesis model id (default: framework Opus)."
    )
    ap.add_argument(
        "--literature",
        action="store_true",
        help="OPT-IN: attach a verdict-INERT LLM LITERATURE lane (published-literature read "
        "per axis + agreement-vs-omics + omics-blind signals) under "
        "decision['literature_synthesis'], AND feed it to the --synthesize narrator as a "
        "corroboration/contradiction lane. Requires the skill to supply a literature_fn; "
        "NEVER alters the verdict spine (byte-identical without this flag).",
    )
    ap.add_argument(
        "--literature-model",
        default=None,
        help="Override the Bedrock model id for the --literature lane (default: framework Opus).",
    )
    ap.add_argument(
        "--subtype",
        default=None,
        help="OPTIONAL synthesis-grain selector: name a molecular subtype (e.g. MSI_H) to "
        "have the narration FOREGROUND that stratum's position, in addition to the "
        "across-subtype omnibus. Emphasis-only — no spine change; if the subtype is "
        "not among the computed strata, synthesis says so honestly.",
    )
    ap.add_argument(
        "--subtypes",
        default=None,
        help="OPTIONAL comma-separated molecular subtype/stratum ids (e.g. 'MSI_H,MSS'). "
        "When set AND the skill supplies a subtype_panorama_fn, resolves a DESCRIPTIVE "
        "per-stratum panorama across those strata (e.g. dependency by MSI status) and "
        "appends it to the package + headline. Does NOT affect the verdict (byte-stable "
        "regardless). Distinct from --subtype (singular), which only steers synthesis "
        "emphasis over already-computed strata.",
    )
    ap.add_argument(
        "--verdict-only",
        action="store_true",
        help="FAST/lean mode: read ONLY the verdict-relevant cards (the resolver's "
        "referenced cards, passed by the skill as verdict_cards) and skip the "
        "verdict-inert enrichment reads + any --synthesize narration. The verdict "
        "spine (verdict + driving_rule_id) is byte-identical to a full run. No-op "
        "for a skill that declares no verdict_cards subset (reads all cards).",
    )
    ap.add_argument(
        "--emit-envelope",
        action="store_true",
        help="OPT-IN (default OFF ⇒ complete no-op): ALSO write a governance-grade "
        "evidence_package.json envelope (beside decision.json) around THIS "
        "subskill's resolver verdict, via the shared _skills_common.envelope "
        "writer. PURELY ADDITIVE — decision.json is byte-identical whether or not "
        "this flag is set. The synthesis slot carries the verdict as its headline.",
    )
    ap.add_argument(
        "--data-mode",
        default="live",
        help="Data-provenance posture, carried into the emitted envelope's "
        "input_context/governance ONLY (mapped to the governance data_mode enum; "
        "a subskill envelope is exploratory-grade). D1b does NOT implement manifest "
        "pinning / resolve_release — that is a data-catalog follow-on. Inert unless "
        "--emit-envelope is set.",
    )
    ap.add_argument(
        "--release-pin",
        default=None,
        help="Optional catalog release pin, carried into the envelope governance block "
        "ONLY (no manifest resolution yet — follow-on). Inert unless --emit-envelope.",
    )
    ap.add_argument(
        "--figures",
        action="store_true",
        help="OPT-IN (default OFF ⇒ no figures): emit per-card SVG (+ interactive plotly) "
        "figures via the shared _skills_common figure-emitter registry (rehomed from "
        "the retired compose-dashboard) into "
        "<out>/figures/cards/<card_id>/. PURELY ADDITIVE — decision.json is "
        "byte-identical whether or not this flag is set. Best-effort per card: a card "
        "with no registered emitter or a failed data load contributes no figure and "
        "never breaks the run. NB: emitters re-read method data from S3, so a --figures "
        "run is materially slower than the deterministic spine.",
    )
    ap.add_argument(
        "--no-dashboard",
        action="store_true",
        help="Suppress the default-on best-effort per-subskill dashboard.html "
        "(rendered by report_render from the just-composed decision, incl. its "
        "headline.evidence_graph). PURELY ADDITIVE + display-only — decision.json is "
        "byte-identical whether or not the dashboard is written. Use for batch/backtest "
        "runs that want only the data package.",
    )
    return ap


def _merge_panorama_cards(card_outputs: list, panorama_cards: list) -> list:
    """Append the --subtypes panorama cards to the whole-cohort cards, DROPPING any whose card_id already
    appears in card_outputs. A skill may list the same card in BOTH its whole-cohort set AND
    _SUBTYPE_PANORAMA_CARDS (tumor-presence lists tumor-rna-distribution-by-subtype in both, because the
    headline reads its subtype_* fields); a naive concat then double-lists it under --subtypes, inflating
    decision["cards"]/evidence_graph.cards and double-counting the EVIDENCE_SIGNALS rollup. The panorama
    BLOCK is merged into the headline separately and the headline card-reads resolve the whole-cohort copy
    either way, so dropping the redundant append is behavior-preserving. Order-preserving; verdict-inert
    (panorama cards fire no rung). Distinct panorama cards (not in the whole-cohort set) are still appended."""
    seen = {c.get("card_id") for c in card_outputs}
    return card_outputs + [c for c in panorama_cards if c.get("card_id") not in seen]


def _attach_literature_lane(decision: dict, args, literature_fn) -> None:
    """OPT-IN --literature lane (extracted from run_wired_skill; byte-identical). Attaches the verdict-INERT decision['literature_synthesis'] AFTER the spine; honest-skip when no literature_fn is declared; a Bedrock/network fault degrades to a note and never breaks the deterministic run."""
    if getattr(args, "literature", False):
        if literature_fn is None:
            decision["literature_synthesis"] = {
                "_literature_skipped": "no_literature_lens_declared",
                "_note": (
                    "This skill declares no literature lens, so --literature is a no-op. The "
                    "deterministic decision above is complete."
                ),
            }
        else:
            try:
                decision["literature_synthesis"] = literature_fn(decision, getattr(args, "literature_model", None))
            except Exception as e:  # noqa: BLE001 — the literature lane is optional; never break the spine
                decision["literature_synthesis"] = {
                    "_literature_error": f"{type(e).__name__}: {e}",
                    "_note": "LLM literature synthesis unavailable; the deterministic verdict above is unaffected.",
                }


def _attach_synthesis_lane(decision: dict, args, synthesize_fn) -> None:
    """OPT-IN --synthesize lane (extracted from run_wired_skill; byte-identical). Attaches the sibling decision['llm_synthesis'] AFTER the spine (structurally cannot move the verdict); honest-skip when no synthesize_fn is declared (NEVER falls back to another lens); a fault degrades to a note."""
    if args.synthesize:
        # Each skill narrates through its OWN synthesizer (its tool schema + prompt match its
        # evidence), passed as synthesize_fn by the skill's run.py — INCLUDING tumor-presence, which
        # now passes synthesize_presence explicitly. When a skill declares NO narrator, --synthesize is
        # an honest no-op: we NEVER fall back to another lens's narrator. The former fallback ran the
        # PRESENCE narrator for any verdict-bearing skill without its own synthesize_fn, mis-lensing a
        # safety / mechanism / differentiation verdict through a presence prompt — the exact bug the
        # per-skill synthesize_fn was introduced to fix. There is no lens-appropriate narration for a
        # skill that declares none, so skip honestly and leave the deterministic decision intact.
        _synth = synthesize_fn
        if _synth is None:
            decision["llm_synthesis"] = {
                "_synthesis_skipped": "no_narrator_declared",
                "_note": (
                    "This skill declares no synthesis narrator, so --synthesize is a no-op — "
                    "there is no lens-appropriate narration for this grain, and the framework "
                    "will not narrate it through another skill's lens. The deterministic "
                    "decision above is complete."
                ),
            }
        else:
            try:
                decision["llm_synthesis"] = _synth(decision, args.synthesis_model, args.subtype)
            except Exception as e:  # noqa: BLE001 — synthesis is optional; never break the spine
                decision["llm_synthesis"] = {
                    "_synthesis_error": f"{type(e).__name__}: {e}",
                    "_note": "LLM synthesis unavailable; the deterministic verdict above is unaffected.",
                }


def run_wired_skill(
    *,
    skill_name: str,
    skill_version: str,
    cards: list[str],
    axis: str,
    question: str,
    verdict_fn: Optional[VerdictFn] = None,
    verdict_modality_aware: bool = False,
    headline_fn: Optional[HeadlineFn] = None,
    on_dependency_status: Optional[dict[str, str]] = None,
    partial_status_note: Optional[str] = None,
    isoform_check_target: bool = False,
    preprocess_gate: Optional[str] = None,
    synthesize_fn: Optional[SynthesizeFn] = None,
    literature_fn: Optional[Callable[[dict, Optional[str]], dict]] = None,
    subtype_panorama_fn: Optional["SubtypePanoramaFn"] = None,
    subtype_merge_fn: Optional[Callable[[dict, dict], None]] = None,
    claim_record_fn: Optional[Callable[[list, list, Optional[tuple]], dict]] = None,
    extra_axes: Optional[list[str]] = None,
    verdict_cards: Optional[list[str]] = None,
    skill_figures_fn: Optional[Callable[[dict, Path], list]] = None,
    subgroup_reader_spec: Optional[dict] = None,
    subgroup_classify: Optional[Callable] = None,
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
            Skills without a verdict function can omit this.
        verdict_modality_aware: when True the callback is invoked as
            (fired, modality=args.modality) instead of (fired). For a skill whose
            verdict consults the fired rules' per-modality `signals` block —
            today only tumor-selectivity, whose normal-breadth KILL arms are
            declared `adc: neutral` in target-contracts. Default False keeps the
            1-arg contract every other skill uses.
        headline_fn: optional callback (cards, fired, verdict_pair) → dict.
            When omitted, a minimal default headline is emitted.
        on_dependency_status: dependency-status behavior map card_id → behavior. Passed
            through from SKILL.md composition.on_dependency_status. When
            None or empty, missing cards are retained + surfaced in headline.
        partial_status_note: optional string surfaced in headline when the
            skill has status: partial (e.g. "gnomad wired; HPA IHC pending").
        isoform_check_target: when True, the dispatcher calls
            isoform_selective_targets.check_target(args.target) and injects
            two fields (isoform_selective_warning + isoform_selective_
            dominant_isoform) into the headline. Enables isoform-selective
            checking for skills that emit modality-relevant fields.
        subtype_panorama_fn: optional (target, indication, [stratum_ids]) -> dict resolver for
            a DESCRIPTIVE per-subtype panorama (e.g. dependency by MSI status). Invoked ONLY when
            the run receives --subtypes AND this fn is supplied. Its cards are appended to the
            emitted package + its panorama block merged into the headline, but they never enter
            `fired` — the verdict spine is byte-identical with or without --subtypes. When None
            (every existing caller), --subtypes is inert: a complete no-op.
        subtype_merge_fn: OPTIONAL (headline, subtype_result) -> None hook that REPLACES the generic
            flat subtype-panorama merge when a skill needs a bespoke merge the flat one can't express
            (e.g. genomic-alteration writes a NESTED headline['genomic_alteration_by_scope']['subtype']
            block). Invoked in place of the generic merge ONLY when set AND a subtype_result exists.
            Default None => the generic flat merge (byte-identical for every existing caller).
        claim_record_fn: OPTIONAL (cards, fired, verdict_pair) -> dict hook whose result is attached
            as decision['claim_record_shadow'] (VERDICT-INERT M1 factored-record shadow). Best-effort:
            a fault degrades to {'_shadow_error': ...} and never breaks the spine. Default None =>
            no standalone shadow (every existing caller — the shadow is otherwise assembled only by
            the composed target-profile fan-out).
        verdict_cards: OPTIONAL subset of `cards` that can MOVE the verdict — the resolver's
            referenced cards, from reachability.verdict_relevant_cards(gate). When --verdict-only is
            passed AND this is a non-empty SUBSET of `cards`, ONLY these cards are read: the verdict
            is byte-identical (resolve_verdict_for_gate ignores fired rules no rung references) while
            the verdict-inert enrichment reads are skipped. Default None ⇒ --verdict-only reads ALL
            cards (a complete no-op). A guard test enforces verdict_cards ⊆ cards.
        skill_figures_fn: OPTIONAL (decision, figures_dir) -> list[Path] emitter for a skill-level
            AGGREGATE figure (e.g. tumor-presence's Presence x Context hero matrix). Invoked ONLY
            under --figures, AFTER the deterministic decision is composed, reading the already-
            computed `decision` (no S3). PURELY ADDITIVE + best-effort: a failure degrades to
            no-figure and never touches the verdict spine. Default None => no skill-level figure.
        argv: optional argv override (for tests / programmatic invocation).

    Returns:
        exit code (0 on success). Raises RuntimeError under a 'fail' dependency-status behavior.
    """
    # PERF DEFAULT (2026-08-24): a standalone skill CLI run reaches its cards through resolve_cards on
    # the MAIN thread of a single-threaded process, where the forked read pool is both safe and the
    # fastest path (bypasses the GIL on the readers' pandas assembly — tumor-selectivity ~5.3s->~3.9s,
    # tumor-presence ~11.5s->~8.7s, byte-identical output). Opt this entrypoint into `process` unless
    # the caller/env already chose a pool. Scoped HERE, not in resolve_cards, so DIRECT/embedded
    # resolve_cards callers (notebooks, agent hosts, the composed target-profile fan-out — which reads
    # cards from ThreadPoolExecutor worker threads) keep the conservative thread default and never fork
    # unexpectedly. _read_cards_process still forks ONLY from a single-threaded main thread and degrades
    # to threads otherwise, so this is safe even here; escape hatch: SKILLS_READ_POOL=thread.
    os.environ.setdefault("SKILLS_READ_POOL", "process")
    ap = _build_run_parser()
    args = ap.parse_args(argv)

    # Persist a timestamped run log alongside the artifacts (development + provenance). Installed as
    # soon as --out is known so every subsequent print (card resolution, dependency-status behavior,
    # verdict, figures, warnings) is captured. Best-effort + verdict-inert: teeing output cannot
    # change the deterministic spine. Torn down before the final return (and via an atexit backstop).
    install_run_log(args.out, header={"skill": skill_name, "skill_version": skill_version})

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

    # 1. Resolve cards via the _skills_common live-readers (rehomed from the retired compose-dashboard).
    # --verdict-only reads ONLY the
    # verdict-relevant subset (verdict_cards) so enrichment reads are skipped; the verdict is
    # byte-identical because resolve_verdict_for_gate ignores fired rules no resolver rung references.
    # SAFETY: lean ONLY when verdict_cards is a non-empty SUBSET of cards; else read ALL (an
    # absent-resolver / incomplete derivation returns empty and must never silently read nothing).
    _lean = bool(args.verdict_only and verdict_cards and set(verdict_cards) <= set(cards))
    if args.verdict_only and not _lean:
        print(
            "[dispatcher] --verdict-only: no proven verdict-card subset for this skill "
            "(verdict_cards empty or not a subset of cards) — reading ALL cards (no-op).",
            file=sys.stderr,
        )
    _cards_to_read = list(verdict_cards) if _lean else cards
    if _lean:
        args.synthesize = False  # verdict-only skips narration too
        args.literature = False  # ... and the (verdict-inert) literature lane
        print(
            f"[dispatcher] --verdict-only: reading {len(_cards_to_read)}/{len(cards)} "
            f"verdict-relevant cards (enrichment reads skipped; verdict byte-identical)",
            file=sys.stderr,
        )
    # Figure Stage 3: under --figures, persist each card's plot_data DURING resolution into the SAME
    # figures/cards/<id>/ dir the figure-emitter reads from, so migrated emitters render OFFLINE (from
    # the persisted plot_data) with no second live read. Default (no --figures) => plot_data_root=None,
    # a byte-identical no-op. The figures_root here must match _emit_card_figures' Path(out)/"figures".
    _plot_data_root = (Path(args.out) / "figures") if getattr(args, "figures", False) else None
    card_outputs = resolve_cards(_cards_to_read, args.target, _indication, plot_data_root=_plot_data_root)
    _read_secs = time.perf_counter() - _t0
    _compute_start = time.perf_counter()

    # 2. Apply on_dependency_status behavior
    card_outputs, skipped_card_ids, a4_caveats = _apply_on_dependency_status(card_outputs, on_dependency_status or {})

    # 2c. CARD PREPROCESSORS (before fired_rules) — a per-gate cross-card correction that MUST travel to
    # every resolution path (standalone here + target-profile fan-out + resolve_gate_spine). The composed
    # paths already call preprocess_cards_for_gate; the standalone run_wired_skill path did NOT, so a
    # genomic-style preprocessor was silently bypassed standalone. `preprocess_gate` opts a wired skill in
    # (surface-modality-fit passes "surface_modality" to derive surface_confirmation_state). A no-op when
    # unset or the gate has no registered preprocessor, so it is byte-stable for every other skill.
    preprocess_provenance = {}
    if preprocess_gate:
        from _skills_common.card_preprocessors import preprocess_cards_for_gate

        preprocess_provenance = preprocess_cards_for_gate(card_outputs, preprocess_gate)

    # 3. Fire rules against surviving cards only
    surviving_card_ids = [c["card_id"] for c in card_outputs]
    fired = fired_rules(card_outputs, axis=axis, card_id_filter=surviving_card_ids)

    # 4. Verdict (optional callback) — the PRIMARY `axis` alone drives the verdict.
    # `verdict_modality_aware` skills additionally receive the --modality lens AND the resolved cards,
    # because their clamp consults the fired rules' OWN per-modality `signals` (tumor-selectivity: a KILL
    # arm the contract declares neutral for the chosen modality must not KILL) and gates that waiver on a
    # PRECONDITION that is a measured class no rule in the lens fires on (an affirmatively clean
    # essential-organ window — see selectivity_veto._CLEAN_ESSENTIAL_WINDOW_CLASSES). Every other skill
    # keeps the 1-arg contract, and a modality-aware skill called WITHOUT --modality gets modality=None
    # — so both paths are byte-identical to the pre-2026-09-12 behavior.
    if verdict_fn is None:
        verdict_pair = None
    elif verdict_modality_aware:
        verdict_pair = verdict_fn(fired, modality=args.modality, cards=card_outputs)
    else:
        verdict_pair = verdict_fn(fired)

    # 4a. Extra AUDIT axes (optional). A skill may fire a SECOND, self-contained axis (e.g.
    # combo-and-resistance's resistance_emergence) whose rules belong in the emitted audit spine
    # (decision['fired_rules']) + run_health.cards_fired, but must NOT touch the primary verdict.
    # Fired AFTER verdict_fn and merged into `fired`, so the resistance verdict a skill computes in
    # its headline_fn is traceable to a fired rule. Default (no extra_axes) is byte-identical.
    for _extra_axis in extra_axes or []:
        fired = fired + fired_rules(card_outputs, axis=_extra_axis, card_id_filter=surviving_card_ids)

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
            subtype_result = {
                "cards": [],
                "scope_subtypes": _subtypes,
                "_subtype_panorama_error": f"{type(e).__name__}: {e}",
            }

    # 5. Isoform-selective check (optional)
    isoform_warning = None
    if isoform_check_target:
        from .isoform_selective_targets import check_target

        isoform_warning = check_target(args.target)

    # 6. Headline (optional callback; default is a minimal skeleton)
    if headline_fn:
        # In lean (--verdict-only) mode card_outputs holds ONLY the verdict-relevant subset,
        # but a skill's headline_fn may read ENRICHMENT cards for display sub-keys via
        # get_card_field (which now RAISES on an absent card_id — surface-modality-fit is the
        # one skill that does both). Hand the headline placeholder entries for the SKIPPED
        # enrichment cards so those fields null-fill (get_card_field's documented key-absent
        # → None behavior) instead of crashing before decision.json is written. The
        # placeholders are NOT added to card_outputs, so cards_available / cards_missing /
        # emitted_cards / n_cards_resolved AND the verdict spine stay byte-identical to what
        # lean mode would otherwise emit.
        if _lean:
            _read_ids = {c["card_id"] for c in card_outputs}
            _headline_cards = card_outputs + [
                {"card_id": cid, "summary": {}, "_missing": True} for cid in cards if cid not in _read_ids
            ]
        else:
            _headline_cards = card_outputs
        # A headline_fn may OPTIONALLY declare `target` / `indication` params (e.g. to key a
        # target-scoped curated vocabulary that no resolved card exposes — tumor-presence's
        # surface-class abundance anchor, #980). Pass them ONLY when the signature declares them, so
        # every existing 3-arg headline_fn is called byte-identically (purely additive introspection;
        # mirrors resolve_cards' plot_data_out signature-gating). Never breaks on an odd callable.
        _hf_kwargs = {}
        try:
            _hf_params = inspect.signature(headline_fn).parameters
            if "target" in _hf_params:
                _hf_kwargs["target"] = args.target
            if "indication" in _hf_params:
                _hf_kwargs["indication"] = args.indication
            # A headline_fn may OPTIONALLY declare `preprocess_provenance` to receive the per-gate
            # card-preprocessor provenance (preprocess_gate above) — e.g. genomic-alteration threads
            # the family-wise-FDR + amplicon-fusion-demotion provenance into its headline. Signature-
            # gated like target/indication, so every existing headline_fn is called byte-identically.
            if "preprocess_provenance" in _hf_params:
                _hf_kwargs["preprocess_provenance"] = preprocess_provenance
            # A headline_fn may OPTIONALLY declare `modality` to receive the --modality lens — needed
            # when the lens changes the VERDICT (tumor-selectivity's modality-conditional KILL
            # suppression) so the headline can name which veto arm was waived for which modality
            # instead of a suppressed KILL going silently absent. Same signature gating.
            if "modality" in _hf_params:
                _hf_kwargs["modality"] = args.modality
        except (ValueError, TypeError):  # unintrospectable callable → 3-arg call (byte-identical)
            _hf_kwargs = {}
        headline = headline_fn(_headline_cards, fired, verdict_pair, **_hf_kwargs)
    else:
        headline = {
            "verdict": verdict_pair[0] if verdict_pair else "insufficient",
            "driving_rule_id": verdict_pair[1] if verdict_pair else None,
        }

    # CENTRAL signals-first wiring: fold hierarchy-derived sub-group signals into ANY skill that has a
    # question_hierarchy.yaml (sources bound by measurement_type, confidence = agreement × sample-size,
    # first-class per-stratum by_stratum). The sub-group SIGNAL is overlaid from the skill's claim_vector
    # (the tuned per-axis tier + evidence-atom trace) when present — the heuristic reader supplies only
    # the corroborating card sources. setdefault so a skill that emits its own (tumor-presence's
    # explicit-reader version) wins. VERDICT-INERT, best-effort — one edit wires the whole fleet.
    if isinstance(headline, dict):
        try:
            from _skills_common.subgroup_derivation import default_classify, subgroup_signals_for

            _skill_dir = Path(__file__).resolve().parent.parent / skill_name
            if (_skill_dir / "question_hierarchy.yaml").exists():
                # A skill may pass a tuned reader_spec / value→tier classify (run_wired_skill kwargs) so its
                # OWN card vocabulary is read with correct polarity + card roles; else the default heuristic.
                # The claim_vector overlays the authoritative per-axis signal; the tuned classify fixes the
                # corroborating SOURCE tiers + agreement/confidence the overlay does not set.
                _sg = subgroup_signals_for(
                    _skill_dir,
                    card_outputs,
                    reader_spec=subgroup_reader_spec,
                    classify=subgroup_classify or default_classify,
                    claim_vector=headline.get("claim_vector"),
                )
                if _sg:
                    headline.setdefault("subgroup_signals", _sg)
        except Exception:  # noqa: BLE001 — verdict-inert projection; never break the spine
            pass

    # CENTRAL evidence-capsule wiring: the complete-but-limited per-card data package (signal + 5 bounded
    # raw selector shapes + card-floor manifest). Attached to EVERY decision so it flows to BOTH LLM
    # consumers — each skill's single-lens narrator (narrator_engine reads decision['evidence_capsules'])
    # AND, via the target-profile fan-out's evidence_package, the retrieve-don't-recall cross-evidence
    # agent (each capsule row is a citable atom, satisfying the card floor). Pure selection, hash-stable,
    # VERDICT-INERT, best-effort — one edit feeds the whole fleet.
    if isinstance(headline, dict):
        try:
            from _skills_common.evidence_capsule import emit_capsules

            headline["evidence_capsules"] = emit_capsules(card_outputs, _indication)
        except Exception:  # noqa: BLE001 — verdict-inert projection; never break the spine
            pass

    # Attach dependency-status provenance + isoform-selective flags uniformly
    headline["cards_available"] = sum(1 for c in card_outputs if not c.get("_missing"))
    headline["cards_missing"] = [c["card_id"] for c in card_outputs if c.get("_missing")]
    if skipped_card_ids:
        headline["_a4_skipped_sections"] = skipped_card_ids
    if a4_caveats:
        headline["_a4_caveats"] = a4_caveats
    if partial_status_note:
        headline["_partial_status_note"] = partial_status_note
    if isoform_check_target:
        headline["isoform_selective_warning"] = isoform_warning is not None
        headline["isoform_selective_dominant_isoform"] = isoform_warning.dominant_isoform if isoform_warning else None

    # Attach the subtype panorama to the headline (DESCRIPTIVE; verdict-inert). The skill's
    # panorama_fn returns a dict with a "scope_subtypes" list + one panorama block keyed by axis
    # name; surface both for the LLM/render. Never present unless --subtypes was passed.
    if subtype_result is not None:
        if subtype_merge_fn is not None:
            # A skill with a bespoke merge (e.g. genomic's nested genomic_alteration_by_scope['subtype']
            # block, which the flat key-hoist below cannot express) owns the ENTIRE merge, including
            # subtype_scope. Best-effort: a merge fault must not break the spine (descriptive/verdict-inert).
            try:
                subtype_merge_fn(headline, subtype_result)
            except Exception as e:  # noqa: BLE001 — subtype panorama is a display facet; never load-bearing
                headline.setdefault("_enrichment_errors", {})["subtype_merge"] = f"{type(e).__name__}: {e}"
        else:
            headline["subtype_scope"] = subtype_result.get("scope_subtypes")
            for k, v in subtype_result.items():
                if k not in ("cards", "scope_subtypes"):  # the panorama block(s) + any error note
                    headline[k] = v

    # 7. Optional modality lens
    lenses = None
    invoked_lenses: dict = {}
    if args.modality:
        lenses = {args.modality: modality_lens(fired, args.modality)}
        invoked_lenses["modality"] = args.modality

    # The whole-cohort cards drive the verdict; the subtype panorama cards (if any) are appended for
    # the emitted package + LLM only — they are NOT in `fired`, so they touch no rung (spine stable).
    # DEDUP by card_id (order-preserving): a skill may list the same card in BOTH its whole-cohort set
    # AND _SUBTYPE_PANORAMA_CARDS — tumor-presence lists tumor-rna-distribution-by-subtype in both (the
    # headline reads its subtype_* fields), so a naive concat double-lists it under --subtypes, inflating
    # decision["cards"]/evidence_graph.cards and double-counting the EVIDENCE_SIGNALS rollup. The panorama
    # BLOCK is merged into the headline separately (above), and the headline card-reads resolve the
    # whole-cohort copy either way, so dropping the redundant append is behavior-preserving + verdict-inert.
    _panorama_cards = subtype_result.get("cards", []) if subtype_result else []
    emitted_cards = _merge_panorama_cards(card_outputs, _panorama_cards)
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
        emitted_cards,
        args.data_mode,
        args.release_pin,
        skills_repo_sha(),
        resolver_release_pin=_resolver_pin,
    )
    decision = make_decision_json(
        skill_name=skill_name,
        target=args.target,
        indication=_indication,
        question=question.format(target=args.target, indication=_indication),
        card_outputs=emitted_cards,
        fired=fired,
        headline=headline,
        modality_lenses=lenses,
        provenance=provenance,
    )

    # 8a. Per-subskill RUN-HEALTH record (observability; sibling key, never touches the spine).
    # status: ok = all consumed cards resolved; degraded = some card missing/skipped (dependency-status)
    # but the run completed. (A hard failure raises before here, so a written decision.json is
    # never 'error' — the ABSENCE of a fresh run_health is itself the error signal downstream.)
    _cards_missing = [c["card_id"] for c in card_outputs if c.get("_missing")]
    _cards_fired_ids = sorted({f.get("card_id") for f in fired if f.get("card_id")})
    # PROVENANCE WARNINGS (2026-08-13 multi-pair review): resolved_release_governance
    # records a per-family catalog-head resolution failure fail-open in
    # provenance.resolved_releases[<fam>].resolution_error (it must never sink emission). That error
    # was previously observable ONLY in the provenance block — run_health never read it, so a run
    # whose DGE family failed to resolve its catalog head still reported status='ok' (seen live on
    # MET-LUAD, CEACAM5-LUAD). Surface it here as a DISTINCT signal. NOTE: this does NOT flip `status`
    # — a head-resolution failure is a GOVERNANCE/reproducibility gap, not a missing verdict card (the
    # verdict cards resolved), so overloading the card-completeness `status` would be less honest.
    # A consumer wanting full integrity checks BOTH status and provenance_warnings.
    _prov_warnings = _provenance_warnings(provenance)
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
        "provenance_warnings": _prov_warnings,
        "read_secs": round(_read_secs, 4),
        "compute_secs": round(time.perf_counter() - _compute_start, 4),
        # total is stamped at the very end (below) so it includes synthesis + write.
    }

    # 8a-i. OPT-IN FACTORED-RECORD SHADOW (M1) — a skill may supply claim_record_fn to attach its
    # factored claim record beside the legacy verdict spine as decision['claim_record_shadow'].
    # VERDICT-INERT / consumed-by-nothing standalone (the composed target-profile fan-out otherwise
    # assembles the shadow from each sub-skill's _claim_record). Whole-cohort cards/fired drive it (the
    # subtype panorama is descriptive). Best-effort: a builder fault degrades to a sibling error note
    # and never breaks the run (the spine is already composed above). Default (no fn) => absent.
    if claim_record_fn is not None:
        try:
            decision["claim_record_shadow"] = claim_record_fn(card_outputs, fired, verdict_pair)
        except Exception as e:  # noqa: BLE001 — shadow is non-authoritative; never break the spine
            decision["claim_record_shadow"] = {"_shadow_error": f"{type(e).__name__}: {e}"}

    # 8a-ii. CONSOLIDATION FIDELITY (2026-08-14): does the single collapsed verdict mask a polarity
    # conflict among the fired rules? Sibling key, verdict-inert (never touches the spine). Lets any
    # consumer detect over-consolidation generically — masked_conflict=true means "read the per-card /
    # per-modality decomposition, not just the one-word verdict."
    decision["consolidation"] = _consolidation_fidelity(fired, verdict_pair[1] if verdict_pair else None)

    # 8a-iii. OPT-IN LLM LITERATURE lane (verdict-INERT). Attached as a SIBLING key
    # decision['literature_synthesis'] AFTER the deterministic decision is composed and BEFORE the
    # --synthesize narrator below, so the narrator can CITE it as a corroboration/contradiction lane.
    # Requires the skill to supply a literature_fn (via _skills_common.literature_synthesis.
    # make_literature_fn(<LENS>)); when --literature is passed but none is declared, honest-skip. A
    # failure degrades to a note — the deterministic run must never break because a network/Bedrock
    # layer is unavailable. Structurally cannot move the verdict (attached after the spine).
    _attach_literature_lane(decision, args, literature_fn)

    # 8b. OPT-IN LLM synthesis (two-slot design). Attaches a provenance-tagged narration
    # as a SIBLING key decision['llm_synthesis'] AFTER the deterministic decision is composed,
    # so it is structurally impossible for the LLM to alter the verdict spine. Never runs
    # without --synthesize; a synthesis failure degrades to a note (the deterministic run must
    # never break because the narration layer is unavailable — Bedrock auth, network, etc.).
    _attach_synthesis_lane(decision, args, synthesize_fn)

    # 8c. OPT-IN per-card figures (--figures). Emitted BEFORE write_package so the package's
    # figures/ collection (now recursive) picks them up. PURELY ADDITIVE — decision.json is
    # byte-identical whether or not --figures is set; a failure per card degrades to no-figure.
    if args.figures:
        _n_figs = _emit_card_figures(emitted_cards, args.out, args.target, _indication)
        print(f"  --figures: emitted {_n_figs} figure(s) → {Path(args.out) / 'figures'}")
        # CENTRAL per-sub-group signals-first figure (any skill with subgroup_signals). Best-effort.
        try:
            from _skills_common.subgroup_figure import emit_subgroup_figure

            _sgf = emit_subgroup_figure(decision, Path(args.out) / "figures")
            if _sgf:
                print(f"  --figures: emitted {len(_sgf)} sub-group signal figure(s)")
        except Exception:  # noqa: BLE001 — display-only; never break the run
            pass
        # OPT-IN skill-level AGGREGATE figure (--figures): a skill may supply skill_figures_fn to
        # emit a hero graphic that reads the already-computed `decision` (e.g. tumor-presence's
        # Presence × Context matrix over headline.presence_verdict_by_modality). PURELY ADDITIVE and
        # best-effort — reads no S3, decision.json is byte-identical whether or not it runs, and a
        # failure degrades to no-figure (never breaks the deterministic spine).
        if skill_figures_fn is not None:
            try:
                _skill_figs = skill_figures_fn(decision, Path(args.out) / "figures") or []
                if _skill_figs:
                    print(f"  --figures: emitted {len(_skill_figs)} skill-level figure(s)")
            except Exception as e:  # noqa: BLE001 — an aggregate figure must never break the run
                print(
                    f"[dispatcher] --figures: skill-level figure emission failed ({type(e).__name__}: {e}); skipped.",
                    file=sys.stderr,
                )

    # 8d. CENTRAL claim-graph projection (decision.headline.evidence_graph). A one-way, DISPLAY-ONLY
    # relational view over the now fully-assembled decision (verdict spine + cards + fired_rules +
    # subgroup_signals/evidence_capsules + question_table + optional literature_synthesis/llm_synthesis)
    # so renderers read explicit stably-keyed edges instead of re-deriving joins. Runs AFTER the
    # literature/synthesis attaches above (it projects them), attaches by reference into `headline`, and
    # is the ONLY new key. ADDITIVE + byte-stable + verdict-INERT + best-effort — one edit wires the
    # whole fleet; a skill without a questions.yaml still gets a referentially-intact graph.
    if isinstance(headline, dict):
        from _skills_common.evidence_graph import attach_evidence_graph

        _eg_skill_dir = Path(__file__).resolve().parent.parent / skill_name
        # SINGLE shared seam (also called from genomic's hand-rolled main + tp_fanout): builds + attaches
        # the graph incl. per-card key_evidence, self-checks referential integrity, and is fail-soft
        # (logs to headline['_enrichment_errors'], never raises). Byte-stable in the happy path.
        attach_evidence_graph(decision, _eg_skill_dir)

    # Stamp total wall-clock (read + compute + optional synthesis + figures) BEFORE write_package
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

    # 9b. DEFAULT-ON best-effort per-subskill dashboard (report_render, the ONE renderer — same
    # engine + design system as the composed target_profile.html). Renders the standalone single-skill
    # view from the just-composed decision (report_render lifts headline.evidence_graph onto the
    # skill_report, so this carries the rich per-question fingerprint + card chains + literature axes
    # when --literature ran). DISPLAY-ONLY: reads only the in-memory decision (no S3, no Bedrock);
    # decision.json is byte-identical. Fail-soft — a render fault degrades to a note, never breaks the
    # deterministic run (same discipline as the --emit-envelope block below). Opt out with --no-dashboard.
    if not getattr(args, "no_dashboard", False):
        try:
            from _skills_common.report_render import render_skill_report

            _dash = render_skill_report(
                decision,
                backend="html",
                preset="full",
                target=args.target,
                indication=_indication,
                asset_root=(args.out if getattr(args, "figures", False) else None),
            )
            (Path(args.out) / "dashboard.html").write_text(_dash, encoding="utf-8")
            print(f"  dashboard: {args.out}/dashboard.html")
        except Exception as e:  # noqa: BLE001 — dashboard is additive/display-only; never break the spine
            print(
                f"[dispatcher] dashboard render failed ({type(e).__name__}: {e}); decision.json is unaffected.",
                file=sys.stderr,
            )

    # 10. OPT-IN evidence-package envelope. Default OFF ⇒ this whole block is skipped ⇒
    # zero behavior change for every existing invocation. When set, assemble + write a sibling
    # evidence_package.json around the verdict already computed above (decision.json untouched —
    # byte-identical). A failure here degrades to a note; it must never break the deterministic run.
    if args.emit_envelope:
        try:
            _ep_path = _emit_subskill_envelope(
                args=args,
                skill_name=skill_name,
                skill_version=skill_version,
                emitted_cards=emitted_cards,
                headline=headline,
                verdict_pair=verdict_pair,
                fired=fired,
            )
            print(f"  emitted evidence_package.json → {_ep_path}")
        except Exception as e:  # noqa: BLE001 — envelope is additive; never break the spine
            print(
                f"[dispatcher] --emit-envelope: envelope emission failed "
                f"({type(e).__name__}: {e}); decision.json is unaffected.",
                file=sys.stderr,
            )

    print()
    print(json.dumps(headline, indent=2, default=str))
    restore_run_log()
    return 0
