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




# `_risk_by_category_from_sub_verdicts` REMOVED 2026-09-03 (risk-6dim re-home + renderer unification).
# It was a SECOND, parallel 6-category risk mapping (with md-only LOW-MEDIUM/MEDIUM-HIGH labels) used as
# a fallback whenever the canonical deterministic risk_rollup wasn't produced — the source of the md↔html
# divergence. risk_6dim is now computed UNCONDITIONALLY (tp_grounding.build_risk_6dim over the in-memory
# sub_results, offline-safe), so the md table renders the SAME risk_rollup dims the HTML report +
# risk_rollup.json + target_report.risk_6dim use, via `_risk_rows_from_rollup` below. One source.
# See docs/UNIFIED_OUTPUT_CONTRACT.md.


# Phase-3 EMPHASIS routing: per actionability_mode, which axes LEAD the verbose per-skill sections.
# Reorder-only (nothing is hidden), so the _GATING_AXES (dependency/safety/subtype_fit) never-collapse
# guarantee holds trivially. The mode banner + lead order are DETERMINISTIC (not LLM) and verdict-inert.
_MODE_LEAD_AXES = {
    "cis_feature": ["genomic_alteration", "dependency", "tractability_sm"],
    "abundance": ["surface_modality", "expression", "selectivity", "safety"],
    "mixed": ["genomic_alteration", "surface_modality", "dependency", "expression"],
    "dependency_relational": ["dependency", "combination_vulnerability"],   # trio consolidated 2026-08-20
}
_MODE_BANNER = {
    "cis_feature": "selection basis = a molecular FEATURE (biomarker). Leads with genomic / dependency / "
                   "tractability; a weak surface read is EXPECTED (a cis target need not be over-abundant).",
    "abundance": "selection basis = selective OVER-ABUNDANCE (expression/density cutoff). Leads with "
                 "surface / presence / selectivity / safety; a `non_dependent` read is EXPECTED.",
    "mixed": "BOTH modes fire — the cis handle AND the abundance readout are mutually reinforcing; both "
             "stories are led, neither is demoted.",
    "dependency_relational": "no positive cis handle / not over-abundant — actioned via a PARTNER/CONTEXT; "
                             "leads with dependency + SL / combinatorial (patient-selection = the partner biomarker).",
}


def _deciding_shorts(deciding_axis: Optional[dict]) -> list:
    """The deciding-axis hinge short(s): the gate/positive axis that set the verdict. Handles both the
    single 'deciding_axis' (gate_fired) and 'deciding_axes' (positive_signal) shapes; [] otherwise."""
    if not deciding_axis:
        return []
    if deciding_axis.get("deciding_axis"):
        s = deciding_axis["deciding_axis"].get("short")
        return [s] if s else []
    return [r.get("short") for r in deciding_axis.get("deciding_axes", []) if r.get("short")]


def _mode_ordered_shorts(shorts, actionability_mode: Optional[dict], deciding_axis: Optional[dict] = None):
    """Reorder the sub-result shorts so the DECIDING axis (the verdict hinge) leads, then the mode's LEAD
    axes, then the rest in original order. Pure reorder — nothing dropped/hidden (gating axes always
    render). R12: the deciding axis is prepended so actionability-mode emphasis can never bury the axis
    that actually set the verdict (emphasis and hinge were previously unreconciled)."""
    shorts = list(shorts)
    order = [s for s in _deciding_shorts(deciding_axis) if s in shorts]
    lead = _MODE_LEAD_AXES.get(actionability_mode.get("dominant")) if actionability_mode else None
    if lead:
        order += [s for s in lead if s in shorts and s not in order]
    return order + [s for s in shorts if s not in order]


_PLAYBOOKS_CACHE: Optional[dict] = None


def _load_phenotype_playbooks() -> dict:
    """Load the editable phenotype->eval-playbook map (data, not code) next to this script. Best-effort:
    any failure (missing file / no yaml) returns {} so the panel simply omits the playbook line."""
    global _PLAYBOOKS_CACHE
    if _PLAYBOOKS_CACHE is not None:
        return _PLAYBOOKS_CACHE
    try:
        import yaml
        p = Path(__file__).resolve().parent / "phenotype_playbooks.yaml"
        _PLAYBOOKS_CACHE = yaml.safe_load(p.read_text()) or {} if p.exists() else {}
    except Exception:
        _PLAYBOOKS_CACHE = {}
    return _PLAYBOOKS_CACHE


