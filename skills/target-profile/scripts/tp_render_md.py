"""target-profile — Markdown report renderer + the risk-by-category rollup it leads with."""
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

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from _skills_common import ordinal_view
from tp_common import PHASE_METRIC_FIELDS, _first_card_summary_field, _fmt_metric




def _risk_by_category_from_sub_verdicts(sub_results: dict) -> list[tuple[str, str, str]]:
    """Map sub-verdicts onto the 6-category risk framing (biological /
    druggability / translational / clinical / safety / commercial),
    producing (category, level, driver) triples. Categories with no
    wired coverage return level=insufficient_evidence — honest coverage
    signal for governance readers used to the 6-category shape.

    This is a NON-LLM mapping — deterministic reshape of the deterministic
    sub-verdicts. The v1 risk-assessment framing lives here as an output
    convention, not as a re-derivation via literature.
    """
    def _v(short):
        r = sub_results.get(short) or {}
        v = r.get("verdict")
        return v if v else (None, None)

    exp_v, exp_r = _v("expression")
    sel_v, sel_r = _v("selectivity")
    dep_v, dep_r = _v("dependency")
    # Short keys MUST match SUB_SKILLS (run.py:65). Fixed 2026-07-17: the
    # 2026-07-14 restructure renamed these two shorts (mutation→genomic_alteration,
    # tractability→tractability_sm) but this reshape wasn't updated, so _v() silently
    # returned (None,None) — druggability was dead-wired to insufficient_evidence and
    # the mutation signal was dropped from _biological(). A display bug (this feeds the
    # 6-category render table, not the gate), but a real one.
    mut_v, mut_r = _v("genomic_alteration")
    trk_v, trk_r = _v("tractability_sm")
    saf_v, saf_r = _v("safety")

    # Biological: strongest positive across A/B/C/mut wins
    # Simple mapping: at least one strong-supportive → LOW risk; not_selective
    # or non_dependent → HIGH; discordant / not_informative → MEDIUM
    def _biological():
        signals = [exp_v, sel_v, dep_v, mut_v]
        if any(s in ("strong_tumor_selective", "concordant_dependent",
                      "biomarker_stratified_dependency",
                      "broadly_high_expression") for s in signals):
            return "LOW", "strong support across A/B/C/mut sub-verdicts"
        if any(s in ("not_selective", "non_dependent",
                      "broadly_low_expression") for s in signals):
            return "HIGH", "negative signal in A/B/C sub-verdicts"
        if any(s == "discordant_across_comparators" for s in signals):
            return "MEDIUM", "comparator-dependent expression/selectivity signal"
        if all(s in (None, "insufficient", "not_informative") for s in signals):
            return "insufficient_evidence", "no rule-fired verdicts across A/B/C"
        return "MEDIUM", "mixed signals across A/B/C"

    def _druggability():
        if trk_v in ("well_covered", "chemically_confirmed_genetic"):
            return "LOW", trk_r or "PRISM-CRISPR triangulated"
        if trk_v in ("chemically_active",):
            return "LOW-MEDIUM", trk_r or "clinically-active compounds"
        if trk_v in ("tool_compound_only", "weakly_active"):
            return "MEDIUM-HIGH", trk_r or "tool compounds only"
        if trk_v in ("chemically_unhit", "discordant"):
            return "HIGH", trk_r or "no compound hits or discordant"
        return "insufficient_evidence", "tractability sub-verdict absent"

    def _safety():
        # on-target-safety-liability IS wired (gnomAD LoF-constraint). Fixed
        # 2026-07-17: this row was hardcoded insufficient_evidence with a stale
        # "gnomAD cards not wired" note, contradicting the wired safety sub-skill
        # that already feeds the nomination gate. Map its verdict here too.
        # Higher germline constraint → higher on-target (full-KO) safety RISK.
        if saf_v == "highly_constrained_safety_concern":
            return "HIGH", saf_r or "highly LoF-constrained gene (full-KO liability)"
        if saf_v == "moderately_constrained_safety":   # C2c: middle band → MEDIUM
            return "MEDIUM", saf_r or "moderately LoF-constrained gene (equivocal safety)"
        if saf_v == "tolerant_reduced_safety_risk":
            return "LOW", saf_r or "LoF-tolerant gene (reduced full-KO liability)"
        return "insufficient_evidence", "gnomAD constraint sub-verdict absent"

    # For phases we still have no wired data on, report insufficient_evidence
    # honestly rather than fabricate:
    return [
        ("biological",   *_biological()),
        ("druggability", *_druggability()),
        ("translational", "insufficient_evidence",
            "Phase-J (translational-readiness) placeholder — data not wired"),
        ("clinical",      "insufficient_evidence",
            "Phase-E (clinical precedent) placeholder — data feed not wired"),
        ("safety",        *_safety()),
        ("commercial",    "insufficient_evidence",
            "Phase-E (competitive/IP) placeholder — Cortellis/IQVIA not licensed"),
    ]


