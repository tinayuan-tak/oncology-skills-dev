#!/usr/bin/env python3
"""target-profile — composed target profile with Tier-3 LLM narrative synthesis.

Fans out to the 6 wired question-answering skills, collects their sub-
verdicts + fired rules, then invokes Bedrock (via _skills_common.llm) with
a forced structured tool_use to produce executive_summary + tension_analysis
+ recommendation. Emits target_profile.md + nomination.json + provenance.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common import (
    resolve_cards, fired_rules, modality_lens,
    synthesize_structured,
)
from _skills_common.rules_loader import load_interpretation_rules

SKILL_NAME = "target-profile"
SKILL_VERSION = "1.0.0"


# --- Sub-skill orchestration ------------------------------------------------

def _load_sub_skill_verdict_fn(skill_dir_name: str) -> Any:
    """Load a sub-skill's run.py module and return its `_verdict()` or
    `_snapshot()` function (whichever exists). Sub-skills follow the
    convention of exposing one such function; we grab it via importlib
    so target-profile doesn't hard-code each sub-skill's Python path.
    """
    run_py = SKILLS_DIR / skill_dir_name / "scripts" / "run.py"
    spec = importlib.util.spec_from_file_location(
        f"_subskill_{skill_dir_name.replace('-', '_')}", run_py,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, "_verdict", None) or getattr(module, "_snapshot", None)


# The 6 wired question-answering skills to compose. Order matches phase A→H.
SUB_SKILLS = [
    ("tumor-presence",                 "expression"),
    ("tumor-selectivity",              "selectivity"),
    ("functional-requirement",         "dependency"),
    ("mutation-profile",               "mutation"),
    ("tractability-and-modality",      "tractability"),
    ("patient-population-and-access",  "population"),
]

# Card set for each sub-skill (must match SKILL.md composition.cards_used).
SUB_SKILL_CARDS = {
    "tumor-presence": [
        "expression-distribution", "expression-tumor-vs-adjacent",
    ],
    "tumor-selectivity": ["tumor-vs-normal-selectivity"],
    "functional-requirement": [
        "pan-cancer-crispr-dependency-distribution",
        "pan-cancer-rnai-dependency-distribution",
        "crispr-rnai-dependency-concordance",
        "dependency-lineage-selectivity",
    ],
    "mutation-profile": [
        "mutation-type-counts",
        "mutation-stratified-dependency",
        "mutation-hotspot-frequency",
    ],
    "tractability-and-modality": [
        "prism-compound-activity",
        "prism-crispr-concordance",
        "dependency-predictability",
    ],
    "patient-population-and-access": ["mutation-hotspot-frequency"],
}


def _run_sub_skills(target: str, indication: str) -> dict:
    """Invoke each sub-skill's verdict logic in-process. Returns dict keyed
    by short name (`expression`, `selectivity`, ...) with:
      - `skill_dir`
      - `cards`: card_outputs from resolve_cards
      - `fired`: fired-rules list
      - `verdict`: (verdict_str, driving_rule_id) tuple or None if the
        sub-skill doesn't expose a verdict function (e.g. patient-
        population-and-access has no rules; verdict is None)
    """
    axis = "intracellular_intrinsic"
    results: dict = {}
    for skill_dir, short in SUB_SKILLS:
        cards = resolve_cards(SUB_SKILL_CARDS[skill_dir], target, indication)
        fired = fired_rules(cards, axis=axis, card_id_filter=SUB_SKILL_CARDS[skill_dir])
        verdict_fn = _load_sub_skill_verdict_fn(skill_dir)
        verdict_pair = verdict_fn(fired) if verdict_fn else None
        results[short] = {
            "skill_dir": skill_dir,
            "cards": cards,
            "fired": fired,
            "verdict": verdict_pair,  # (str, driving_rule_id) or None
        }
    return results


# --- LLM synthesis ----------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are synthesizing a target-profile summary for a drug-discovery "
    "scientist at a major pharma. You will be given deterministic, rule-"
    "derived sub-verdicts from 6 evidence dimensions (expression, "
    "selectivity, dependency, mutation, tractability, population). Your "
    "job is to (a) write a concise executive summary, (b) surface any "
    "tension across the sub-verdicts, (c) list top arguments for and "
    "against pursuing this target, and (d) recommend a nomination "
    "action. Base every claim on the provided evidence. Do NOT invent "
    "biology. If evidence is thin or missing for a dimension, say so "
    "explicitly rather than filling with generalities."
)


def _build_synthesis_tool() -> dict:
    """Tool schema for the LLM synthesis call. Enums are the audit-critical
    fields — LLM cannot free-form the recommendation."""
    return {
        "description": (
            "Emit a structured target-profile summary composed of one "
            "executive summary paragraph, tension analysis, top "
            "arguments for/against, and an overall recommendation."
        ),
        "type": "object",
        "required": [
            "executive_summary", "tension_analysis",
            "top_arguments_for", "top_arguments_against",
            "overall_recommendation", "confidence",
        ],
        "properties": {
            "executive_summary": {
                "type": "string",
                "description": (
                    "3-5 sentence synthesis of what the 6 sub-verdicts "
                    "collectively imply for this (target, indication)."
                ),
            },
            "tension_analysis": {
                "type": "string",
                "description": (
                    "Where sub-verdicts disagree and why — e.g. tumor-"
                    "selectivity says discordant while functional-"
                    "requirement says lineage_selective. If there's no "
                    "meaningful tension, say so briefly (do not invent)."
                ),
            },
            "top_arguments_for": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 5,
                "description": "Up to 5 strongest positive arguments.",
            },
            "top_arguments_against": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 5,
                "description": "Up to 5 strongest negative arguments.",
            },
            "overall_recommendation": {
                "type": "string",
                "enum": ["nominate", "hold", "veto", "insufficient_evidence"],
                "description": (
                    "Nomination action: nominate = pursue; hold = "
                    "revisit after specific evidence gaps close; veto = "
                    "do not pursue; insufficient_evidence = cannot call."
                ),
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low", "insufficient"],
                "description": (
                    "Analyst-facing confidence in the recommendation. "
                    "'insufficient' iff overall_recommendation is "
                    "insufficient_evidence."
                ),
            },
        },
    }


def _build_user_prompt(
    target: str,
    indication: str,
    sub_results: dict,
    modality: Optional[str] = None,
    therapeutic_hypothesis: Optional[str] = None,
) -> str:
    """Compose the user-message text: sub-verdicts + card summaries +
    optional lens context."""
    lines = [
        f"Target: {target}",
        f"Indication: {indication}",
    ]
    if modality:
        lines.append(f"Modality lens (post-hoc, reweight narrative): {modality}")
    if therapeutic_hypothesis:
        lines.append(f"Therapeutic hypothesis (post-hoc, reweight narrative): "
                     f"{therapeutic_hypothesis}")
    lines.append("")
    lines.append("### Sub-verdicts (deterministic, rule-fired)")
    for short, r in sub_results.items():
        v = r["verdict"]
        if v is None:
            lines.append(f"- **{short}** ({r['skill_dir']}): "
                         f"no rule-fired verdict (skill relies on raw metrics)")
        else:
            verdict_str, driving_rule = v
            lines.append(f"- **{short}** ({r['skill_dir']}): "
                         f"`{verdict_str}` (driving rule: {driving_rule})")
    lines.append("")
    lines.append("### Card summaries (raw, per-card)")
    for short, r in sub_results.items():
        lines.append(f"\n#### {short} ({r['skill_dir']})")
        for c in r["cards"]:
            cid = c["card_id"]
            if c.get("_missing"):
                lines.append(f"- {cid}: MISSING (no dispatcher)")
                continue
            summary = c.get("summary") or {}
            # Strip out oversized nested lists; keep scalars + short lists.
            trimmed = {}
            for k, v in summary.items():
                if k.startswith("_"):
                    continue
                if isinstance(v, list) and len(v) > 5:
                    trimmed[f"{k}_len"] = len(v)
                    trimmed[f"{k}_sample"] = v[:3]
                else:
                    trimmed[k] = v
            lines.append(f"- {cid}: {json.dumps(trimmed, default=str)[:1200]}")
    lines.append("")
    lines.append("### Fired rules (across all sub-skills, biology-first)")
    for short, r in sub_results.items():
        for f in r["fired"]:
            lines.append(f"- [{short}] {f['rule_id']} on "
                         f"{f['card_id']}.{f['field']} = {f['value']}")
    return "\n".join(lines)


# --- Rendering --------------------------------------------------------------

def _render_target_profile_md(
    target: str,
    indication: str,
    sub_results: dict,
    llm_output: dict,
    invoked_lenses: dict,
) -> str:
    """Render target_profile.md with clearly-tagged LLM sections."""
    lines = [
        f"# Target profile — {target} in {indication}",
        "",
        f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
    ]
    if invoked_lenses:
        lines.append(f"Invoked lenses: {invoked_lenses}")
    lines.append("")

    exec_summary = llm_output.get("executive_summary", {}).get("value", "")
    lines.append("## Executive summary *(LLM-synthesized)*")
    lines.append("")
    lines.append(exec_summary)
    lines.append("")

    tension = llm_output.get("tension_analysis", {}).get("value", "")
    lines.append("## Tension analysis *(LLM-synthesized)*")
    lines.append("")
    lines.append(tension)
    lines.append("")

    lines.append("## Sub-verdicts *(deterministic, rule-fired)*")
    lines.append("")
    lines.append("| Dimension | Verdict | Driving rule |")
    lines.append("|---|---|---|")
    for short, r in sub_results.items():
        v = r["verdict"]
        if v is None:
            lines.append(f"| {short} | — | (raw metrics; no rule verdict) |")
        else:
            verdict_str, driving_rule = v
            lines.append(f"| {short} | `{verdict_str}` | `{driving_rule}` |")
    lines.append("")

    for_args = llm_output.get("top_arguments_for", {}).get("value", []) or []
    against_args = llm_output.get("top_arguments_against", {}).get("value", []) or []
    lines.append("## Top arguments *(LLM-synthesized)*")
    lines.append("")
    lines.append("**For:**")
    for a in for_args:
        lines.append(f"- {a}")
    lines.append("")
    lines.append("**Against:**")
    for a in against_args:
        lines.append(f"- {a}")
    lines.append("")

    # llm_output stamps every field as a dict with `value` + provenance
    # metadata. Unwrap for display; nomination.json still carries full stamp.
    def _val(field: str, default: str = "—") -> str:
        raw = llm_output.get(field)
        if isinstance(raw, dict):
            return str(raw.get("value", default))
        return str(raw) if raw is not None else default

    rec = _val("overall_recommendation")
    conf = _val("confidence")
    lines.append("## Recommendation *(LLM-synthesized, enum-constrained)*")
    lines.append("")
    lines.append(f"- **Action:** `{rec}`")
    lines.append(f"- **Confidence:** `{conf}`")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*LLM-synthesized sections carry `_source: llm_synthesized` "
                 "provenance in `nomination.json`. Sub-verdicts + fired rules "
                 "are deterministic; rerunning with identical inputs "
                 "reproduces them exactly.*")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--modality", default=None,
                    help="OPTIONAL post-hoc modality lens.")
    ap.add_argument("--therapeutic-hypothesis", default=None,
                    help="OPTIONAL therapeutic hypothesis (line-of-therapy, "
                         "patient state, clinical goal). Reshapes LLM "
                         "narrative; sub-verdicts unchanged.")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    invoked_lenses: dict = {}
    if args.modality:
        invoked_lenses["modality"] = args.modality
    if args.therapeutic_hypothesis:
        invoked_lenses["therapeutic_hypothesis"] = args.therapeutic_hypothesis

    # 1. Fan out to sub-skills.
    print(f"[target-profile] Running {len(SUB_SKILLS)} sub-skills for "
          f"{args.target} in {args.indication}...", file=sys.stderr)
    sub_results = _run_sub_skills(args.target, args.indication)
    for short, r in sub_results.items():
        v = r["verdict"]
        verdict_str = v[0] if v else "(no verdict)"
        print(f"  - {short:15s} -> {verdict_str}", file=sys.stderr)

    # 2. LLM synthesis via Bedrock (structured tool_use).
    print(f"[target-profile] Invoking Bedrock synthesis...", file=sys.stderr)
    tool_schema = _build_synthesis_tool()
    user_prompt = _build_user_prompt(
        args.target, args.indication, sub_results,
        modality=args.modality,
        therapeutic_hypothesis=args.therapeutic_hypothesis,
    )
    llm_output = synthesize_structured(
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        tool_name="target_profile_synthesis",
        tool_schema=tool_schema,
    )

    # 3. Render + emit artefacts.
    md = _render_target_profile_md(
        args.target, args.indication, sub_results, llm_output, invoked_lenses,
    )
    (args.out / "target_profile.md").write_text(md)

    nomination = {
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "target": args.target,
        "indication": args.indication,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "invoked_lenses": invoked_lenses,
        "sub_verdicts": {
            short: {
                "skill_dir": r["skill_dir"],
                "verdict": r["verdict"][0] if r["verdict"] else None,
                "driving_rule_id": r["verdict"][1] if r["verdict"] else None,
                "fired_rule_ids": [f["rule_id"] for f in r["fired"]],
                "cards_missing": [c["card_id"] for c in r["cards"] if c.get("_missing")],
            }
            for short, r in sub_results.items()
        },
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
        "invoked_lenses": invoked_lenses,
        "sub_skills_ran": [s for s, _ in SUB_SKILLS],
        "llm_prompt_hash": llm_output.get("executive_summary", {}).get("_prompt_hash"),
        "llm_model_id": llm_output.get("executive_summary", {}).get("_model_id"),
        "artefacts": ["target_profile.md", "nomination.json"],
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