def _render_phenotype_landscape(companion: Optional[dict],
                                scorecard: Optional[dict] = None) -> list:
    """Render the verdict-INERT target-signature landscape panel (soft phenotype mixture + nearest analogs
    + novelty + D1 readiness). Returns [] when the companion is absent (best-effort facet — never blocks)."""
    if not companion or not isinstance(companion, dict):
        return []
    mix = companion.get("phenotype_mixture") or companion.get("soft_membership") or {}
    if not mix:
        return []
    out = ["## Target-signature landscape *(deterministic VIEW — descriptive, verdict-inert)*", ""]
    # phenotype mixture (components >= 8%), as a compact text bar
    parts = [(k, v) for k, v in mix.items() if v and v >= 0.08]
    if parts:
        bar = " · ".join(f"**{v*100:.0f}%** {k}" for k, v in parts)
        out.append(f"- **Phenotype mixture:** {bar}")
    analogs = companion.get("nearest_analogs") or []
    if analogs:
        astr = ", ".join(f"{a['target']}" + (f"/{a['indication']}" if a.get('indication') else "")
                         + f" ({a.get('distance')})" for a in analogs[:5])
        out.append(f"- **Nearest reference analogs:** {astr}")
    nov = companion.get("novelty") or {}
    if nov:
        flags = []
        if nov.get("inconsistent_flag"):
            flags.append("**inconsistent** with any canonical phenotype")
        if nov.get("local_density_flag"):
            flags.append("local outlier")
        tag = "; ".join(flags) if flags else "consistent with known phenotypes"
        hr = nov.get("hull_residual")
        out.append(f"- **Novelty:** {tag}" + (f" (hull-residual {hr})" if hr is not None else ""))
    miss = companion.get("missingness") or {}
    if miss:
        um = miss.get("unmeasured_axes") or []
        cov = f"{miss.get('n_features_measured')}/{miss.get('n_features_total')} features measured"
        out.append(f"- **Coverage:** {cov}"
                   + (f"; unmeasured axes: {', '.join(um[:6])}" + ("…" if len(um) > 6 else "") if um else ""))
    if scorecard and isinstance(scorecard, dict) and scorecard.get("score") is not None:
        cf = scorecard.get("counterfactual_gap") or {}
        lim = cf.get("limiting_axis")
        out.append(f"- **Readiness (D1, phenotype-conditioned):** {scorecard['score']}"
                   + (f" — route-limiting axis: `{lim}`" if lim else ""))
    prec = companion.get("rule_precedent") or []
    if prec:
        pstr = ", ".join(f"{p['target']} (J={p.get('jaccard')})" for p in prec[:4])
        out.append(f"- **Rule-fingerprint precedent:** {pstr}")
    # dominant-phenotype eval PLAYBOOK (descriptive orientation content; read-only, never a gate)
    dom = max(mix, key=mix.get) if mix else None
    pb = (_load_phenotype_playbooks() or {}).get(dom) if dom else None
    if isinstance(pb, dict) and (pb.get("modality") or pb.get("comparators")):
        out.append(f"- **Playbook ({dom}):** {pb.get('modality', '')}".rstrip())
        comps = pb.get("comparators") or []
        if comps:
            out.append(f"  - _comparators:_ {', '.join(str(c) for c in comps)}")
        if pb.get("acquire"):
            out.append(f"  - _evidence to acquire:_ {pb['acquire']}")
    out += ["", "_Descriptive orientation from the frozen target-signature atlas — a soft mixture over "
            "curated canonical phenotype anchors, not a classification or a gate. Playbook is illustrative "
            "eval guidance, not a recommendation._", ""]
    return out