def _render_target_profile_md(
    target: str,
    indication: str,
    sub_results: dict,
    llm_output: dict,
    invoked_lenses: dict,
    composite_figure_relpath: Optional[str] = None,
    deciding_axis: Optional[dict] = None,
    ordinal_matrix: Optional[dict] = None,
) -> str:
    """Render target_profile.md with clearly-tagged LLM sections + per-phase
    evidence tables + risk-by-category summary + deciding-axis routing + the
    ordinal evidence matrix + embedded composite figure. deciding_axis + ordinal_matrix
    are DETERMINISTIC (not LLM) — surfaced so a human reader sees the same routing +
    modality view that land in nomination.json, not only the LLM narrative."""
    lines = [
        f"# Target profile — {target} in {indication}",
        "",
        f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
    ]
    if invoked_lenses:
        lines.append(f"Invoked lenses: `{invoked_lenses}`")
    lines.append("")

    # --- Composite figure (Shape C) ----------------------------------------
    if composite_figure_relpath:
        lines.append(f"![Target profile at a glance]({composite_figure_relpath})")
        lines.append("")

    # --- Executive summary (LLM) -------------------------------------------
    exec_summary = llm_output.get("executive_summary", {}).get("value", "")
    lines.append("## Executive summary *(LLM-synthesized)*")
    lines.append("")
    lines.append(exec_summary)
    lines.append("")

    # --- Recommendation (LLM) — pulled up front for governance readers -----
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

    # --- Deciding axis (deterministic router; reports, never predicts) -----
    if deciding_axis:
        lines.append("## Deciding axis *(deterministic — what the call hinges on)*")
        lines.append("")
        basis = deciding_axis.get("basis")
        lines.append(f"_{deciding_axis.get('routing', '')}_")
        lines.append("")
        if basis == "gate_fired":
            da = deciding_axis.get("deciding_axis", {})
            lines.append(f"- **Load-bearing gate:** {da.get('gate')} ({da.get('gate_name')}) "
                         f"— `{da.get('short')}`")
            lines.append(f"- **Framework coverage of that gate:** `{da.get('framework_can_evidence')}`")
        elif basis == "abstention_coverage_gaps":
            lines.append("The framework cannot decide from its own evidence. Gates it could not "
                         "evidence this run (necessity first — these are the routing targets):")
            lines.append("")
            lines.append("| gate | short | band | framework can evidence |")
            lines.append("|---|---|---|---|")
            for g in deciding_axis.get("unevidenced_gates", []):
                lines.append(f"| {g.get('gate')} | `{g.get('short')}` | {g.get('band')} "
                             f"| `{g.get('framework_can_evidence')}` |")
        elif basis == "positive_signal":
            axes = ", ".join(f"`{r.get('short')}`" for r in deciding_axis.get("deciding_axes", []))
            lines.append(f"- **Supporting axes (necessity biology evidenced):** {axes}")
        lines.append("")

    # --- Risk-by-category summary (deterministic, from sub-verdicts) -------
    lines.append("## Risk-by-category summary *(deterministic reshape "
                 "of sub-verdicts)*")
    lines.append("")
    lines.append("Governance-facing 6-category framing mapped from the rule-"
                 "fired sub-verdicts below. Categories with no wired data "
                 "return `insufficient_evidence` rather than fabricated risk "
                 "levels.")
    lines.append("")
    lines.append("| Category | Risk level | Driver |")
    lines.append("|---|---|---|")
    for cat, level, driver in _risk_by_category_from_sub_verdicts(sub_results):
        lines.append(f"| **{cat}** | `{level}` | {driver} |")
    lines.append("")

    # --- Tension analysis (LLM) --------------------------------------------
    tension = llm_output.get("tension_analysis", {}).get("value", "")
    lines.append("## Tension analysis *(LLM-synthesized)*")
    lines.append("")
    lines.append(tension)
    lines.append("")

    # --- Sub-verdicts (rule-fired) -----------------------------------------
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

    # --- Ordinal evidence matrix (deterministic VIEW; gate × modality) -----
    if ordinal_matrix:
        cols = ordinal_matrix["axes"]["columns"]
        leg = ordinal_matrix["legend"]
        lines.append("## Modality-scoped evidence matrix *(deterministic VIEW — not a score)*")
        lines.append("")
        lines.append(f"> {ordinal_matrix.get('_disclaimer', '')}")
        lines.append("")
        lines.append("| gate | " + " | ".join(cols) + " | verdict |")
        lines.append("|" + "---|" * (len(cols) + 2))
        for row in ordinal_matrix["rows"]:
            cells = row["cells"]
            glyphs = " | ".join(ordinal_view._cell_glyph(cells[m]) for m in cols)
            lines.append(f"| {row['short']} | {glyphs} | {row.get('verdict') or '—'} |")
        on = ", ".join(f"{k}={v:+d}" for k, v in sorted(leg["on_scale"].items(), key=lambda t: -t[1]))
        lines.append("")
        lines.append(f"_Scale (order-preserving, NOT metric): {on}; off-scale (coverage, not a "
                     f"low score): {', '.join(leg['off_scale'])} (`insf`/`n/a`); `·` = no signal. "
                     f"A cell shows the strongest raw signal for that (gate, modality); when it "
                     f"differs from the resolved verdict, the verdict is the decision._")
        lines.append("")

    # --- Per-phase evidence tables (Shape A enrichment) --------------------
    lines.append("## Per-phase evidence *(deterministic, from card summaries)*")
    lines.append("")
    lines.append("Key metrics inlined from each sub-skill's underlying card "
                 "summaries. Use these to trace a verdict back to its "
                 "supporting data.")
    lines.append("")
    for short, r in sub_results.items():
        fields = PHASE_METRIC_FIELDS.get(short, [])
        if not fields:
            continue
        v = r["verdict"]
        header = f"### {short}"
        if v:
            header += f" — `{v[0]}`"
        lines.append(header)
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|---|---|")
        any_value = False
        for field, label in fields:
            value = _first_card_summary_field(r, field)
            if value is None:
                continue
            lines.append(f"| {label} | `{_fmt_metric(value)}` |")
            any_value = True
        if not any_value:
            lines.append("| (no metrics available) | — |")
        lines.append("")

    # --- Top arguments (LLM) -----------------------------------------------
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

    # --- Provenance footer -------------------------------------------------
    lines.append("---")
    lines.append("")
    lines.append("*LLM-synthesized sections carry `_source: llm_synthesized` "
                 "provenance (see `nomination.json`). Sub-verdicts + "
                 "per-phase evidence + risk-by-category are deterministic "
                 "and reproducible from the same inputs. The composite "
                 "figure is rendered from the same sub-verdicts and can be "
                 "regenerated identically.*")

    return "\n".join(lines)


__all__ = [
    '_render_target_profile_md',
    '_risk_by_category_from_sub_verdicts',
]
