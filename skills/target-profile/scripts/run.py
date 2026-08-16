#!/usr/bin/env python3
"""target-profile — composed target profile with Tier-3 LLM narrative synthesis.

Fans out to the 10 question-answering sub-skills in SUB_SKILLS (tumor-presence,
tumor-selectivity, functional-requirement, synthetic-lethal-partners, mechanism-
and-pharmacology, genomic-alteration-profile, differentiation-landscape,
tractability-small-molecule, surface-modality-fit, on-target-safety-liability)
+ an opt-in subtype_fit tier (--subtypes), collects their sub-verdicts + fired
rules, then invokes Bedrock (via _skills_common.llm) with a forced structured
tool_use to produce executive_summary + tension_analysis + recommendation. The
LLM's overall_recommendation is CLAMPED by the deterministic one-directional
nomination gate. Emits target_profile.md + nomination.json + provenance.

Each sub-skill is scoped to its OWN SUB_SKILL_CARDS entry (card_id_filter), so a
card must be in a sub-skill's entry to be seen by THAT sub-skill's verdict — a
card composed only under another sub-skill is invisible here (the resolver-
dependency completeness guard in tests/ enforces this).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

# scripts/ on sys.path so the sibling tp_* modules resolve regardless of how run.py
# is loaded (tests exec it via importlib.spec_from_file_location, which does NOT add
# scripts/ to sys.path). tp_common additionally puts the skills root on the path so
# `_skills_common` is importable.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

# The 5,138-LOC composer was split into cohesive sibling modules (2026-08-16). run.py
# stays the CLI entrypoint + orchestration (main); everything else lives in the tp_*
# modules and is re-exported here so the module's public surface — and every test that
# reaches into it (run._biomarker_facet, run.SUB_SKILL_CARDS, ...) — is byte-identical.
from tp_common import *              # noqa: F401,F403
from tp_common import SKILL_NAME, SKILL_VERSION, SKILLS_DIR, _framework_model_version
from tp_fanout import *              # noqa: F401,F403
from tp_fanout import SUB_SKILLS, _run_sub_skills, _skipped_synthesis_output
from tp_gates import *               # noqa: F401,F403
from tp_gates import (               # names main() calls directly
    _CONFIDENCE_RANK, _TIER_TO_CONFIDENCE, _gate_recommendation, _gate_scorecard, _positive_tier,
)
from tp_facets import *              # noqa: F401,F403
from tp_facets import (
    _addressable_population_facet, _biomarker_facet, _deciding_axis, _fragility_facet,
    _heterogeneity_facet, _ordinal_matrix, _subtype_facet,
)
from tp_synthesis_prompt import *    # noqa: F401,F403
from tp_synthesis_prompt import _SYSTEM_PROMPT, _METRIC_LEGEND, _build_synthesis_tool, _build_user_prompt
from tp_render_md import *           # noqa: F401,F403
from tp_render_md import _render_target_profile_md
from tp_render_html import *         # noqa: F401,F403
from tp_render_html import _render_target_profile_html
from tp_evidence_package import *    # noqa: F401,F403
from tp_evidence_package import (
    _catalogue_rows_from_sub_results, _emit_card_figures, _validation_summary_from_sub_results,
    _write_evidence_package,
)

# _skills_common symbols invoked directly by main() (modality_lens preserved from the
# pre-split import surface).
from _skills_common import modality_lens, synthesize_structured, render_composite_panel
from _skills_common import ordinal_view
from _skills_common.envelope import build_governance




def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--subtypes", default=None,
                    help="Comma-separated molecular subgroup ids to scope the "
                         "profile to (e.g. 'MSI_H,MSS'). When set, the subtype "
                         "tier is evaluated: a MEASURED, floor-cleared subtype "
                         "that is NOT a dependency holds the nomination. Omit for "
                         "a whole-cohort profile (backward-compatible default).")
    ap.add_argument("--modality", default=None,
                    help="OPTIONAL post-hoc modality lens.")
    ap.add_argument("--release-pin", default=None,
                    help="OPTIONAL data release_pin to STAMP into governance/provenance for "
                         "reproducibility (parity with compose-dashboard). Pass-through only: "
                         "target-profile reads live and does NOT auto-resolve the release — absent "
                         "this flag the pin is recorded as 'unpinned' (honest, never fabricated). "
                         "Auto-resolution is a deferred data-catalog follow-on.")
    ap.add_argument("--therapeutic-hypothesis", default=None,
                    help="OPTIONAL therapeutic hypothesis (line-of-therapy, "
                         "patient state, clinical goal). Reshapes LLM "
                         "narrative; sub-verdicts unchanged.")
    ap.add_argument("--no-figures", action="store_true",
                    help="VERDICT-ONLY mode: skip per-card figure emission + the interactive HTML "
                         "(the 4.6MB inlined plotly.js + the figure double-read). Emits "
                         "nomination.json + target_profile.md + provenance + a STATIC (no-JS) HTML. "
                         "The deterministic verdict spine is byte-identical to a full run — figures "
                         "never feed the verdict. Use for fast iteration / re-runs; render later via "
                         "the deferred-render path. (Perf Stage 1, 2026-07-23.)")
    ap.add_argument("--no-synthesis", action="store_true",
                    help="Skip the Tier-3 Bedrock LLM synthesis (executive-summary / tension / "
                         "recommendation narrative). The deterministic verdict spine — sub-verdicts, "
                         "recommendation gate, positive tier, deciding axis, scorecard, facets — is "
                         "computed independently of the LLM and stays byte-identical to a full run. "
                         "nomination.json marks llm_synthesis._synthesis_skipped; the report shows a "
                         "note in place of the narrative. Removes the serial, non-cacheable network tail.")
    ap.add_argument("--verdict-only", action="store_true",
                    help="Umbrella fast/CI/iteration mode: implies --no-synthesis AND --no-figures. "
                         "Emits the deterministic nomination (nomination.json + a narrative-free "
                         "target_profile.md + provenance) with no Bedrock call and no figure/panel "
                         "render. The verdict spine is byte-identical to a full run.")
    ap.add_argument("--profile-timers", action="store_true",
                    help="Emit per-sub-skill READ vs FIGURE-EMIT wall-clock timings to stderr "
                         "(instrumentation only; zero effect on artifacts). (Perf Stage 0.)")
    ap.add_argument("--emit", choices=["nomination", "evidence-package"], default="nomination",
                    help="Output shape. 'nomination' (default) → nomination.json + target_profile.md "
                         "+ provenance (the biologist-facing narrated profile). 'evidence-package' → "
                         "a deterministic, LLM-free evidence_package.json envelope (the same machine-"
                         "facing shape compose-dashboard emits), assembled from the SAME per-sub-skill "
                         "verdict spine. evidence-package implies --no-synthesis + --no-figures and "
                         "emits no nomination.json / md / html.")
    args = ap.parse_args()

    # --verdict-only is the umbrella fast mode: skip BOTH the LLM synthesis tail and figure/panel
    # rendering. Both are verdict-inert, so the deterministic spine is unaffected.
    if args.verdict_only:
        args.no_synthesis = True
        args.no_figures = True

    # --emit evidence-package is a MACHINE artifact: deterministic + LLM-free by construction, and
    # never renders the nomination-oriented md/html/figures. The deterministic verdict spine it reads
    # (sub-verdicts, recommendation gate, deciding axis) is byte-identical to a nomination run.
    if args.emit == "evidence-package":
        args.no_synthesis = True
        args.no_figures = True

    args.out.mkdir(parents=True, exist_ok=True)

    invoked_lenses: dict = {}
    if args.modality:
        invoked_lenses["modality"] = args.modality
    if args.therapeutic_hypothesis:
        invoked_lenses["therapeutic_hypothesis"] = args.therapeutic_hypothesis

    # 1. Fan out to sub-skills.
    print(f"[target-profile] Running {len(SUB_SKILLS)} sub-skills for "
          f"{args.target} in {args.indication}...", file=sys.stderr)
    subtypes = [s.strip() for s in args.subtypes.split(",") if s.strip()] if args.subtypes else None
    _fanout_t0 = time.perf_counter() if args.profile_timers else 0.0
    sub_results = _run_sub_skills(args.target, args.indication, subtypes=subtypes,
                                  profile_timers=args.profile_timers)
    if args.profile_timers:
        print(f"[perf] === fan-out total {time.perf_counter() - _fanout_t0:6.1f}s ===",
              file=sys.stderr)
    for short, r in sub_results.items():
        v = r["verdict"]
        verdict_str = v[0] if v else "(no verdict)"
        print(f"  - {short:15s} -> {verdict_str}", file=sys.stderr)

    # Ordinal matrix VIEW (gap #3 "now"): gate × modality signals projected onto the ordinal
    # scale. Labeled, additive, NOT a verdict input (ordinal_view contract). Computed BEFORE the
    # prompt so synthesis can reason over the matrix-SLICE (gap #4b), not only the flat verdict
    # list; also emitted in nomination.json for downstream consumers.
    ordinal_matrix = _ordinal_matrix(sub_results)

    # Biomarker convergence facet (Q12, Part 3c): a deterministic, additive, verdict-inert assembly of
    # the scattered biomarker byproducts (corroboration + stratification + preferred_assay). Like the
    # ordinal matrix, computed BEFORE the prompt so synthesis can reason over it, and emitted in
    # nomination.json. One-directional: informs confidence, never mints a nominate.
    biomarker_facet = _biomarker_facet(sub_results)

    # Subtype convergence facet (capstone Part 3c integration layer): converge the three
    # subtype-grain panoramas (expression / dependency / mutation-frequency) BY molecular subtype
    # to surface cross-axis patient-selection strata. Like the biomarker facet: deterministic,
    # additive, verdict-inert; computed before the prompt so synthesis can reason over it, and
    # emitted in nomination.json. One-directional — informs confidence, never mints a nominate.
    subtype_facet = _subtype_facet(sub_results, indication=args.indication)

    # Fragility facet (2026-08-12): verdict-inert flip-stability — the quantitative "how solid is this
    # call?" scalar. Worst-case single-rule flip-fragility over the decision-relevant axes (+ a
    # coverage floor for blind axes), computed by re-running the deterministic resolver over perturbed
    # fired-rule sets. Like the other facets: computed BEFORE the prompt, emitted in nomination.json,
    # and STRICTLY verdict-inert — it never calls the gate and never writes overall_recommendation /
    # confidence. May set a categorical `contested` flag (declarative threshold) for the reader/banner.
    fragility = _fragility_facet(sub_results, subtypes=subtypes, modality=args.modality)
    # Heterogeneity facet (2026-08-12): verdict-inert cross-context DISPERSION — does a pooled
    # verdict hide a split across comparators / assays / molecular subtypes? Companion to fragility;
    # never touches the recommendation.
    heterogeneity = _heterogeneity_facet(sub_results, subtypes=subtypes)
    addressable_population = _addressable_population_facet(sub_results)

    # Biology-axis EMPHASIS STEER (2026-08-05): resolve the target's curated biology_axis +
    # plausible modalities so synthesis foregrounds the modalities the biology supports (fixes
    # surface-antigen over-emphasis for intracellular targets). Resolution NEVER raises — an
    # uncurated target resolves to axis=unknown and the block says "do not assume a modality
    # class." SLOT-2 emphasis only; the deterministic verdict + gate recommendation are untouched.
    from _skills_common.biology_axis import resolve_biology_axis
    axis_info = resolve_biology_axis(args.target)

    # 2. LLM synthesis via Bedrock (structured tool_use) — SKIPPED under --no-synthesis/--verdict-only.
    # The deterministic spine (sub-verdicts, recommendation gate, positive tier, deciding axis,
    # scorecard, facets) is computed independently below and is byte-identical whether or not
    # synthesis runs, so the skipped path emits a stub the gate clamps into + the renderers degrade
    # to a "synthesis skipped" note.
    if args.no_synthesis:
        llm_output = _skipped_synthesis_output()
        print("[target-profile] --verdict-only/--no-synthesis: skipped Bedrock synthesis "
              "(deterministic verdict spine is authoritative)", file=sys.stderr)
    else:
        print(f"[target-profile] Invoking Bedrock synthesis (biology_axis={axis_info['biology_axis']})...",
              file=sys.stderr)
        tool_schema = _build_synthesis_tool()
        user_prompt = _build_user_prompt(
            args.target, args.indication, sub_results,
            modality=args.modality,
            therapeutic_hypothesis=args.therapeutic_hypothesis,
            ordinal_matrix=ordinal_matrix,
            biomarker_facet=biomarker_facet,
            subtype_facet=subtype_facet,
            axis_info=axis_info,
        )
        llm_output = synthesize_structured(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            tool_name="target_profile_synthesis",
            tool_schema=tool_schema,
        )
        # Attach the deterministic cross-cutting metric legend (sibling key) so a non-computational
        # reader has an accurate reference for the quantities cited across lenses — independent of the
        # LLM's inline glosses. On a successful narration only (a degraded/error dict stays minimal).
        if isinstance(llm_output, dict) and "_synthesis_error" not in llm_output:
            llm_output.setdefault("metric_legend", _METRIC_LEGEND)

    # 2b. Deterministic recommendation gate. A killer sub-verdict FORCES the
    # recommendation regardless of what the LLM chose — the auditable rule wins.
    # We clamp the wrapped {value, _source, ...} in place and record the override
    # in nomination.json + provenance so the gate is never silent.
    gate_action, gate_hits, gate_suppressions = _gate_recommendation(
        sub_results, modality=args.modality)
    recommendation_gate = {"fired": bool(gate_action),
                           "suppressed_vetoes": gate_suppressions}
    if gate_suppressions:
        print(f"[target-profile] recommendation gate SUPPRESSED "
              f"{[s['short']+':'+s['verdict']+' via '+s['suppressed_by']['kind'] for s in gate_suppressions]}",
              file=sys.stderr)
    confidence_tier = {"tier": None}
    if gate_action:
        rec = llm_output.get("overall_recommendation")
        llm_value = rec.get("value") if isinstance(rec, dict) else rec
        recommendation_gate = {
            "fired": True,
            "forced_recommendation": gate_action,
            "llm_recommendation": llm_value,
            "overridden": llm_value != gate_action,
            "triggered_by": gate_hits,
            "suppressed_vetoes": gate_suppressions,
        }
        if isinstance(rec, dict):
            rec["value"] = gate_action
            rec["_gated"] = True  # mark the value as rule-forced, not LLM-chosen
        else:
            llm_output["overall_recommendation"] = {
                "value": gate_action, "_source": "recommendation_gate"}
        print(f"[target-profile] recommendation GATE fired: forced '{gate_action}' "
              f"(LLM said '{llm_value}') via {[h['short']+':'+h['verdict'] for h in gate_hits]}",
              file=sys.stderr)
    else:
        # NO kill fired → the positive tier may raise a deterministic confidence
        # FLOOR. F1-safe: this branch is unreachable when a kill fired; it touches
        # ONLY `confidence`, never `overall_recommendation` (never forces nominate).
        tier, pos_hits = _positive_tier(sub_results, modality=args.modality)
        confidence_tier = {"tier": tier, "hits": pos_hits}
        if tier:
            floor = _TIER_TO_CONFIDENCE[tier]  # strong→high, moderate→medium
            conf = llm_output.get("confidence")
            llm_conf = conf.get("value") if isinstance(conf, dict) else conf
            # Apply as a floor: never lower the LLM's confidence, only raise it.
            if _CONFIDENCE_RANK.get(floor, 0) > _CONFIDENCE_RANK.get(llm_conf, 0):
                if isinstance(conf, dict):
                    conf["value"] = floor
                    conf["_floored_by_positive_tier"] = True
                else:
                    llm_output["confidence"] = {
                        "value": floor, "_source": "positive_tier"}
                confidence_tier["floored_from"] = llm_conf
                confidence_tier["floored_to"] = floor
            print(f"[target-profile] positive tier: {tier} "
                  f"(dims={sorted({h['short'] for h in pos_hits})}); "
                  f"confidence floor {floor}", file=sys.stderr)

    # Deciding-axis router (L): name the load-bearing gate + whether the framework can
    # evidence it. Reports (never predicts): a fired gate is the deciding axis; on abstention,
    # the unevidenced necessity gates are the routing instruction. Purely additive — reads the
    # already-resolved gate/positive state, touches no verdict.
    deciding_axis = _deciding_axis(
        sub_results, gate_action, gate_hits,
        positive_hits=confidence_tier.get("hits", []) or [],
    )
    print(f"[target-profile] deciding axis [{deciding_axis['basis']}]: "
          f"{deciding_axis.get('routing', '')}", file=sys.stderr)

    # Gate scorecard (deterministic, top-of-report): 8-gate rows from the gate registry, 4-state
    # status reusing the nomination-gate policy. Also emitted in nomination.json.
    scorecard = _gate_scorecard(sub_results, deciding_axis, modality=args.modality)
    catalogue_rows = _catalogue_rows_from_sub_results(sub_results)

    # 5-field validation_summary — the shared evidence-package writer's contract, composed from
    # target-profile's card-read model (passed = card returned usable data; failed = absent/not-wired
    # OR data_unavailable; passed_with_warnings + excluded_by_applies_when = 0: no method validation,
    # no target-level applies_when gating). Computed HERE (before the emit branch) so the
    # evidence-package emitter and the nomination path below share ONE construction.
    validation_summary = _validation_summary_from_sub_results(sub_results)

    # --emit evidence-package: emit the deterministic machine envelope from the verdict spine and
    # RETURN, skipping every nomination-oriented render (composite panel / md / html / nomination.json
    # / provenance). The spine it reads is byte-identical to a nomination run.
    if args.emit == "evidence-package":
        ep_path = _write_evidence_package(
            args=args, sub_results=sub_results, gate_action=gate_action,
            recommendation_gate=recommendation_gate, confidence_tier=confidence_tier,
            deciding_axis=deciding_axis, validation_summary=validation_summary,
        )
        print(f"[target-profile] wrote {ep_path} (evidence-package; deterministic, LLM-free)")
        print(f"Recommendation: {gate_action or '(no gate fired)'}")
        return 0

    # 3a. Render composite panel PNG + SVG (Shape C — slide-drop artefact).
    figures_dir = args.out / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    composite_png = figures_dir / "target_profile_at_a_glance.png"
    composite_rel = None
    if args.verdict_only:
        # --verdict-only: the "at a glance" panel is a matplotlib figure that also narrates the LLM
        # recommendation — skip it with the rest of the figures. The md/html degrade to no-image.
        print("[target-profile] --verdict-only: skipped composite panel render", file=sys.stderr)
    else:
        try:
            render_composite_panel(
                out_path=composite_png,
                target=args.target,
                indication=args.indication,
                sub_results=sub_results,
                llm_output=llm_output,
            )
            composite_rel = f"figures/{composite_png.name}"
            print(f"[target-profile] wrote {composite_png} (+ .svg companion)",
                  file=sys.stderr)
        except Exception as e:
            # Panel rendering must never block artefact emission. Log + continue
            # with no image reference in the markdown.
            composite_rel = None
            print(f"[target-profile] WARN: composite panel render failed: {e}",
                  file=sys.stderr)

    # 3a-bis. Produce per-card distribution figures (SVG + interactive .plotly.json) via the shared
    # figure registry. This is the dynamic-dashboard Phase B change: a run now PRODUCES the per-card
    # charts (previously rules/summary-only). Best-effort — never blocks artefact emission.
    # PERF Stage 1: --no-figures skips this (the figure double-read + the 4.6MB plotly inline). The
    # HTML then degrades to the tested static no-JS fallback; the verdict spine is byte-identical
    # (card_figures never feeds nomination.json / sub_verdicts — it's a separate presentation slot).
    if args.no_figures:
        card_figures = {}
        print("[target-profile] --no-figures: skipped per-card figure emission (verdict-only mode)",
              file=sys.stderr)
    else:
        _fig_t0 = time.perf_counter() if args.profile_timers else 0.0
        card_figures = _emit_card_figures(sub_results, figures_dir, args.target, args.indication)
        if args.profile_timers:
            print(f"[perf] === figure-emit total {time.perf_counter() - _fig_t0:6.1f}s ===",
                  file=sys.stderr)

    # 3b. Render + emit markdown artefact (Shape A — enriched).
    md = _render_target_profile_md(
        args.target, args.indication, sub_results, llm_output, invoked_lenses,
        composite_figure_relpath=composite_rel,
        deciding_axis=deciding_axis,
        ordinal_matrix=ordinal_matrix,
    )
    (args.out / "target_profile.md").write_text(md)

    # 3c. Render + emit the static HTML governance artifact (self-contained; inlines the
    # composite SVG). Pure projection — never blocks emission on failure.
    try:
        composite_svg = composite_png.with_suffix(".svg") if composite_rel else None
        htmldoc = _render_target_profile_html(
            args.target, args.indication, sub_results, llm_output, invoked_lenses,
            deciding_axis=deciding_axis, ordinal_matrix=ordinal_matrix,
            scorecard=scorecard, composite_svg_path=composite_svg,
            catalogue_rows=catalogue_rows, recommendation_gate=recommendation_gate,
            card_figures=card_figures, figures_dir=figures_dir,
        )
        (args.out / "target_profile.html").write_text(htmldoc)
        print(f"[target-profile] wrote {args.out}/target_profile.html", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"[target-profile] WARN: HTML render failed: {e}", file=sys.stderr)

    # Governance / reproducibility. Phase-D convergence (#9): build the governance block via the SHARED
    # _skills_common.build_governance so it can no longer drift from compose-dashboard's — same keys,
    # same construction, one source. Uses the 5-field validation_summary composed above (shared with
    # the --emit evidence-package path). release_pin is a pass-through (target-profile reads live and
    # does not auto-resolve the release); honest default 'unpinned'.
    governance = build_governance("live_latest", args.release_pin or "unpinned", validation_summary)
    # Additive target-profile annotation (does NOT alter the shared 3-key core → no schema drift):
    governance["_note"] = (
        "target-profile reads live data; release auto-resolution is a deferred data-catalog "
        "follow-on, so release_pin is 'unpinned' unless supplied via --release-pin.")

    nomination = {
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "target": args.target,
        "indication": args.indication,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "governance": governance,
        "invoked_lenses": invoked_lenses,
        "sub_verdicts": {
            short: {
                "skill_dir": r["skill_dir"],
                "verdict": r["verdict"][0] if r["verdict"] else None,
                "driving_rule_id": r["verdict"][1] if r["verdict"] else None,
                "fired_rule_ids": [f["rule_id"] for f in r["fired"]],
                # cards_used: the ACTUAL card set this sub-skill resolved this run (2026-08-12
                # reproducibility fix). Previously only cards_MISSING was recorded, leaving the positive
                # pulled set implicit in the static SUB_SKILL_CARDS map — insufficient to reproduce a run
                # or key an eval ledger. Now the full set + the missing subset are both on the record.
                "cards_used": [c["card_id"] for c in r["cards"]],
                "cards_missing": [c["card_id"] for c in r["cards"] if c.get("_missing")],
            }
            for short, r in sub_results.items()
        },
        "recommendation_gate": recommendation_gate,
        "confidence_tier": confidence_tier,
        "deciding_axis": deciding_axis,
        "gate_scorecard": scorecard,
        "ordinal_matrix_view": ordinal_matrix,
        # Biomarker convergence facet (Q12, Part 3c): corroboration + stratification + preferred_assay.
        # A FACET (not a gate) — informs confidence + patient-selection; never mints a nominate.
        "biomarker_facet": biomarker_facet,
        # Subtype convergence facet (Part 3c integration layer): the per-molecular-subtype cross-axis
        # convergence (expression / dependency / mutation-frequency). A FACET (not a gate) — defines
        # patient-selection strata + informs confidence; never mints a nominate.
        "subtype_facet": subtype_facet,
        # Fragility facet (verdict-inert flip-stability): worst-case single-rule flip-fragility over the
        # decision-relevant axes + a `contested` flag (declarative threshold). A structural sensitivity
        # measure ("how solid is this call?"), NOT a probability — informs the reader, never mints or
        # moves a recommendation (target_index/contested touch neither the gate nor confidence).
        "fragility": fragility,
        # Heterogeneity facet (verdict-inert): cross-context dispersion (comparator / modality /
        # subtype). A stratified-opportunity signal the pooled verdict hides; never moves the call.
        "heterogeneity": heterogeneity,
        "addressable_population": addressable_population,
        # Per-card figures produced this run (SVG + interactive .plotly.json siblings), keyed by
        # card_id, paths relative to figures/. The dynamic HTML renderer (Phase B PR-2) embeds the
        # `dynamic: True` Plotly specs; falls back to the SVG otherwise.
        "card_figures": card_figures,
        "llm_synthesis": llm_output,
    }
    (args.out / "nomination.json").write_text(
        json.dumps(nomination, indent=2, default=str)
    )

    provenance = {
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "target": args.target,
        "indication": args.indication,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "governance": governance,
        "invoked_lenses": invoked_lenses,
        "sub_skills_ran": [s for s, _ in SUB_SKILLS],
        "recommendation_gate": recommendation_gate,
        "confidence_tier": confidence_tier,
        "deciding_axis": deciding_axis,
        "llm_prompt_hash": llm_output.get("executive_summary", {}).get("_prompt_hash"),
        "llm_model_id": llm_output.get("executive_summary", {}).get("_model_id"),
        # Governance item B (2026-07-20): the DECLARED framework model pin. Distinct
        # from llm_model_id (the model that actually ran) — when the two diverge, an
        # env override was used. Auditors compare them to detect per-run drift.
        "framework_model_version": _framework_model_version(),
        "artefacts": [
            "target_profile.md",
            "target_profile.html",
            "nomination.json",
        ] + ([] if args.no_figures else [
            "figures/target_profile_at_a_glance.png",
            "figures/target_profile_at_a_glance.svg",
        ]),
    }
    (args.out / "provenance.yaml").write_text(yaml.safe_dump(provenance, sort_keys=False))

    print(f"[target-profile] wrote {args.out}/target_profile.md")
    print(f"[target-profile] wrote {args.out}/nomination.json")
    print(f"[target-profile] wrote {args.out}/provenance.yaml")
    print()
    def _unwrap(raw):
        return raw.get("value") if isinstance(raw, dict) else raw
    print(f"Recommendation: {_unwrap(llm_output.get('overall_recommendation'))}")
    print(f"Confidence:     {_unwrap(llm_output.get('confidence'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