# risk_rollup bin vocab (LOW/MED/HIGH/ENGINE-BLIND) → the md table's level vocab.
_ROLLUP_BIN_TO_MD_LEVEL = {"LOW": "LOW", "MED": "MEDIUM", "HIGH": "HIGH",
                           "ENGINE-BLIND": "insufficient_evidence"}
# fixed 6-dim order for the md risk table (matches the historical _risk_by_category ordering).
_RISK_DIM_ORDER = ("biological", "druggability", "translational", "clinical", "safety", "commercial")


def _risk_rows_from_rollup(risk_rollup: Optional[dict]) -> Optional[list[tuple[str, str, str]]]:
    """Adapt the CANONICAL deterministic risk_rollup (dims) into the md (category, level, driver) rows,
    so the md table renders the SAME 6-dim risk the HTML report + risk_rollup.json already show — instead
    of the md's own parallel `_risk_by_category_from_sub_verdicts` mapping (which could diverge). Returns
    None when the rollup is absent/misshaped → the renderer falls back to the local mapping (e.g. a
    --no-substrate run where risk_rollup was never produced)."""
    dims = risk_rollup.get("dims") if isinstance(risk_rollup, dict) and "dims" in risk_rollup else risk_rollup
    if not isinstance(dims, dict):
        return None
    rows: list[tuple[str, str, str]] = []
    for dim in _RISK_DIM_ORDER:
        d = dims.get(dim)
        if not isinstance(d, dict) or "bin" not in d:
            continue
        level = _ROLLUP_BIN_TO_MD_LEVEL.get(d.get("bin"), d.get("bin") or "insufficient_evidence")
        chain = d.get("chain") or []
        driver = (f"{chain[0][0]}: {chain[0][1]}" if chain and len(chain[0]) >= 2
                  else (d.get("pillar") or ""))
        rows.append((dim, level, driver))
    return rows or None


def _render_target_profile_md(
    target: str,
    indication: str,
    sub_results: dict,
    llm_output: dict,
    invoked_lenses: dict,
    composite_figure_relpath: Optional[str] = None,
    deciding_axis: Optional[dict] = None,
    ordinal_matrix: Optional[dict] = None,
    presence_facet: Optional[dict] = None,
    actionability_mode: Optional[dict] = None,
    archetype_companion: Optional[dict] = None,
    nomination_scorecard: Optional[dict] = None,
    risk_rollup: Optional[dict] = None,
    recommendation_gate: Optional[dict] = None,
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
    # Phase-3 actionability-mode banner (deterministic, verdict-inert emphasis routing). Present only
    # for a resolved mode; insufficient/absent → no banner (unchanged from pre-Phase-3).
    if actionability_mode and actionability_mode.get("dominant") in _MODE_BANNER:
        _m = actionability_mode
        # R13: surface override provenance (source + the run's derived call) so a reader can see when the
        # dominant mode is CURATED vs derived from this run's evidence — "mixed [curated; derived = ...]".
        _prov = ""
        if _m.get("source") == "curated_override":
            _prov = f"; source: curated, derived this run = `{_m.get('derived_dominant')}`"
        lines += [
            "",
            f"**Actionability mode: `{_m['dominant']}`** (confidence: {_m.get('confidence')}{_prov}) — "
            f"{_MODE_BANNER[_m['dominant']]}",
            "_Emphasis only: the per-skill sections below lead with the mode-relevant axes. The verdict "
            "spine and all gating axes (dependency / safety) are unchanged and shown in full._",
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
    # The Action shown is the RECOMMENDATION OF RECORD: run.main clamps overall_recommendation.value to
    # the deterministic recommendation-gate action, so `rec` is authoritative, not the LLM's raw pick. The
    # LLM synthesis is ADVISORY (it narrates; it does not set the call) — label it so, and when the gate
    # OVERRODE the LLM, surface that disagreement rather than hide it (contract rules 1-2).
    _rg = recommendation_gate or {}
    lines.append("## Recommendation *(deterministic gate — LLM synthesis is advisory)*")
    lines.append("")
    lines.append(f"- **Action:** `{rec}`")
    lines.append(f"- **Confidence:** `{conf}`")
    lines.append("_The action is the deterministic recommendation gate's — the recommendation of record. "
                 "The LLM synthesis below is **advisory (does not set the call)**._")
    if _rg.get("overridden"):
        lines.append(f"- **⚠ LLM↔gate disagreement:** the LLM advised "
                     f"`{_rg.get('llm_recommendation')}`, but the deterministic gate forced "
                     f"`{_rg.get('forced_recommendation')}` (the auditable rule wins).")
    lines.append("")

    # --- Target-signature landscape (deterministic, DESCRIPTIVE, verdict-inert) --------------------
    # Orientation panel from the target-archetype companion: the soft phenotype MIXTURE (convex membership
    # to canonical anchors), nearest reference analogs, a novelty flag, and the interpretable D1
    # readiness score. A "you are here" read — never a gate, never a classification claim.
    lines += _render_phenotype_landscape(archetype_companion, nomination_scorecard)

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

    # --- Risk-by-category summary (deterministic risk_6dim projection) -----
    lines.append("## Risk-by-category summary *(deterministic risk_6dim "
                 "projection)*")
    lines.append("")
    lines.append("Governance-facing 6-category framing — the canonical "
                 "deterministic `risk_6dim` roll-up (the same `target_report."
                 "risk_6dim` / `risk_rollup.json` the HTML report renders). "
                 "Categories with no wired engine leg show "
                 "`insufficient_evidence` rather than fabricated risk levels.")
    lines.append("")
    lines.append("| Category | Risk level | Driver |")
    lines.append("|---|---|---|")
    # ONE source: the canonical deterministic risk_rollup (target_report.risk_6dim), computed
    # unconditionally upstream (tp_grounding.build_risk_6dim) and rendered here + in the HTML report +
    # risk_rollup.json — no parallel md-local mapping to diverge. `_risk_rows_from_rollup` returns None
    # only if the rollup genuinely failed to compute (best-effort None); render an honest note then.
    _risk_rows = _risk_rows_from_rollup(risk_rollup)
    if _risk_rows:
        for cat, level, driver in _risk_rows:
            lines.append(f"| **{cat}** | `{level}` | {driver} |")
    else:
        lines.append("| _(risk_6dim unavailable this run)_ | `insufficient_evidence` | "
                     "deterministic risk roll-up not computed |")
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

    # --- Presence × context (deterministic VIEW from tumor-presence) -------
    # The per-(measurement, sample_context) reconciliation BEHIND the collapsed presence verdict —
    # surfaced so a reader sees cross-modal tension (RNA-high/protein-absent; tumor-high/normal-high)
    # the one-word verdict hides. DISPLAY-ONLY (the normal column is a safety COMPARATOR; the safety
    # verdict is owned by on-target-safety-liability). md gets the table; the html report gets the SVG.
    pvm = (presence_facet or {}).get("presence_verdict_by_modality") or {}
    if pvm:
        lines.append("## Presence × context *(deterministic VIEW — not a score)*")
        lines.append("")
        lines.append("| Measurement / context | Sub-verdict | Evidence |")
        lines.append("|---|---|---|")
        for key, b in pvm.items():
            if not isinstance(b, dict):
                continue
            lines.append(f"| {key} | `{b.get('verdict')}` | {b.get('evidence_state')} |")
        lines.append("")
        if presence_facet.get("cell_line_vs_tumor_discordant"):
            lines.append(f"> ⚠ {presence_facet.get('presence_interpretation_note')}")
            lines.append("")
        _pq = presence_facet.get("bulk_rna_proxy_quality")
        if _pq:
            lines.append(f"RNA→protein proxy quality: `{_pq}` "
                         f"(source: {presence_facet.get('bulk_rna_proxy_quality_source')}). "
                         f"Normal-tissue comparator (window framing — safety verdict owned by "
                         f"on-target-safety-liability): HPA-IHC "
                         f"`{presence_facet.get('normal_tissue_ihc_breadth_class')}`, scRNA-normal "
                         f"`{presence_facet.get('sc_normal_expression_class')}`.")
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
    for short in _mode_ordered_shorts(sub_results.keys(), actionability_mode, deciding_axis):
        r = sub_results[short]
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
    '_risk_rows_from_rollup',
]
