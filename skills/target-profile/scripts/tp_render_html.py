"""target-profile — self-contained HTML report renderer (CSS/JS bootstrap, gate sections,
per-card panels, risk-category rollup)."""
from __future__ import annotations

import argparse
import concurrent.futures
import html as _html
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

from _skills_common import resolve_cards, ordinal_view
from tp_common import PHASE_METRIC_FIELDS, SKILL_NAME, SKILL_VERSION, _CONTRACTS_REPO, _first_card_summary_field, _fmt_metric, _framework_model_version
from tp_gates import _load_gate_coverage




# --- Risk-category roll-up (5R dashboard spine, 2026-07-21) ------------------
#
# The committee-facing lead lens: roll the per-gate scorecard rows up into drug-discovery risk
# categories (5R-anchored — see target-contracts docs/design/RISK_CATEGORY_DASHBOARD_SPINE.md).
# DATA-DRIVEN SURFACING: a category is surfaced IFF >=1 of its member sub-skills produced evidence
# this run (a non-coverage-gap status). Categories with no evidenced member are NOT rendered as
# rows — they collapse into a one-line "not yet evidenced" footnote. This keeps the dashboard
# honest (absence = "we don't evidence this yet") AND self-extending (wire a new sub-skill → its
# category appears automatically). Category risk LEVEL is a computed roll-up of member statuses,
# reusing the SAME 4-state the scorecard already assigned — no new classification logic.
_RISK_CATEGORY_ORDER = ["biological", "biomarker", "druggability", "safety",
                        "translational", "clinical", "commercial"]
_RISK_CATEGORY_LABEL = {
    "biological":    ("Biological", "Right Target — is this real, actionable biology?"),
    "biomarker":     ("Biomarker", "Right Patient — who responds?"),
    "druggability":  ("Druggability", "can it be drugged (small-molecule / biologic)?"),
    "safety":        ("Safety", "Right Safety — on-target liability?"),
    "translational": ("Translational", "Right Tissue — models / PD / exposure?"),
    "clinical":      ("Clinical", "clinical precedent?"),
    "commercial":    ("Commercial", "Right Commercial Potential — differentiation?"),
}


def _risk_category_rollup(scorecard: list[dict]) -> dict:
    """Group scorecard rows by risk_category → the 5R lead lens. Returns
    {surfaced: [{category, label, sub, risk_level, driver, members:[rows], anchor}],
     not_evidenced: [category,...]}. A category surfaces iff >=1 member has an on-scale status
     (supportive/opposing/neutral — i.e. we looked); all-coverage-gap categories are 'not evidenced'.
    risk_level: opposing member → 'elevated'; else any supportive → 'supported'; else 'neutral'."""
    by_cat: dict = {}
    for row in scorecard or []:
        cat = row.get("risk_category") or "other"
        by_cat.setdefault(cat, []).append(row)

    def _level(members: list[dict]) -> tuple[str, str]:
        statuses = [m.get("status") for m in members]
        opp = [m for m in members if m.get("status") == "opposing"]
        sup = [m for m in members if m.get("status") == "supportive"]
        if opp:
            drv = opp[0]
            return "elevated", f"{_humanize(drv.get('verdict') or drv.get('short'))} (opposing)"
        if sup:
            drv = sup[0]
            return "supported", f"{_humanize(drv.get('verdict') or drv.get('short'))}"
        return "neutral", "measured; no strong signal either way"

    surfaced, not_evidenced = [], []
    for cat in _RISK_CATEGORY_ORDER + sorted(k for k in by_cat if k not in _RISK_CATEGORY_ORDER):
        members = by_cat.get(cat)
        if not members:
            not_evidenced.append(cat)
            continue
        # evidenced iff >=1 member has an on-scale (non-coverage-gap) status
        if not any(m.get("status") in ("supportive", "opposing", "neutral") for m in members):
            not_evidenced.append(cat)
            continue
        level, driver = _level(members)
        label, sub = _RISK_CATEGORY_LABEL.get(cat, (_humanize(cat), ""))
        # anchor: link to the first evidenced member's gate section (roll-up → detail)
        anchor = None
        for m in members:
            a = _SHORT_TO_GATE_ANCHOR.get(m.get("short"))
            if a:
                anchor = a
                break
        surfaced.append({"category": cat, "label": label, "sub": sub, "risk_level": level,
                         "driver": driver, "members": members, "anchor": anchor})
    return {"surfaced": surfaced, "not_evidenced": not_evidenced}

_HTML_STATUS = {   # 4-state scorecard chip → (glyph, css class, human label)
    "supportive":   ("●", "chip-pos",  "Supports"),
    "neutral":      ("○", "chip-neu",  "Measured — neutral"),
    "opposing":     ("◆", "chip-neg",  "Counts against"),
    "coverage_gap": ("□", "chip-gap",  "Not evaluated"),
}

# --- Plain-English label layer (reader-facing; raw tokens stay in nomination.json) -----------
# The internal vocabulary (verdict strings, gate shorts, coverage terms) leaks jargon to a human
# reader. These maps turn it into plain English for the HTML report. Curated overrides for the
# load-bearing terms; a snake_case→Title-Case fallback for the rest so nothing renders as a raw id.
_GATE_SHORT_LABEL = {
    "expression": "Expression (is it expressed?)",
    "selectivity": "Tumor selectivity (vs normal)",
    "dependency": "Functional dependence (is it required?)",
    "synthetic_lethal_partners": "Synthetic-lethal partners",
    "mechanism": "Mechanism / mode of action",
    "genomic_alteration": "Genomic alteration",
    "differentiation": "Differentiation (co-mutation)",
    "combinatorial_dependency": "Combinatorial dependency (dual-KO)",
    "tractability_sm": "Small-molecule druggability",
    "surface_modality": "Surface / biologics fit",
    "safety": "On-target safety",
    "target_intrinsic": "Target-intrinsic dossier",
    "subtype_fit": "Subtype-specific fit",
}
# Flat subskill roster (fan-out order) → one dashboard section each. Replaces the old gate-band
# grouping: the body lists the SUBSKILLS, not A–E "gates". Kept in step with tp_fanout.SUB_SKILLS.
_SUBSKILL_ORDER = [
    "expression", "selectivity", "dependency", "synthetic_lethal_partners",
    "combinatorial_dependency", "mechanism", "genomic_alteration", "differentiation",
    "tractability_sm", "surface_modality", "safety", "target_intrinsic",
]
# Subskill axes for which the grounded literature reader (literature-risk-assessment/ground_axis)
# is configured today — kept in step with ground_axis.AXIS_CONFIG's verdict_key set (#491/#493:
# safety, dependency, selectivity, surface_modality, tractability_sm). A subskill NOT in this set
# renders an honest "not yet grounded" note; one IN it but without a record this run renders nothing.
_GROUNDABLE_AXES = {"safety", "dependency", "selectivity", "surface_modality", "tractability_sm"}


def _subskill_anchor(short: str) -> str:
    """Section anchor for a subskill (flat layout). NOT gate-lettered."""
    return "s-skill-" + re.sub(r"[^a-z0-9]+", "-", short.lower()).strip("-")
_COVERAGE_LABEL = {
    "captured": "Well covered",
    "partial": "Partially covered",
    "blind": "Not covered (framework blind)",
    "license_blocked": "License-blocked data",
    "out_of_scope": "Out of scope (Tier-2)",
}
# Plain-English band labels (reader-facing) — the "necessity/sufficiency" jargon is dropped in
# favor of the question each band actually asks.
_BAND_LABEL = {"necessity": "Is it real biology?",
               "sufficiency": "Will it become a drug?"}
# Nomination action → (display term, plain-English gloss). Shown as "Term — gloss" in the header.
_ACTION_GLOSS = {
    "nominate": ("Nominate", "advance this target"),
    "hold": ("Hold", "do not advance yet — a concern must be resolved first"),
    "veto": ("Veto", "do not pursue — a disqualifying finding"),
    "insufficient_evidence": ("Insufficient evidence", "the framework cannot make a call"),
}
# Load-bearing verdict humanizations (the ones a reader most needs unambiguous).
_VERDICT_LABEL = {
    "lineage_selective": "Selective dependency (lineage-restricted)",
    "concordant_dependent": "Strong dependency (CRISPR + RNAi agree)",
    "selective_dependent": "Selective dependency",
    "chemical_genetic_confirmed_dependent": "Dependency confirmed (chemical + genetic)",
    "non_dependent": "Not a dependency (pooled)",
    "pan_essential_killer": "Pan-essential (no therapeutic window)",
    "broadly_dependent": "Broadly dependent",
    "strong_tumor_selective": "Strongly tumor-selective",
    "modest_tumor_selective": "Modestly tumor-selective",
    "not_selective": "Not tumor-selective",
    "discordant_across_comparators": "Discordant across comparators",
    "highly_constrained_safety_concern": "High on-target safety concern",
    "biomarker_stratified_dependency": "Biomarker-stratified dependency",
    "confirmed_driver": "Confirmed driver (annotation-corroborated)",
    "well_covered": "Well-covered by compounds",
    "well_characterized": "Well-characterized mechanism",
    "both_patterns_present": "Co-mutation + mutual-exclusivity present",
    "broadly_moderate_expression": "Broadly moderate expression",
    "has_experimental_sl_partner": "Has an experimental SL partner",
    "insufficient": "Insufficient evidence",
    "data_unavailable": "Data unavailable",
    None: "Not evaluated",
}


def _humanize(token: Optional[str]) -> str:
    """snake_case / lowercase identifier → readable Title Case, with curated overrides."""
    if token is None:
        return "Not evaluated"
    if token in _VERDICT_LABEL:
        return _VERDICT_LABEL[token]
    return str(token).replace("_", " ").replace("-", " ").strip().capitalize()

# CSS design system (dataviz-skill method; Takeda Okabe-Ito palette as the brand parameters).
# Color roles as CSS custom properties. Status chips use VALIDATED constructions — dark status-ink
# on a pale same-hue tint + a glyph + a label (never color-alone) — WCAG 4.8-6.3:1 (computed with
# the dataviz validator, NOT eyeballed; the validator caught that saturated status colors on white
# fail contrast, so chips are tinted backgrounds). The ordinal heatmap uses a DIVERGING blue↔red
# ramp (a magnitude), deliberately distinct from the status chips so the two color languages don't
# collide (dataviz rule: status colors are reserved, never reused as a scale).
_HTML_CSS = """
:root{
  --surface:#ffffff; --surface-2:#f7f9fb; --surface-3:#eef2f6;
  --ink:#141c26; --ink-2:#4a5763; --muted:#6b7783; --line:#e2e8ee; --line-2:#cfd8e0;
  --brand:#0a2540; --brand-accent:#0072B2;                 /* Takeda deep navy + Okabe-Ito blue */
  --pos-ink:#1a6b1a; --pos-bg:#e6f4e6;                      /* status: good */
  --neg-ink:#a1231d; --neg-bg:#fbe6e4;                      /* status: critical */
  --neu-ink:#8a5a00; --neu-bg:#fcf1db;                      /* status: warning */
  --gap-ink:#5b6b7b; --gap-bg:#eef1f4;                      /* coverage gap (hatched) */
  --llm-bg:#f5f2fb; --llm-bd:#d9ccf0; --llm-ink:#5b3fa0;    /* AI-generated section tint */
  --div-p2:#2166ac; --div-p0:#e9eef3; --div-n1:#f4a582; --div-n3:#b2182b;  /* diverging blue↔red */
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth}
body{font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
  color:var(--ink);background:var(--surface-3);margin:0;padding:0}
/* Header band — full-bleed; inner content aligned to the same max-width as the shell */
header{background:linear-gradient(100deg,var(--brand),#123a5e);color:#fff;
  padding:24px 40px;border-bottom:3px solid var(--brand-accent)}
header>*{max-width:1560px;margin-left:auto;margin-right:auto}
header h1{font-size:25px;font-weight:650;margin:0;letter-spacing:-.01em;line-height:1.25}
header .rec{font-size:14px;margin-top:10px;opacity:.95;display:flex;flex-wrap:wrap;align-items:center;gap:8px}
header .pill{display:inline-block;background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.32);
  border-radius:999px;padding:2px 12px;font-weight:650}
.badge-rule{display:inline-block;background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.3);
  border-radius:6px;padding:2px 9px;font-size:12px;font-weight:600;cursor:help}
/* 2-column shell: sticky left nav + content. Wide — uses the full viewport up to a large cap. */
.shell{display:flex;gap:28px;max-width:1680px;margin:0 auto;padding:26px 40px 64px;align-items:flex-start}
nav.toc{position:sticky;top:20px;flex:0 0 150px;font-size:12.5px;line-height:1.3}   /* narrower (item 7) */
nav.toc .h{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);
  font-weight:700;margin:0 0 8px}
nav.toc a{display:block;padding:6px 10px;border-radius:7px;color:var(--ink-2);text-decoration:none;
  border-left:2px solid transparent}
nav.toc a:hover{background:var(--surface);color:var(--brand);border-left-color:var(--brand-accent)}
.content{flex:1 1 auto;min-width:0}
.sub{color:var(--muted);font-size:13px;margin:0 0 10px}
/* Responsive inline SVG — strip matplotlib's fixed pt size, scale to the card (viewBox holds ratio) */
section svg{width:100%!important;height:auto!important;display:block}
/* Section cards */
section{background:var(--surface);border:1px solid var(--line);border-radius:12px;
  padding:18px 20px;margin:0 0 18px;box-shadow:0 1px 2px rgba(20,28,38,.04)}
h2{font-size:16px;font-weight:650;margin:0 0 12px;color:var(--brand);letter-spacing:-.005em}
h2 .n{color:var(--muted);font-weight:500;font-size:13px}
/* Tables */
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{padding:8px 11px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}
th{background:var(--surface-2);font-weight:600;color:var(--ink-2);font-size:12px;
  text-transform:uppercase;letter-spacing:.03em;border-bottom:1.5px solid var(--line-2)}
tr:last-child td{border-bottom:0}
code{font:12.5px/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  background:var(--surface-3);padding:1px 5px;border-radius:4px;color:var(--ink-2)}
/* LLM vs deterministic provenance tags */
.llm{background:var(--llm-bg);border:1px solid var(--llm-bd);border-radius:12px;padding:16px 20px;margin:0 0 18px}
.llm h2{color:var(--llm-ink)}
.tag{display:inline-block;font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;font-weight:700;
  padding:2px 8px;border-radius:5px;margin-bottom:8px}
.llm .tag{color:var(--llm-ink);background:rgba(91,63,160,.1)}
.det .tag{color:var(--muted);background:var(--surface-3)}
/* AI-generated provenance chip in the exec summary's upper-right corner. The h2 purple bar hugs the
   box top (first-child), so the chip floats on that bar → give it translucent-white-on-purple so it
   reads against the dark band rather than the light in-flow tag treatment. */
.llm-exec{position:relative}
.llm-exec .tag-corner{position:absolute;top:9px;right:14px;margin:0;z-index:2;
  color:#fff;background:rgba(255,255,255,.18)}
/* Status chips — validated: tinted bg + dark ink + glyph + label */
.chip{display:inline-flex;align-items:center;gap:5px;padding:3px 10px;border-radius:999px;
  font-size:12px;font-weight:650;white-space:nowrap;line-height:1.3}
.chip .g{font-size:11px}
.chip-pos{background:var(--pos-bg);color:var(--pos-ink)}
.chip-neu{background:var(--neu-bg);color:var(--neu-ink)}
.chip-neg{background:var(--neg-bg);color:var(--neg-ink)}
.chip-gap{background:var(--gap-bg);color:var(--gap-ink);
  background-image:repeating-linear-gradient(45deg,transparent,transparent 5px,rgba(91,107,123,.13) 5px,rgba(91,107,123,.13) 6px)}
/* Scorecard hero */
.scorecard th:first-child,.scorecard td:first-child{text-align:center;font-weight:700;color:var(--brand);width:38px}
.scorecard tr.gate-start td{border-top:2px solid var(--line-2)}
.scorecard tr.deciding{background:#fff9ec}
.scorecard tr.deciding td:first-child{box-shadow:inset 3px 0 0 var(--neu-ink)}
.badge-deciding{display:inline-block;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;
  color:var(--neu-ink);background:var(--neu-bg);padding:1px 6px;border-radius:4px;margin-left:6px}
/* Deciding-axis banner */
.banner{background:linear-gradient(90deg,#eef4f8,var(--surface));border-left:4px solid var(--brand-accent);
  padding:12px 16px;border-radius:8px;margin:0 0 12px;font-size:14px}
/* Ordinal matrix heatmap */
.mtx{font-size:12.5px}
.mtx td{text-align:center;font-variant-numeric:tabular-nums;font-weight:600;border:2px solid var(--surface)}
.mtx td:first-child,.mtx td:last-child{text-align:left;font-weight:400;background:var(--surface)!important}
.mtx th{text-align:center}
.mtx .p2{background:var(--div-p2);color:#fff}.mtx .p0{background:var(--div-p0);color:var(--ink-2)}
.mtx .n1{background:var(--div-n1);color:#3a1207}.mtx .n3{background:var(--div-n3);color:#fff}
.mtx .off{background:var(--gap-bg);color:var(--gap-ink);font-style:italic}
.disclaimer{font-size:12px;color:var(--muted);font-style:italic;margin:6px 0}
details{margin-top:10px;border-top:1px solid var(--line);padding-top:10px}
summary{cursor:pointer;font-weight:600;color:var(--ink-2);font-size:13px}
footer{color:var(--muted);font-size:12px;text-align:center;padding-top:8px}
/* Interactive figures (Phase B). Tighter default height (item 1) — the method sets each figure's
   own height; this caps the container so charts don't dominate. */
.plotly-fig{width:100%;min-height:250px;margin:6px 0 2px}
/* Gate section + subtabs (iterative dashboard, 2026-07-21). A gate section is a normal section
   card; inside it a radio-driven tab strip (Plots / Evidence / Rules) — pure CSS, no framework, so
   the report stays a self-contained archivable file. Each gate's radios share a name scoped by the
   gate short (name=tab-<short>) so gates toggle independently. */
.gate .gate-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 4px}
.gate .gate-letter{display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;
  border-radius:7px;background:var(--brand);color:#fff;font-weight:700;font-size:13px;flex:0 0 auto}
.gate .gate-verdict{margin-left:auto;font-size:13px;color:var(--ink-2)}
/* Axis band header (gate-model v2): the two-axis split — Biology (necessity) vs Modality-fit
   (sufficiency) — rendered as a band that groups the gate sections beneath it. */
.axis-band{margin:26px 0 10px;padding:8px 14px;border-radius:9px;background:var(--surface-2);
  border-left:4px solid var(--brand)}
.axis-band h2{margin:0;font-size:15px;background:none;color:var(--brand);padding:0;letter-spacing:.2px}
.axis-band .n{color:var(--muted);font-weight:400;font-size:13px}
/* Tabbed card subsections. A tiny JS handler (in the page bootstrap) toggles .active on the
   clicked label + its target panel — robust across any tab count, and JS is already present for the
   Plotly resize-on-show. The button strip is a <div role=tablist> of <button> tabs; panels carry
   .panel and are hidden unless .active. Degrades gracefully: with JS off, ALL panels show stacked
   (no data hidden) since :not(.active) only hides when the script has run (html.tabs-js). */
.tabs{margin-top:8px}
.tabs .tablist{display:flex;flex-wrap:wrap;gap:3px;border-bottom:1px solid var(--line)}
.tabs .tab{padding:7px 13px;font-size:13px;font-weight:600;color:var(--ink-2);cursor:pointer;
  border:1px solid var(--line);border-bottom:none;border-radius:8px 8px 0 0;background:var(--surface-2);
  margin-bottom:-1px}
.tabs .tab:hover{color:var(--brand)}
.tabs .tab.active{background:var(--surface);color:var(--brand);box-shadow:0 -2px 0 var(--brand-accent) inset}
.tabs .tab.gap{color:var(--muted);opacity:.72}
.tabs .panel{border:1px solid var(--line);border-radius:0 8px 8px 8px;padding:16px 18px;
  background:var(--surface)}
html.tabs-js .tabs .panel{display:none}
html.tabs-js .tabs .panel.active{display:block}
/* Panel body: plots (left ~78%) + summary rail (right ~22%) — item 3. Stacks on narrow screens. */
.card-body{display:grid;grid-template-columns:minmax(0,3.5fr) minmax(200px,1fr);gap:20px;align-items:start}
@media(max-width:900px){.card-body{grid-template-columns:1fr}}
.card-plots{min-width:0}
.card-rail{font-size:12.5px;border-left:1px solid var(--line);padding-left:16px}
.card-rail .rail-h{font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);
  font-weight:700;margin:0 0 6px}
.card-rail .rail-sec{margin:0 0 14px}
.card-rail .interp{background:var(--surface-2);border-radius:7px;padding:9px 11px;font-size:12.5px;
  line-height:1.5;color:var(--ink-2)}
.card-rail .kf{margin:0 0 7px}.card-rail .kf b{color:var(--brand);font-variant-numeric:tabular-nums;font-size:14px}
.card-rail .kf span{color:var(--muted);display:block;font-size:10.5px;text-transform:uppercase;letter-spacing:.03em}
.panel .empty-note{color:var(--muted);font-size:13px;margin:4px 0}
/* Per-card panel: verdict strip + key-facts + plot */
.card-verdict{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 12px;
  padding:9px 12px;background:var(--surface-2);border-radius:8px;font-size:13.5px}
.card-verdict .drv{color:var(--muted);font-size:12px}
.card-verdict .drv code{font-size:11.5px}
.keyfacts{display:flex;flex-wrap:wrap;gap:8px 22px;margin:0 0 12px}
.keyfacts .kf{font-size:13px}.keyfacts .kf b{color:var(--brand);font-variant-numeric:tabular-nums}
.keyfacts .kf span{color:var(--muted);display:block;font-size:11px;text-transform:uppercase;letter-spacing:.03em}
.card-src{font-size:11.5px;color:var(--muted);margin-top:10px}
.rules-tbl td code{font-size:11.5px}
.sig-pos{color:var(--pos-ink);font-weight:600}.sig-neg{color:var(--neg-ink);font-weight:600}
.sig-neu{color:var(--neu-ink)}.sig-kill{color:var(--neg-ink);font-weight:700}
/* GI-style components (Phase B PR-3) — About band + data-loaded status banner + navy section bars */
/* Provenance trace — per-sub-skill run record (collapsible, at the bottom). */
.trace-skill{margin:8px 0 12px;padding:8px 0 0;border-top:1px solid var(--line)}
.trace-h{margin:0 0 5px;font-size:13px}
table.trace-cards{width:100%;font-size:12px;border-collapse:collapse;margin:2px 0 4px}
table.trace-cards th{text-align:left;color:var(--muted);font-weight:600;padding:2px 8px}
table.trace-cards td{padding:2px 8px;border-top:1px solid var(--line-2);vertical-align:top}
tr.trace-missing{opacity:.55}
.about{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 20px;margin:0 0 18px}
.about .h{font-weight:700;color:var(--ink-2);font-size:13px;margin:0 0 8px;display:flex;align-items:center;gap:7px}
.about .h::before{content:"\\24D8";color:var(--brand-accent);font-size:15px}   /* circled i */
.about ul{margin:0;padding-left:20px;font-size:13.5px;color:var(--ink-2)}
.about li{margin:2px 0}
.about .citation{border-top:1px solid var(--line);margin-top:10px;padding-top:9px;
  font-size:12px;color:var(--muted);line-height:1.5}
.about .citation code{font-size:11.5px}
.statusbar{background:var(--pos-bg);border:1px solid #bfe3bf;border-left:4px solid var(--pos-ink);
  border-radius:8px;padding:9px 15px;margin:0 0 18px;font-size:13.5px;color:#144d14;font-weight:600;
  display:flex;align-items:center;gap:8px}
.statusbar::before{content:"\\2713";color:var(--pos-ink);font-weight:800}  /* check */
.statusbar .n{font-weight:400;color:#2c6b2c}
/* Section title bar — GI dark-navy band. Full-bleed left/right (no top-bleed: the small provenance
   tag chip sits above it as a kicker). One h2 per section, so a descendant selector is safe. */
section>h2,.llm>h2{background:var(--brand);color:#fff;margin:8px -20px 14px;
  padding:11px 20px;font-size:14.5px;letter-spacing:.005em}
section>h2 .n,.llm>h2 .n{color:rgba(255,255,255,.72)}
.llm>h2{background:var(--llm-ink)}                               /* AI sections: purple bar, not navy */
section>h2:first-child,.llm>h2:first-child{margin-top:-18px;border-radius:12px 12px 0 0}  /* no tag → hug top */
"""


# Vanilla-JS bootstrap: draw every embedded Plotly spec. No framework, DISPLAY-only (Plotly's own
# hover/zoom) — it re-derives NO evidence (honesty spine: light JS renders, never recomputes). Each
# spec rides in a <script type=application/json class=plotly-spec data-target=...> block next to its
# div; we parse + Plotly.newPlot into the target. Responsive; guarded so one bad spec can't blank the
# page.
_PLOTLY_BOOTSTRAP_JS = """<script>
(function(){
  function draw(){
    if(typeof Plotly==='undefined'){return setTimeout(draw,60);}   // wait for the inlined bundle
    var specs=document.querySelectorAll('script.plotly-spec');
    for(var i=0;i<specs.length;i++){
      try{
        var el=specs[i], tgt=document.getElementById(el.getAttribute('data-target'));
        if(!tgt||tgt.getAttribute('data-drawn'))continue;
        var fig=JSON.parse(el.textContent);
        (fig.layout=fig.layout||{}).autosize=true;
        Plotly.newPlot(tgt,fig.data,fig.layout,{responsive:true,displaylogo:false,
          modeBarButtonsToRemove:['lasso2d','select2d']});
        tgt.setAttribute('data-drawn','1');
      }catch(e){if(window.console)console.warn('plotly spec draw failed',e);}
    }
  }
  // A chart drawn inside a display:none tab panel has zero size → renders blank until resized.
  // On any tab radio toggle, resize every already-drawn plot in the newly-shown panel(s). Also
  // resize on window resize. This is what makes non-default subtabs (and their plots) render.
  function resizeVisible(){
    if(typeof Plotly==='undefined')return;
    document.querySelectorAll('.plotly-fig[data-drawn]').forEach(function(d){
      if(d.offsetParent!==null){try{Plotly.Plots.resize(d);}catch(e){}}   // offsetParent null = hidden
    });
  }
  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',function(){draw();resizeVisible();});
  }else{draw();resizeVisible();}
  window.addEventListener('resize',resizeVisible);
  // Expose so the tab bootstrap can resize the plots in a panel it just revealed.
  window.__resizePlots=resizeVisible;
})();
</script>"""

# Tab bootstrap — ALWAYS emitted when gate sections are present (independent of Plotly). Adds
# html.tabs-js (which flips the panel CSS from "all shown, stacked" to "only .active shown"), then
# on a tab click toggles .active on the clicked button + its target panel within the same .tabs
# group, and asks the Plotly layer (if present) to resize the now-visible charts. No framework.
_TAB_BOOTSTRAP_JS = """<script>
(function(){
  document.documentElement.classList.add('tabs-js');
  document.addEventListener('click',function(e){
    var btn=e.target.closest?e.target.closest('.tabs .tab'):null;
    if(!btn)return;
    var group=btn.closest('.tabs');
    var pid=btn.getAttribute('data-panel');
    group.querySelectorAll(':scope > .tablist > .tab').forEach(function(t){t.classList.remove('active');});
    group.querySelectorAll(':scope > .panel').forEach(function(p){p.classList.remove('active');});
    btn.classList.add('active');
    var pan=document.getElementById(pid); if(pan)pan.classList.add('active');
    if(window.__resizePlots)setTimeout(window.__resizePlots,0);
  });
})();
</script>"""


def _esc(x) -> str:
    return _html.escape(str(x if x is not None else "—"), quote=True)


def _inline_svg(svg_path: Optional[Path]) -> Optional[str]:
    """Read an emitted matplotlib SVG (svg.fonttype:none → text-preserving) and return its
    <svg>...</svg> body for inline embedding. Strips the XML/doctype preamble so it drops into
    the page. Returns None on any failure (render never blocks on the figure)."""
    if not svg_path or not Path(svg_path).exists():
        return None
    try:
        raw = Path(svg_path).read_text()
        i = raw.find("<svg")
        if i < 0:
            return None
        body = raw[i:]
        # Strip matplotlib's fixed pt width/height on the root <svg> so it scales to the card
        # (the viewBox preserves the aspect ratio). Belt-and-suspenders with the CSS rule.
        end = body.find(">")
        head, rest = body[:end], body[end:]
        head = re.sub(r'\s(width|height)="[^"]*"', "", head)
        return head + rest
    except Exception:  # noqa: BLE001
        return None


def _mtx_cell_class(cell: dict) -> str:
    if cell.get("signal") is None:
        return ""
    o = cell.get("ordinal")
    if o is None:
        return "off"
    return {2: "p2", 0: "p0", -1: "n1", -3: "n3"}.get(o, "p0")


def _prettify_field(key: str) -> str:
    """A summary-field key → readable label (snake/camel → words)."""
    k = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(key)).replace("_", " ").strip()
    return k[:1].upper() + k[1:]


def _plotly_bundle() -> Optional[str]:
    """The plotly.js source, for INLINING into the self-contained report (no CDN, no external src).
    ~4.6 MB — the deliberate weight of the dynamic dashboard. Cached; None if plotly is absent (the
    report then degrades to static SVG/table). NOTE: an inlined-plotly report is too large for the
    VS Code Simple Browser to render — download + open in a real browser to review it."""
    global _PLOTLY_JS_CACHE
    try:
        return _PLOTLY_JS_CACHE
    except NameError:
        pass
    try:
        from plotly.offline import get_plotlyjs
        _PLOTLY_JS_CACHE = get_plotlyjs()
    except Exception:  # noqa: BLE001
        _PLOTLY_JS_CACHE = None
    return _PLOTLY_JS_CACHE


def _read_card_plotly_specs(card_figures: Optional[dict], figures_dir: Optional[Path],
                            card_id: str) -> list[dict]:
    """For a card, load its interactive Plotly specs (the `dynamic: True` descriptors produced this
    run) from disk. Returns [{id, title, spec_json(str)}], newest-schema-safe. Empty when no dynamic
    figure was produced (→ the card renders its static table only — the fallback)."""
    if not card_figures or not figures_dir:
        return []
    out = []
    for f in card_figures.get(card_id) or []:
        if not f.get("dynamic"):
            continue
        spec_path = figures_dir / f["path"]
        try:
            spec_json = spec_path.read_text()
        except Exception:  # noqa: BLE001 — a missing spec just drops to the static view
            continue
        out.append({"id": f["id"], "spec_json": spec_json})
    return out


def _render_card_data_html(sub_results: dict, card_figures: Optional[dict] = None,
                           figures_dir: Optional[Path] = None) -> tuple[list[str], int]:
    """Per-question 'Evidence' section: render each sub-skill's card SUMMARY metrics (already in
    sub_results from resolve_cards) as clean data, PLUS — when a run produced them (Phase B) —
    the card's interactive Plotly figure(s) embedded inline. Leads with the PHASE_METRIC_FIELDS
    curated key metrics; otherwise shows the card's scalar summary fields.

    Returns (html_lines, n_plotly_embedded). A card with a dynamic spec shows the interactive chart
    above its data table; a card without one shows the table alone (the static fallback). The plot
    is a computed, provenanced artifact (drawn by the method from the same series as the SVG) — the
    renderer only EMBEDS it, never re-plots (honesty spine: renderer adds nothing)."""
    out = ["<section id=s-evidence class=det><span class=tag>Computed from the evidence</span>"
           "<h2>Evidence by question <span class=n>— the card data behind each call</span></h2>"]
    n_plotly = 0
    for short, r in sub_results.items():
        cards = r.get("cards") or []
        # gather scalar summary fields across this sub-skill's cards (skip private _ + nested)
        rows: list[tuple[str, str]] = []
        curated = PHASE_METRIC_FIELDS.get(short, [])
        seen = set()
        for field, label in curated:
            val = _first_card_summary_field(r, field)
            if val is not None:
                rows.append((label, _fmt_metric(val))); seen.add(field)
        for c in cards:
            if c.get("_missing"):
                continue
            for k, v in (c.get("summary") or {}).items():
                if k.startswith("_") or k in seen or isinstance(v, (list, dict)):
                    continue
                rows.append((_prettify_field(k), _fmt_metric(v))); seen.add(k)
        label = _GATE_SHORT_LABEL.get(short, _humanize(short))
        # Interactive figures produced for this sub-skill's cards this run (Phase B). Embedded as a
        # <div> + JSON <script>; the bootstrap at page end calls Plotly.newPlot. Absent → table only.
        plot_divs: list[str] = []
        for c in cards:
            if c.get("_missing"):
                continue
            for spec in _read_card_plotly_specs(card_figures, figures_dir, c.get("card_id")):
                dom_id = f"plt-{short}-{spec['id']}"
                plot_divs.append(
                    f"<div class=plotly-fig id={dom_id}></div>"
                    f"<script type='application/json' class=plotly-spec data-target={dom_id}>"
                    f"{spec['spec_json']}</script>")
                n_plotly += 1
        if not rows and not plot_divs:
            missing = [c["card_id"] for c in cards if c.get("_missing")]
            note = ("no card data (cards not available this run: "
                    + ", ".join(f"<code>{_esc(m)}</code>" for m in missing) + ")") if missing \
                    else "no scalar metrics emitted"
            out.append(f"<details><summary>{_esc(label)}</summary>"
                       f"<p class=sub>{note}.</p></details>")
            continue
        out.append(f"<details open><summary>{_esc(label)}</summary>")
        out.extend(plot_divs)                          # interactive chart(s) lead
        if rows:
            out.append("<table>")
            for lab, val in rows[:18]:   # cap to keep the section scannable
                out.append(f"<tr><td style='color:var(--muted);width:45%'>{_esc(lab)}</td>"
                           f"<td>{_esc(val)}</td></tr>")
            out.append("</table>")
        out.append("</details>")
    out.append("</section>")
    return out, n_plotly


# --- Gate section with subtabs (iterative dashboard, 2026-07-21) ------------------------------
# One gate (A–H) rendered as a section card with a radio-tab strip: Plots | Evidence | Rules.
# PURE PROJECTION — reads the same sub_results + card_figures the flat view uses; recomputes nothing.
# Scoped rollout: only the Presence gate (A / expression) is wired into the report today; the shared
# helper is gate-agnostic so the remaining gates slot in later without a rewrite.

_SIG_CLASS = {"supportive": "sig-pos", "opposing": "sig-neg", "killer": "sig-kill",
              "neutral": "sig-neu", "insufficient": "sig-neu"}

# Human title + one-line "what it shows" per presence-gate card. Keeps the subtab label short and
# the panel self-explaining. Extend as more gates migrate to the card-subtab style.
_CARD_TITLE = {
    # Selective (B)
    "tumor-vs-normal-selectivity":  ("Tumor-vs-normal", "3-cell sensitivity DEG (adjacent + GTEx comparators)"),
    # Mechanism (D)
    "signaling-network-mechanism":  ("Signaling network", "SIGNOR/CollecTri/Reactome MoA context"),
    # Presence (A)
    "cellline-rna-distribution":      ("Cell-line RNA", "DepMap pan-cancer expression distribution"),
    "tumor-rna-vs-adjacent": ("Tumor vs adjacent RNA", "TCGA tumor-vs-paired-normal DEG"),
    "tumor-protein-abundance-cptac":       ("Tumor protein (CPTAC)", "per-cohort tumor-vs-normal protein"),
    "cellline-protein-abundance":    ("Cell-line protein", "Gygi TMT MS abundance distribution"),
    "tumor-elevation-breadth":      ("Pan-cancer breadth", "elevated in K of N cancers"),
    # Required (C) — primary dependency evidence
    "pan-cancer-crispr-dependency-distribution": ("CRISPR dependency", "DepMap Chronos pan-cancer distribution"),
    "pan-cancer-rnai-dependency-distribution":   ("RNAi dependency", "DEMETER2 pan-cancer distribution"),
    "dependency-lineage-selectivity":            ("Lineage selectivity", "per-lineage Chronos forest"),
    "paralog-buffering":                         ("Paralog buffering", "dual-KO buffering (masks single-gene dep)"),
    # Required (C) — biomarker facets (see _CARD_V2_ROLE)
    "crispr-rnai-dependency-concordance": ("CRISPR×RNAi", "two LOF assays agree (corroboration)"),
    "prism-crispr-concordance":           ("Chemical-genetic", "compound kill tracks dependency (corroboration)"),
    "dependency-predictability":          ("Predictability", "how omics-learnable the dependency is (corroboration)"),
    "mutation-stratified-dependency":     ("Mutation-stratified", "dependency by mutation status (patient-selection)"),
    "expression-dependency-correlation":  ("Expression biomarker", "expression predicts dependency (patient-selection)"),
    "synthetic-lethal-partners":          ("SL partners", "curated synthetic-lethal context (patient-selection)"),
    # Surface-biologics modality-fit (axis 2) — composed verdict + its inputs
    "adc-tce-modality-fit":         ("ADC/TCE fit", "composed modality verdict (topology + family + structure)"),
    "surface-topology-and-ptm":     ("Topology & PTM", "TMbed transmembrane + endocytosis + PTM sites"),
    "surfaceome-family-classification": ("Surfaceome family", "SURFY/HPA surface-residency class"),
    "structure-features-static":    ("Structure", "PDB/AlphaFold pocket + disorder features"),
    "surface-abundance-density":    ("Surface density", "copies-per-cell estimate (TCE viability)"),
    # Small-molecule tractability (modality-fit)
    "prism-compound-activity":      ("Compound activity", "PRISM per-compound kill across cell lines"),
    # Safety (modality-fit)
    "gnomad-lof-constraint":        ("Germline constraint", "gnomAD LoF-intolerance (pLI / LOEUF)"),
}

# v2 role of a card WITHIN its gate (gate-model v2, docs/design/GATE_MODEL_V2_MEMO.md). Cards not
# listed are `primary` (the gate's own necessity evidence). Facets modulate the gate verdict:
#   corroboration  → agreement between measures of the same thing → CONFIDENCE in the verdict
#   stratification → a feature partitions the outcome → PATIENT-SELECTION (who responds)
_CARD_V2_ROLE = {
    # Required (C) biomarker facets
    "crispr-rnai-dependency-concordance": "corroboration",
    "prism-crispr-concordance":           "corroboration",
    "dependency-predictability":          "corroboration",
    "mutation-stratified-dependency":     "stratification",
    "expression-dependency-correlation":  "stratification",
    "synthetic-lethal-partners":          "stratification",
    # Surface-biologics (modality-fit): the composed verdict leads; the rest are its inputs.
    "adc-tce-modality-fit":               "composed",
}
_V2_ROLE_BADGE = {
    "composed":       ("verdict", "chip-pos"),
    "corroboration":  ("confidence", "chip-neu"),
    "stratification": ("patient-selection", "chip-pos"),
}

# reports_into (gate-model v2): cards whose HOME gate differs from a gate they ALSO feed. The
# dashboard renders each card under its home gate section; a breadcrumb ("also feeds <Gate>")
# surfaces the cross-gate contribution. These edges already exist as veto-suppressors / positive
# cross-refs in nomination_verdict_gate.yaml — this only makes them LEGIBLE in the dashboard.
#
# The map {card_id: [(label, anchor), ...]} is now BUILT FROM THE CONTRACT (_card_reports_into),
# reading each card-grain biomarker_facet's `card_id` + `reports_into` (v2 2.0.0). The hardcoded
# fallback below is used only when the contract carries no facet data (the v1 merge window, or a
# missing vocab) — same fail-open discipline as the loader: a missing contract never erases the
# breadcrumbs, it falls back to the last-known-good static map.
_CARD_REPORTS_INTO_FALLBACK = {
    "prism-crispr-concordance":       [("Required (C)", "s-gate-c")],
    "dependency-predictability":      [("Required (C)", "s-gate-c")],
    "mutation-stratified-dependency": [("Required (C)", "s-gate-c")],
}


def _card_reports_into(contracts_repo: Path | None = None) -> dict:
    """{card_id: [(label, anchor), ...]} of cross-gate breadcrumb edges, read from the contract's
    card-grain biomarker_facets (card_id + reports_into). Each reports_into target short resolves to
    its section anchor (_SHORT_TO_GATE_ANCHOR) + a human label (letter/name from the gate map). A
    self-edge (target == the card's own home gate) is dropped by the renderer, not here. Falls back
    to _CARD_REPORTS_INTO_FALLBACK when the contract exposes no card-grain facets (v1 window)."""
    repo = contracts_repo or _CONTRACTS_REPO
    path = repo / "vocabularies" / "gate_coverage.yaml"
    try:
        data = yaml.safe_load(path.read_text())
        facets = data.get("biomarker_facets", []) or []
    except Exception:  # noqa: BLE001 — missing/malformed vocab → fall back, never erase breadcrumbs
        facets = []
    # short → human gate label (e.g. dependency → "Required (C)"); built from the loaded baseline so
    # letters/names track the contract. Biology gates: "<name> (<letter>)"; modality-fit: "<name>".
    baseline, _src = _load_gate_coverage(contracts_repo)
    def _label(short: str) -> str:
        m = baseline.get(short, {})
        nm, letter = m.get("gate_name") or _humanize(short), m.get("gate")
        return f"{nm} ({letter})" if letter else nm
    out: dict = {}
    for f in facets:
        cid = f.get("card_id")
        if not cid or f.get("grain") != "card":
            continue
        edges = [(_label(s), _SHORT_TO_GATE_ANCHOR[s]) for s in (f.get("reports_into") or [])
                 if s in _SHORT_TO_GATE_ANCHOR]
        if edges:
            out[cid] = edges
    return out or {k: list(v) for k, v in _CARD_REPORTS_INTO_FALLBACK.items()}

# Roll-up lens: sub-skill short → the gate SECTION anchor it belongs to (the id _render_gate_section_html
# emits). Lets the top scorecard link each question-row down to its detailed section. MUST stay in sync
# with _GATE_SECTIONS in _render_target_profile_html (biology gates → s-gate-<letter>; modality-fit gates
# → s-gate-<name-slug>). Sub-skills that report_into another gate but have their own section link to their
# HOME section (e.g. synthetic_lethal_partners + genomic_alteration are unified UNDER Required's section).
# Flat layout: each short links to its OWN subskill section anchor (s-skill-<short>). A
# reports_into breadcrumb ("Also feeds …") therefore points at a section that actually renders.
_SHORT_TO_GATE_ANCHOR = {
    "expression":                _subskill_anchor("expression"),
    "selectivity":               _subskill_anchor("selectivity"),
    "dependency":                _subskill_anchor("dependency"),
    "synthetic_lethal_partners": _subskill_anchor("synthetic_lethal_partners"),
    "mechanism":                 _subskill_anchor("mechanism"),
    "genomic_alteration":        _subskill_anchor("genomic_alteration"),
    "tractability_sm":           _subskill_anchor("tractability_sm"),
    "surface_modality":          _subskill_anchor("surface_modality"),
    "safety":                    _subskill_anchor("safety"),
}
# Which summary fields to surface as the card's "key facts" (label, field). First hit wins per card;
# unknown cards fall back to their first ~4 scalar summary fields.
_CARD_KEYFACTS = {
    "cellline-rna-distribution": [("Call", "expression_call_class"), ("Median log2TPM", "median_log2tpm_panel"),
                                ("Cell lines", "n_cell_lines"),
                                # additive isoform-EXPRESSION facet (roadmap #2 model arm): WHICH transcript
                                # carries the expression — a single-isoform target is a cleaner modality/
                                # epitope target; isoform_diverse flags that the druggable isoform must be
                                # specified (complements the mechanism isoform_selective_warning note).
                                ("Isoform", "isoform_expression_class"),
                                ("Dominant-iso frac", "dominant_isoform_fraction")],
    "tumor-rna-vs-adjacent": [("Call", "expression_call_class"), ("log2FC", "log2_fc"),
                                     ("q-value", "q_value")],
    "tumor-protein-abundance-cptac": [("Class", "protein_expression_class"), ("Effect size", "protein_effect_size"),
                               ("Cohort", "cohort"), ("n tumor", "n_tumor_samples"),
                               ("n normal", "n_normal_samples")],
    "cellline-protein-abundance": [("Class", "protein_expression_class")],
    "tumor-elevation-breadth": [("Breadth", "tumor_elevation_breadth_class"),
                                ("Protein K/N", "n_cohorts_elevated"), ("RNA K/N", "rna_n_indications_elevated")],
    # Required (C)
    "pan-cancer-crispr-dependency-distribution": [("Class", "dependency_class"),
                                                  ("Median Chronos", "median_chronos_panel"),
                                                  ("% dependent", "fraction_dependent")],
    "pan-cancer-rnai-dependency-distribution": [("Class", "dependency_class"),
                                                ("Median DEMETER2", "median_demeter2")],
    "dependency-lineage-selectivity": [("Selectivity", "lineage_selectivity_class"),
                                       ("Selective lineages", "n_selective_lineages")],
    "paralog-buffering": [("Buffering", "paralog_buffering_class"),
                          ("Strongest paralog", "strongest_paralog_symbol")],
    "crispr-rnai-dependency-concordance": [("Concordance", "concordance_class")],
    "prism-crispr-concordance": [("Class", "crispr_prism_concordance_class"),
                                 ("Compounds", "n_compounds_evaluated")],
    "dependency-predictability": [("Predictability", "predictability_class"),
                                  ("Top feature", "pred_dominant_feature_class")],
    "mutation-stratified-dependency": [("Class", "mutation_stratification_class"),
                                       ("Hotspot q", "hotspot_mannwhitney_q")],
    "expression-dependency-correlation": [("Correlation", "correlation_class")],
    "synthetic-lethal-partners": [("SL class", "sl_partner_class"),
                                  ("Strongest partner", "strongest_partner_symbol")],
    # Surface-biologics modality-fit
    "adc-tce-modality-fit": [("Fit", "fit_class"), ("ADC topology", "is_adc_topology_favorable"),
                             ("TCE topology", "is_tce_topology_favorable")],
    "surface-topology-and-ptm": [("TM passes", "tm_pass_count"), ("EC residues", "extracellular_residue_count"),
                                 ("Endo motifs", "endocytosis_motif_count_high_confidence")],
    "surfaceome-family-classification": [("Surface?", "is_surface_protein"), ("Family", "family_class")],
    "structure-features-static": [("Druggable pocket", "has_druggable_pocket"), ("Disorder", "disorder_fraction")],
    "surface-abundance-density": [("Copies/cell", "estimated_copies_per_cell"),
                                  ("TCE-viable", "above_tce_threshold")],
    # Selective (B)
    "tumor-vs-normal-selectivity": [("Selectivity", "selectivity_class"),
                                    ("Cells supporting", "cells_supporting"), ("Direction", "dominant_direction")],
    # Mechanism (D)
    "signaling-network-mechanism": [("Network", "network_class"), ("Upstream", "n_upstream_regulators"),
                                    ("Downstream", "n_downstream_effectors")],
    # Small-molecule tractability (modality-fit)
    "prism-compound-activity": [("Activity", "prism_activity_class"), ("Compounds", "n_compounds_targeting"),
                                ("Top clinical phase", "highest_clinical_phase")],
    # Safety (modality-fit)
    "gnomad-lof-constraint": [("Constraint", "constraint_class"), ("pLI", "pli_score"), ("LOEUF", "loeuf_score")],
}


# Per-card figure curation for the gate subtabs: which figure ids to show, in order. A card that
# emits several figures may want only a subset surfaced in the dashboard (the rest stay in the
# data package). None → show all, in emit order. Presence gate: Cell-line RNA leads with the
# pan-cancer DENSITY then the per-LINEAGE box (the indication-relevant view); the ranked waterfall
# is available in the package but not surfaced here (redundant with the density for this section).
_CARD_FIGURE_ORDER = {
    "cellline-rna-distribution": ["density_expression", "lineage_expression"],
    # cell-line protein (item #2): density (bucket-shaded) + per-lineage box, mirroring RNA;
    # the ranked waterfall is emitted but not surfaced in the subtab (matches the RNA card).
    "cellline-protein-abundance": ["density_protein_abundance", "lineage_protein_abundance"],
}


def _card_plot_divs(card_id: str, card_figures, figures_dir) -> tuple[list[str], int]:
    """Interactive Plotly divs for ONE card (same embed the flat view uses). When the card has a
    curated figure order (_CARD_FIGURE_ORDER), only those ids are shown, in that order."""
    specs = {s["id"]: s for s in _read_card_plotly_specs(card_figures, figures_dir, card_id)}
    order = _CARD_FIGURE_ORDER.get(card_id) or list(specs.keys())
    divs, n = [], 0
    for sid in order:
        spec = specs.get(sid)
        if not spec:
            continue
        dom_id = f"plt-card-{card_id}-{spec['id']}"
        divs.append(f"<div class=plotly-fig id={dom_id}></div>"
                    f"<script type='application/json' class=plotly-spec data-target={dom_id}>"
                    f"{spec['spec_json']}</script>")
        n += 1
    return divs, n


def _fmt_fact_value(value):
    """Rail key-metric value formatter: numbers via _fmt_metric, but snake_case STRING enums are
    humanized (broadly_high → "Broadly high") so raw tokens never leak into visible dashboard text.
    (The .md table keeps _fmt_metric's backticked raw values — code style there is fine.)"""
    if isinstance(value, str) and value and not value.replace(".", "").replace("-", "").isdigit():
        return _humanize(value)
    return _fmt_metric(value)


def _card_key_facts(card: dict) -> list[tuple[str, str]]:
    """The card's headline facts (label, formatted value) — curated per card, else first scalars."""
    cid = card.get("card_id")
    summ = card.get("summary") or {}
    facts: list[tuple[str, str]] = []
    for label, field in _CARD_KEYFACTS.get(cid, []):
        if summ.get(field) is not None:
            facts.append((label, _fmt_fact_value(summ[field])))
    if not facts:   # fallback: first few scalar summary fields
        for k, v in summ.items():
            if k.startswith("_") or isinstance(v, (list, dict)):
                continue
            facts.append((_prettify_field(k), _fmt_fact_value(v)))
            if len(facts) >= 4:
                break
    return facts


def _card_fired_rules(card_id: str, fired: list) -> list[dict]:
    """The fired rules attributable to THIS card (by card_id)."""
    return [f for f in (fired or []) if isinstance(f, dict) and f.get("card_id") == card_id]


# Indication → DepMap OncotreeLineage (cell lines are lineage-keyed; the indication-relevant
# cell-line view is its lineage). Mirrors the method-side map; kept here so the renderer can pull
# the indication's lineage row without importing the method.
_INDICATION_LINEAGE = {
    "COADREAD": "Bowel", "COAD": "Bowel", "READ": "Bowel", "PDAC": "Pancreas", "PAAD": "Pancreas",
    "NSCLC": "Lung", "LUAD": "Lung", "LUSC": "Lung", "SCLC": "Lung", "GC": "Stomach", "STAD": "Stomach",
    "BRCA": "Breast", "OV": "Ovary/Fallopian Tube", "GBM": "CNS/Brain", "HNSCC": "Head and Neck",
}


def _expression_indication_focus(card: dict, indication: str) -> Optional[dict]:
    """Item 4: for the cell-line RNA card, pull the INDICATION's lineage row from per_lineage_stats
    (COADREAD→Bowel) and build human-readable interpretation. Returns None if not applicable / no
    lineage data. Output: {lineage, median_log2tpm, fraction_expressed, n, rank, n_lineages, interp}."""
    summ = card.get("summary") or {}
    stats = summ.get("per_lineage_stats")
    if not indication or not isinstance(stats, list) or not stats:
        return None
    lineage = _INDICATION_LINEAGE.get(indication.upper())
    if not lineage:
        return None
    # per_lineage_stats is sorted by median_log2tpm desc → index = rank
    row = None
    for i, s in enumerate(stats):
        if s.get("lineage") == lineage:
            row = dict(s); row["rank"] = i + 1
            break
    n_lin = summ.get("n_lineages_evaluated") or len(stats)
    if row is None:
        # indication's lineage not among the evaluated lineages (below the n≥5 floor, or absent)
        return {"lineage": lineage, "absent": True, "n_lineages": n_lin,
                "interp": (f"No {lineage} cell-line cohort cleared the n≥5 floor in DepMap this "
                           f"release, so a {indication}-lineage expression readout isn't available "
                           f"— the pan-cancer distribution is the only cell-line view here.")}
    med = row.get("median_log2tpm")
    frac = row.get("fraction_expressed")
    n = row.get("n")
    rank = row.get("rank")
    # human-readable interpretation (bucketed against the 1.0 / 5.0 reflines)
    if med is None:
        level = "unknown"
    elif med >= 5.0:
        level = "highly expressed"
    elif med >= 1.0:
        level = "expressed"
    else:
        level = "low / not expressed"
    pct = f"{frac*100:.0f}%" if isinstance(frac, (int, float)) else "—"
    med_str = f"{med:.1f}" if isinstance(med, (int, float)) else "n/a"
    interp = (f"In {lineage} cell lines ({indication}'s DepMap lineage; n={n}), the target is "
              f"<b>{level}</b> — median log2(TPM+1) {med_str}, {pct} of lines above the expressed "
              f"threshold. It ranks {rank} of {n_lin} lineages by median expression"
              + (" (among the highest)." if rank and rank <= 3 else
                 " (mid-to-low among lineages)." if rank and rank > n_lin/2 else "."))
    return {"lineage": lineage, "median_log2tpm": med, "fraction_expressed": frac,
            "n": n, "rank": rank, "n_lineages": n_lin, "interp": interp, "level": level}


def _render_gate_section_html(gate: str, gate_name: str, shorts: list[str], sub_results: dict,
                              scorecard_by_short: dict, card_figures, figures_dir,
                              indication: str = None, modality_note: str = None,
                              reports_into_map: dict | None = None,
                              exclude_card_ids: set | None = None,
                              include_only_card_ids: list | None = None,
                              sec_id: str | None = None,
                              grounded_html: list[str] | None = None) -> tuple[list[str], int]:
    """Render ONE gate as a section whose SUBTABS are its evidence CARDS. Each card subtab shows,
    top-to-bottom: a verdict strip (the rule/verdict this card drove), the card's key facts, and its
    interactive Plotly figure. PURE PROJECTION — recomputes nothing. Returns (html, n_plotly).

    `shorts` are the sub-skills grouped under this gate letter (usually one; C has several). A gate's
    cards are the union of its sub-skills' cards, in declaration order. Cards with no data this run
    still get a subtab (greyed 'gap' label) — a coverage gap is shown, never hidden.
    `modality_note`: for axis-2 (modality-fit) gates, a one-line 'relevant for <modalities>' banner —
    the gate's relevance is lens-conditional (gate-model v2)."""
    # section id + tab-group key: gate letter if lettered, else a slug of the gate_name (modality-fit
    # gates are NAMED, not lettered in v2). glow is the unique key used for panel ids + tab scoping.
    glow = gate.lower() if gate else re.sub(r"[^a-z0-9]+", "-", gate_name.lower()).strip("-")
    sec_id = sec_id or f"s-gate-{glow}"
    # No "Computed from the evidence" tag on gate sections — it's redundant chrome repeated on every
    # gate (the whole Biology/Modality-fit axis IS the deterministic evidence; the AI-generated
    # exec summary is the only section that needs a provenance tag).
    out = [f"<section id={sec_id} class='det gate'>"]

    # header: gate letter + name + roll-up verdict chip(s) (the gate's own sub-verdict). A
    # facet-collection section (include_only_card_ids, e.g. Biomarker) has NO single sub-verdict —
    # it's a set of relational facet cards, each with its own role badge — so suppress the chips.
    _is_facet_section = include_only_card_ids is not None
    chips = []
    if not _is_facet_section:
        for short in shorts:
            row = scorecard_by_short.get(short) or {}
            glyph, cls, _lab = _HTML_STATUS.get(row.get("status"), _HTML_STATUS["coverage_gap"])
            chips.append(f"<span class='chip {cls}'><span class=g>{glyph}</span>"
                         f"{_esc(_humanize(row.get('verdict') or 'not evaluated'))}</span>")
    q = (gate_name if (_is_facet_section or len(shorts) != 1)
         else _GATE_SHORT_LABEL.get(shorts[0], _humanize(shorts[0])))
    letter = f"<span class=gate-letter>{_esc(gate)}</span>" if gate else ""   # named (modality-fit) gates: no letter
    out.append(f"<div class=gate-head>{letter}"
               f"<h2 style='margin:0;background:none;color:var(--brand);padding:0'>{_esc(gate_name)} "
               f"<span class=n>— {_esc(q)}</span></h2>"
               f"<span class=gate-verdict>{''.join(chips)}</span></div>")
    if modality_note:
        # axis-2 lens banner: this gate's relevance is modality-conditional (gate-model v2).
        out.append(f"<div class=banner style='margin-top:6px'>{_esc(modality_note)}</div>")
    # per-subskill GROUNDED literature block (escalate-only findings / honest not-configured note),
    # placed high in the section so a reader sees the literature liabilities alongside the verdict.
    if grounded_html:
        out.extend(grounded_html)

    # collect this gate's cards (union across sub-skills), each with its owning sub-skill's fired rules.
    # exclude_card_ids: facet cards routed OUT to the Biomarker section (so gates C/E don't double-show
    # them). include_only_card_ids: when set (the Biomarker section), keep ONLY these cards + render in
    # that order — collecting the facet cards from wherever their sub-skills live.
    excl = exclude_card_ids or set()
    cards: list[tuple[dict, list]] = []
    for short in shorts:
        r = sub_results.get(short, {})
        fired = r.get("fired") or []
        for c in (r.get("cards") or []):
            cid = c.get("card_id")
            if cid in excl:
                continue
            if include_only_card_ids is not None and cid not in include_only_card_ids:
                continue
            cards.append((c, fired))
    if include_only_card_ids is not None:
        # order by the requested include list (stable) so the Biomarker section reads intentionally
        _ord = {cid: i for i, cid in enumerate(include_only_card_ids)}
        cards.sort(key=lambda cf: _ord.get(cf[0].get("card_id"), 999))
    if not cards:
        out.append("<p class=empty-note>No evidence cards ran for this subskill this run.</p></section>")
        return out, 0

    # v2 ordering: PRIMARY (the gate's own necessity evidence) first, then biomarker FACETS
    # (corroboration → confidence, stratification → patient-selection). Stable within each group.
    # composed verdict FIRST (-1); then primary (0); then facets (corroboration, stratification).
    _role_order = {"composed": -1, None: 0, "corroboration": 1, "stratification": 2}
    cards.sort(key=lambda cf: _role_order.get(_CARD_V2_ROLE.get(cf[0].get("card_id")), 0))

    n_plotly_total = 0
    # default tab = first card that has a live plot, else first card
    default_idx = 0
    for i, (c, _f) in enumerate(cards):
        if _card_plot_divs(c.get("card_id"), card_figures, figures_dir)[0]:
            default_idx = i
            break

    # tablist (buttons) + panels. JS (page bootstrap) toggles .active on click; a panel is
    # data-tabgroup-scoped so gates switch independently. Panel id = <sec_id>-p<i>.
    tabs = [f"<div class=tabs data-tabgroup={sec_id}>", "<div class=tablist role=tablist>"]
    panels = []
    for i, (c, fired) in enumerate(cards):
        cid = c.get("card_id")
        title, _blurb = _CARD_TITLE.get(cid, (_humanize(cid), ""))   # blurb no longer shown (was mislabeling multi-plot cards)
        missing = c.get("_missing")
        active = " active" if i == default_idx else ""
        pid = f"{sec_id}-p{i}"
        lab_cls = " gap" if missing else ""
        # v2 role badge (confidence / patient-selection) on facet cards; primary cards get none.
        role = _CARD_V2_ROLE.get(cid)
        badge = ""
        if role and role in _V2_ROLE_BADGE:
            btxt, bcls = _V2_ROLE_BADGE[role]
            badge = f"<span class='chip {bcls}' style='margin-left:6px;font-size:9.5px;padding:1px 6px'>{btxt}</span>"
        tabs.append(f"<button class='tab{lab_cls}{active}' data-panel={pid}>{_esc(title)}{badge}</button>")

        pan = [f"<div class='panel{active}' id={pid}>"]
        if missing:
            pan.append(f"<p class=empty-note>{_esc(title)} — card not available this run "
                       f"(<code>{_esc(cid)}</code>). Coverage gap, not a negative.</p></div>")
            panels.append("".join(pan)); continue

        # 2-column body (item 3): plots (left) + summary rail (right).
        pan.append("<div class=card-body>")

        # -- LEFT: the interactive plot(s) --
        divs, npl = _card_plot_divs(cid, card_figures, figures_dir)
        n_plotly_total += npl
        pan.append("<div class=card-plots>")
        if divs:
            pan.extend(divs)
        else:
            pan.append("<p class=empty-note>No chart produced this run — the summary metrics "
                       "are at right; a static/summary run embeds no plot for this card.</p>")
        pan.append("</div>")   # .card-plots

        # -- RIGHT: summary rail — key facts, indication focus (item 4), rule/verdict fired --
        pan.append("<div class=card-rail>")
        facts = _card_key_facts(c)
        if facts:
            pan.append("<div class=rail-sec><p class=rail-h>Key metrics</p>")
            for label, val in facts:
                pan.append(f"<div class=kf><span>{_esc(label)}</span><b>{_esc(val)}</b></div>")
            pan.append("</div>")
        # indication-lineage focus (cell-line RNA): metric + human-readable interpretation
        focus = _expression_indication_focus(c, indication) if cid == "cellline-rna-distribution" else None
        if focus:
            pan.append(f"<div class=rail-sec><p class=rail-h>{_esc(indication)} focus "
                       f"({_esc(focus['lineage'])})</p>")
            if not focus.get("absent"):
                pan.append(f"<div class=kf><span>Median log2TPM</span><b>{focus['median_log2tpm']:.1f}</b></div>"
                           if isinstance(focus.get('median_log2tpm'), (int, float)) else "")
                if isinstance(focus.get("fraction_expressed"), (int, float)):
                    pan.append(f"<div class=kf><span>% lines expressed</span>"
                               f"<b>{focus['fraction_expressed']*100:.0f}%</b></div>")
                if focus.get("rank"):
                    pan.append(f"<div class=kf><span>Lineage rank</span>"
                               f"<b>{focus['rank']} / {focus['n_lineages']}</b></div>")
            pan.append(f"<div class=interp>{focus['interp']}</div>")
            pan.append("</div>")
        # rule / verdict fired for this card
        crules = _card_fired_rules(cid, fired)
        pan.append("<div class=rail-sec><p class=rail-h>Rule fired</p>")
        if crules:
            top = crules[0]
            sigs = top.get("signals") or {}
            sig_html = " · ".join(
                f"<span class={_SIG_CLASS.get(v, 'sig-neu')}>{_esc(m)}: {_esc(v)}</span>"
                for m, v in sigs.items()) or "—"
            pan.append(f"<div><code>{_esc(top.get('rule_id'))}</code></div>"
                       f"<div style='margin-top:4px'>{sig_html}</div>")
        else:
            pan.append("<div class=sub>No rule fired (neutral / below threshold).</div>")
        pan.append("</div>")
        # reports_into breadcrumb (v2): if this card ALSO feeds other gate(s), name them — read from
        # the contract (reports_into_map, {card_id: [(label, anchor), ...]}) with a fallback to the
        # static map. Self-edges (target == the section we're already in) are dropped, so a card
        # rendered under its home gate never "also feeds" itself.
        rmap = reports_into_map if reports_into_map is not None else _CARD_REPORTS_INTO_FALLBACK
        edges = [(lbl, anc) for (lbl, anc) in (rmap.get(cid) or []) if anc != sec_id]
        if edges:
            links = " · ".join(f"<a href='#{anc}' style='color:var(--brand-accent);"
                               f"text-decoration:none'>→ {_esc(lbl)}</a>" for lbl, anc in edges)
            pan.append(f"<div class=rail-sec><p class=rail-h>Also feeds</p>"
                       f"<div class=sub>{links} "
                       f"(this evidence corroborates that gate too)</div></div>")
        # Data-source / version tag: card readers stamp summary._data_source with the derived-
        # manifest id or release-pinned source (e.g. "DepMap-26Q1 Chronos",
        # "coadread-dge-tumor-vs-normal-sensitivity-v1", "recount3-tcga-gtex-2023-01-04"). Surface it
        # so each panel names WHICH data product + version it resolved against (provenance at a glance,
        # mirroring provenance.yaml's data_provenance). _data_s3_uri, when present, is the hover title.
        csum = c.get("summary") or {}
        dsrc = csum.get("_data_source")
        if dsrc:
            title = csum.get("_data_s3_uri") or ""
            title_attr = f" title='{_esc(str(title))}'" if title else ""
            pan.append(f"<div class=rail-sec><p class=rail-h>Data source</p>"
                       f"<div class=sub{title_attr}><code>{_esc(str(dsrc))}</code></div></div>")
        pan.append(f"<p class=card-src>Card <code>{_esc(cid)}</code></p>")
        pan.append("</div>")   # .card-rail

        pan.append("</div>")   # .card-body
        pan.append("</div>")   # .panel
        panels.append("".join(pan))

    tabs.append("</div>")     # .tablist
    out.extend(tabs)
    out.extend(panels)
    out.append("</div></section>")   # .tabs
    return out, n_plotly_total


# Literature risk-level → chip class + label (LOW is good news = positive chip; HIGH = negative).
_LIT_RISK_CHIP = {
    "LOW": ("chip-pos", "LOW"), "MEDIUM": ("chip-neu", "MEDIUM"),
    "HIGH": ("chip-neg", "HIGH"), "not_assessed": ("chip-gap", "not assessed"),
}
_LIT_DIM_ORDER = ["biological", "druggability", "translational", "clinical", "safety", "commercial"]


def _pubmed_links(pmids: list) -> str:
    if not pmids:
        return "<span class=sub>none</span>"
    return ", ".join(f"<a href='https://pubmed.ncbi.nlm.nih.gov/{_esc(str(p))}/' target=_blank "
                     f"rel=noopener>{_esc(str(p))}</a>" for p in pmids)


def _render_literature_risk_html(ra: Optional[dict]) -> list[str]:
    """The target×indication-level 6-dimension literature RISK panel (from literature-risk-assessment's
    risk_assessment.json). CONTEXT-TIER — rendered as a visually-separate, explicitly-labeled
    'non-reproducible, as-of-DATE' block per RISK_ASSESSMENT_INTEGRATION.md §4; NEVER fused into the
    deterministic grid and NEVER a verdict input. Each dimension: risk grade + the literature's STATE
    read + what-could-kill-it, with cited (retrieved, confab-guarded) PMIDs."""
    if not ra or not ra.get("dimensions"):
        return []
    prov = ra.get("provenance", {}) or {}
    pin = prov.get("corpus_pin", {}) or {}
    mindate, maxdate = pin.get("mindate", ""), pin.get("maxdate", "")
    asof = str(prov.get("generated_at", ""))[:10]
    ind = ra.get("indication", "")
    model = prov.get("synthesis_model", "")
    out = ["<section id=s-litrisk class='llm lit-risk'>"
           "<span class='tag tag-corner'>AI-generated · literature context</span>"
           "<h2>Literature risk assessment <span class=n>— 6 drug-discovery dimensions, "
           "retrieval-grounded</span></h2>",
           "<div class=banner style='background:#fff8e1;border-left:3px solid #e0a800'>"
           "<b>Context only — not a verdict input, not reproducible</b> "
           "(<code>citable_in_nominations: false</code>). Retrieval-grounded over PubMed "
           f"{_esc(mindate)}–{_esc(maxdate)} for <b>{_esc(ind)}</b>; every claim cites only retrieved "
           f"PMIDs (confabulation-guarded). As-of {_esc(asof)}.</div>",
           "<table><tr><th>Dimension</th><th>5R pillar</th><th>Risk</th>"
           "<th>What the literature says (state) · what could kill it (risk)</th>"
           "<th>Cited PMIDs</th></tr>"]
    dims = ra["dimensions"]
    for k in _LIT_DIM_ORDER + [d for d in dims if d not in _LIT_DIM_ORDER]:
        d = dims.get(k)
        if not d:
            continue
        cls, lab = _LIT_RISK_CHIP.get(str(d.get("risk_level")), ("chip-gap", str(d.get("risk_level"))))
        contra = (" <span class=badge-rule title='Literature diverges from the deterministic verdict'>"
                  "⚠ diverges from computed verdict</span>") if d.get("contradicts_deterministic") else ""
        cell = (f"<div><b>State:</b> {_esc(d.get('interpretation') or '—')}</div>"
                f"<div style='margin-top:4px'><b>Risk:</b> {_esc(d.get('justification') or '—')}{contra}</div>")
        out.append(f"<tr><td><b>{_esc(k.title())}</b></td>"
                   f"<td class=sub>{_esc(d.get('pillar', ''))}</td>"
                   f"<td><span class='chip {cls}'>{_esc(lab)}</span></td>"
                   f"<td>{cell}</td><td class=sub>{_pubmed_links(d.get('cited_pmids') or [])}</td></tr>")
    out.append("</table>")
    out.append(f"<p class=sub style='margin-top:8px'>Model <code>{_esc(model)}</code> · corpus pinned "
               "(PMIDs + query + date window) in <code>risk_assessment.json</code>. Grades are "
               "literature-derived context, held separate from the deterministic sub-verdicts.</p>")
    out.append("</section>")
    return out


def _grounded_block_html(short: str, grounded_record: Optional[dict]) -> list[str]:
    """Per-subskill GROUNDED literature block (from ground_axis). Escalate-only, PMID-cited findings
    that RAISE this axis's risk (liability / dependency-weakening), anchored to the deterministic
    verdict. When ground_axis isn't configured for this axis, render an honest 'not yet grounded'
    note (coverage-gap honesty discipline) rather than silence."""
    if not grounded_record or not grounded_record.get("grounded"):
        if short in _GROUNDABLE_AXES:
            return []  # groundable but not run this time — say nothing rather than a false gap
        return ["<div class=grounded grounded-none><span class=tag>Literature grounding</span>"
                " Grounded literature reader not yet configured for this axis "
                "<span class=sub>(currently: safety, dependency — see literature-risk-assessment"
                " <code>ground_axis</code>).</span></div>"]
    g = grounded_record["grounded"]
    findings = g.get("findings") or []
    anchor = _humanize(g.get("anchor_verdict") or "—")
    pin = g.get("corpus_pin", {}) or {}
    n_ret = g.get("n_retrieved", 0)
    dropped = len(g.get("confabulated_dropped") or [])
    contra = (" <span class=badge-rule title='Literature diverges from the deterministic verdict'>"
              "⚠ diverges from computed verdict</span>") if g.get("contradicts_deterministic") else ""
    out = ["<div class=grounded><span class=tag>Literature grounding · escalate-only</span>"
           f"<b>Grounded findings</b> — PMID-cited literature that can only RAISE this axis's risk, "
           f"anchored to the computed verdict <code>{_esc(anchor)}</code>.{contra} "
           f"<span class=sub>{n_ret} abstracts retrieved (PubMed {_esc(pin.get('mindate',''))}–"
           f"{_esc(pin.get('maxdate',''))}); {dropped} confabulated PMID(s) dropped.</span>"]
    if not findings:
        out.append("<p class=sub>No escalating literature findings for this axis in the retrieved "
                   "corpus.</p></div>")
        return out
    out.append("<ul class=grounded-findings>")
    for f in findings:
        out.append(f"<li><b>{_esc(f.get('kind') or 'finding')}:</b> {_esc(f.get('finding') or '')} "
                   f"<span class=sub>{_pubmed_links(f.get('cited_pmids') or [])}</span></li>")
    out.append("</ul>")
    corr = g.get("corroborations") or []
    if corr:
        out.append("<p class=sub><b>Corroborations of the computed verdict:</b> "
                   + _esc("; ".join(corr)) + "</p>")
    out.append("</div>")
    return out


def _render_target_profile_html(
    target: str,
    indication: str,
    sub_results: dict,
    llm_output: dict,
    invoked_lenses: dict,
    deciding_axis: Optional[dict] = None,
    ordinal_matrix: Optional[dict] = None,
    scorecard: Optional[list[dict]] = None,
    composite_svg_path: Optional[Path] = None,
    catalogue_rows: Optional[list[dict]] = None,
    recommendation_gate: Optional[dict] = None,
    show_deciding_axis: bool = False,
    card_figures: Optional[dict] = None,
    figures_dir: Optional[Path] = None,
    presence_only: bool = False,
    presence_facet: Optional[dict] = None,
    risk_assessment: Optional[dict] = None,
    grounded_by_axis: Optional[dict] = None,
) -> str:
    """Render a self-contained target_profile.html — the governance artifact. Pure projection of the
    same nomination data the .md carries; no recompute. All structured outputs (scorecard,
    deciding-axis, ordinal matrix) are DETERMINISTIC sections, visually distinct from the
    AI-generated ones.

    DYNAMIC vs STATIC (Phase B): when a run produced per-card interactive figures (`card_figures` +
    `figures_dir`), their Plotly specs are EMBEDDED inline (plotly.js inlined once, a small vanilla-JS
    bootstrap draws them) — the dashboard reads like the GI team's interactive charts while staying a
    single archivable file with zero external deps. When no figure was produced (the default / a
    data-blocked run / plotly absent), the report degrades to the STATIC card tables — same file, no
    JS. The renderer only EMBEDS the method-drawn spec; it never re-plots (honesty spine intact).
    NOTE: an inlined-plotly report is ~4.6 MB and won't render in the VS Code Simple Browser —
    download + open in a real browser to review."""
    def _val(field, default="—"):
        raw = llm_output.get(field)
        return raw.get("value", default) if isinstance(raw, dict) else (raw if raw is not None else default)

    p: list[str] = ["<!DOCTYPE html><html lang=en><head><meta charset=utf-8>",
                    "<meta name=viewport content='width=device-width,initial-scale=1'>",
                    f"<title>Target profile — {_esc(target)} × {_esc(indication)}</title>",
                    f"<style>{_HTML_CSS}</style></head><body>"]

    # --- Header band: title + the headline recommendation ------------------
    action = str(_val("overall_recommendation"))
    term, gloss = _ACTION_GLOSS.get(action, (action, ""))
    action_html = f"<b>{_esc(term)}</b>" + (f" — {_esc(gloss)}" if gloss else "")
    # "Rule-checked" badge: when a deterministic gate overrode the AI's choice, say so on hover.
    rg = recommendation_gate or {}
    if rg.get("fired"):
        forced = rg.get("forced_recommendation", action)
        llm_said = rg.get("llm_recommendation")
        tip = (f"A deterministic safety/quality rule set this call. "
               f"The AI suggested '{llm_said}'; a rule required '{forced}'."
               if rg.get("overridden") else
               "A deterministic rule confirmed the AI's call.")
        checked = f"<span class=badge-rule title=\"{_esc(tip)}\">✓ rule-checked</span>"
    else:
        checked = ("<span class=badge-rule title=\"No override rule fired; the AI's recommendation "
                   "stands, checked against the deterministic gate.\">✓ rule-checked</span>")
    if presence_only:
        # Focused view: clean "TARGET × INDICATION" header, no recommendation clutter.
        p.append(f"<header><h1>{_esc(target)} <span style='opacity:.6;font-weight:400'>×</span> "
                 f"{_esc(indication)}</h1></header>")
    else:
        p.append("<header>"
                 f"<h1>{_esc(target)} <span style='opacity:.7;font-weight:400'>in</span> {_esc(indication)}"
                 " — target profile</h1>"
                 f"<div class=rec>Recommendation: {action_html}"
                 f" · confidence <span class=pill>{_esc(_val('confidence'))}</span> {checked}"
                 f" <span style='opacity:.7;font-size:12px'>· AI-generated</span></div>"
                 "</header>")

    # --- Presence × Context hero (deterministic VIEW) ----------------------
    # Renders tumor-presence's cross-modal reconciliation (presence_facet.presence_verdict_by_modality)
    # as a compact state-matrix: measurement layers × sample contexts, PRESENCE block + normal-tissue
    # WINDOW block. Rendered INLINE from the facet (no figure-file dependency); DISPLAY-ONLY (order-
    # preserving tiers, off-scale for unmeasured/comparator cells, never a verdict input). Placed high
    # so the one-word presence verdict is never read without its cross-modal decomposition.
    if presence_facet and presence_facet.get("presence_verdict_by_modality"):
        try:
            from _skills_common.presence_matrix import render_presence_matrix_svg
            _hero_svg = render_presence_matrix_svg(presence_facet, target, indication)
            p.append("<section id=s-presence-matrix class=det>"
                     "<span class=tag>Deterministic VIEW — not a score</span>"
                     "<h2>Presence × context <span class=n>— where RNA / protein / single-cell "
                     "agree or disagree, framed against normal tissue</span></h2>"
                     f"{_hero_svg}</section>")
        except Exception:  # noqa: BLE001 — an aggregate figure must never break the report
            pass

    # --- Flat subskill sections (SINGLE SOURCE for both the left nav AND the render loop below, so
    # they cannot drift). Each present subskill (fan-out order) gets ONE section — NO gate letters,
    # NO 5R bands. This is the "just list the subskills" layout: it also gives target-intrinsic +
    # combinatorial-dependency (gateless, previously section-less) real sections, and removes the
    # band grouping that mis-bucketed the trailing (target-intrinsic / subtype) sections under Safety.
    _present_shorts = [s for s in _SUBSKILL_ORDER if s in sub_results]
    if "subtype_fit" in sub_results and "subtype_fit" not in _present_shorts:
        _present_shorts.append("subtype_fit")   # opt-in tier (only under --subtypes)
    if presence_only:
        _present_shorts = [s for s in _present_shorts if s == "expression"]
    # (short, display label, section anchor) triples — the ordered section list the nav + body share.
    _sections = [(s, _GATE_SHORT_LABEL.get(s, _humanize(s)), _subskill_anchor(s))
                 for s in _present_shorts]

    # --- 2-column shell: sticky left nav (jump-links) + content ---
    # NOTE: the composite-panel SVG is deliberately NOT embedded here — it is a matplotlib
    # text-badge grid sized for a slide (~1583px) that renders poorly in a web card. The
    # scorecard below IS the native-HTML "at a glance". The SVG remains a .md/PPT slide asset.
    # Nav: no "Sections" heading; narrow column (CSS). Subskill links are DERIVED from _sections
    # (the SAME list the body renders), so a new/renamed subskill appears automatically — no drift.
    shell_cls = "shell focused" if presence_only else "shell"
    nav = [f"<div class={shell_cls}><nav class=toc>",
           "<a href='#s-exec'>Executive summary</a>"]
    if presence_only:
        for _s, _lab, _anc in _sections:
            nav.append(f"<a href='#{_anc}'>{_esc(_lab)}</a>")
    else:
        if risk_assessment:
            nav.append("<a href='#s-litrisk'>Literature risk (6-dim)</a>")
        if scorecard:
            nav.append("<a href='#s-evidence'>Evidence summary</a>")
        if deciding_axis and show_deciding_axis:
            nav.append("<a href='#s-deciding'>Deciding axis</a>")
        if ordinal_matrix:
            nav.append("<a href='#s-matrix'>Modality-fit matrix</a>")
        # one flat link per subskill (fan-out order) — no bands, no gate letters.
        # NOTE nav order MUST match the main-page order below.
        nav.append("<span class=h>Subskill evidence</span>")
        for _s, _lab, _anc in _sections:
            nav.append(f"<a href='#{_anc}'>{_esc(_lab)}</a>")
        nav.append("<a href='#s-tension'>Conflicting signals</a>")
        nav.append("<a href='#s-provenance'>Provenance trace</a>")
        nav.append("<a href='#s-about'>About this analysis</a>")
    nav.append("</nav><div class=content>")
    p.append("".join(nav))

    # --- "About this analysis" band + data-loaded status banner — DEFERRED to the BOTTOM (#4).
    # Descriptive framing + provenance is reference material, not a lead; _about_html() is defined
    # here (so it captures the run's counts) and APPENDED at the end of the body. Skipped in
    # presence_only.
    def _about_html() -> list[str]:
        if presence_only:
            return []
        n_gates = len({(r.get("skill_dir") or short) for short, r in sub_results.items()})
        n_cards = sum(1 for r in sub_results.values() for c in (r.get("cards") or [])
                      if isinstance(c, dict) and not c.get("_missing"))
        n_plotly_total = sum(1 for figs in (card_figures or {}).values()
                             for f in figs if f.get("dynamic"))
        fignote = (f" · <span class=n>{n_plotly_total} interactive figure"
                   f"{'s' if n_plotly_total != 1 else ''}</span>" if n_plotly_total else "")
        return [
            f"<div class=statusbar id=s-about>Evaluated {_esc(target)} × {_esc(indication)}"
            f"<span class=n>· {n_gates} subskill{'s' if n_gates != 1 else ''} assessed "
            f"· {n_cards} evidence card{'s' if n_cards != 1 else ''}{fignote}</span></div>",
            "<div class=about><p class=h>About this analysis</p><ul>"
            "<li><b>Target-evaluation profile</b> — one section per question-answering subskill "
            "(presence, selectivity, dependence, mechanism, alteration, tractability, safety, …), "
            "each with its deterministic verdict and evidence cards.</li>"
            "<li>The recommendation is <b>rule-checked</b>: a deterministic rule can override the "
            "AI-generated call (a measured killer forces the verdict); AI sections are tinted + labeled.</li>"
            "<li>Coverage gaps are shown as gaps, never as negatives — “we didn’t look” is "
            "distinct from “we looked and it’s absent.”</li></ul>"
            f"<div class=citation>Framework: <code>{_esc(SKILL_NAME)} v{_esc(SKILL_VERSION)}</code>"
            + (f" · model <code>{_esc(_framework_model_version())}</code>" if _framework_model_version() else "")
            + " · a projection of <code>nomination.json</code>; sub-verdicts are deterministic and "
            "reproducible from the same inputs.</div></div>",
        ]

    # --- Executive summary (LLM) — TOP, the lead the reader needs first ----
    # AI-generated tag moved to the upper-right corner (out of the heading's way) — the exec summary
    # is the one AI section, so its provenance sits as a corner chip rather than a leading banner.
    p.append("<div class='llm llm-exec' id=s-exec><span class='tag tag-corner'>AI-generated</span>"
             f"<h2>Executive summary</h2><p>{_esc(_val('executive_summary'))}</p></div>")

    # --- Literature risk assessment (6 dimensions; CONTEXT-TIER lens) -------
    # The target×indication-level literature read from literature-risk-assessment (risk_assessment.json).
    # Rendered as a visually-separate, explicitly-labeled non-reproducible context block — NOT the
    # deterministic verdict grid (RISK_ASSESSMENT_INTEGRATION.md §4). Suppressed in presence_only.
    if risk_assessment and not presence_only:
        p.extend(_render_literature_risk_html(risk_assessment))

    # --- Subskill sections (FLAT). Iterates _sections (the SAME list the left nav uses — no drift).
    # ONE section per subskill in fan-out order; each renders its own cards as a card-subtab section,
    # with (for the grounded axes) the per-subskill escalate-only literature findings inline. No gate
    # letters, no 5R band headers — the "just list the subskills" layout.
    scorecard_by_short = {r["short"]: r for r in (scorecard or [])}
    # cross-section breadcrumb edges, read from the contract (card_id + reports_into on card-grain
    # facets), computed once + passed to every section. Fails open to the static fallback.
    reports_into_map = _card_reports_into()
    grounded_by_axis = grounded_by_axis or {}
    n_gate_plotly = 0
    # Sections are collected into bands_html (NOT appended to p yet) so the ordered assembly below can
    # place the summary sections (Evidence summary + Modality-fit matrix) ABOVE them.
    bands_html: list[str] = []
    for short, label, sec_id in _sections:
        grounded_html = _grounded_block_html(short, grounded_by_axis.get(short))
        gate_html, n_g = _render_gate_section_html(
            "", label, [short], sub_results, scorecard_by_short,
            card_figures, figures_dir, indication=indication, modality_note=None,
            reports_into_map=reports_into_map,
            sec_id=sec_id, grounded_html=grounded_html)
        bands_html.extend(gate_html)
        n_gate_plotly += n_g
    # presence_only renders the single section directly (early-return below handles the rest).
    if presence_only:
        p.extend(bands_html)

    # FOCUSED VIEW (item 5): presence-only — close out after the Presence section, skipping the
    # scorecard/risk/tension/evidence/matrix. Everything below is the full-report body.
    if presence_only:
        n_plotly = n_gate_plotly
        p.append("<footer>"
                 f"Generated {_esc(datetime.now(timezone.utc).isoformat(timespec='seconds'))}"
                 " · focused Presence view · projection of nomination.json (no recompute).</footer>")
        p.append("</div>")   # close .content (matches the full-report path's single close)
        if n_plotly:
            bundle = _plotly_bundle()
            if bundle:
                p.append(f"<script>{bundle}</script>")
                p.append(_PLOTLY_BOOTSTRAP_JS)
        p.append(_TAB_BOOTSTRAP_JS)
        p.append("</body></html>")
        return "".join(p)

    # --- Evidence summary (deterministic) — a closure emitted near the TOP, one row per SUBSKILL
    # (replaces the old gate-lettered scorecard). Each subskill keeps its own honest 4-state status
    # (a greyed row = coverage gap, never a negative). Iterates _sections so every present subskill
    # appears — including the gateless ones (target-intrinsic, combinatorial-dependency) that carry no
    # scorecard row. anchors_in is the HTML already emitted (so a row only links to a rendered section).
    def _evidence_summary_html(anchors_in: str) -> list[str]:
        if not _sections:
            return []
        out = ["<section id=s-evidence class=scorecard><span class=tag>Computed from the evidence</span>"
               "<h2>Evidence summary <span class=n>— one row per subskill</span></h2>",
               "<p class=sub>Each subskill's deterministic call. "
               "<span class='chip chip-gap'><span class=g>□</span> Not evaluated</span> = a gap, "
               "not a negative. Deciding subskill highlighted.</p>",
               "<table><tr><th>Subskill</th><th>Status</th><th>Finding</th><th>Coverage</th></tr>"]
        for short, label, sec_id in _sections:
            row = scorecard_by_short.get(short) or {}
            glyph, cls, statlab = _HTML_STATUS.get(row.get("status"), _HTML_STATUS["coverage_gap"])
            # verdict: prefer the scorecard row, else the sub-skill's own sub-verdict (gateless shorts).
            verdict = row.get("verdict")
            if not verdict:
                sv = (sub_results.get(short, {}) or {}).get("verdict")
                verdict = sv[0] if (isinstance(sv, (list, tuple)) and sv) else None
            finding = _esc(_humanize(verdict)) if verdict else "<span class=sub>—</span>"
            drv = row.get("driving_rule_id")
            if not drv:
                sv = (sub_results.get(short, {}) or {}).get("verdict")
                if isinstance(sv, (list, tuple)) and len(sv) > 1:
                    drv = sv[1]
            if drv:
                finding += f" <span class=sub><code>{_esc(drv)}</code></span>"
            vtok = (verdict or "")
            if short == "genomic_alteration" and "biomarker_stratified" in vtok:
                finding += " <span class=sub>→ feeds Functional dependence</span>"
            if short == "tractability_sm":
                finding += " <span class=sub>(also confirms Functional dependence)</span>"
            name = _esc(label)
            if f"id={sec_id}" in anchors_in:   # only link if the section actually rendered
                name = (f"<a href='#{sec_id}' style='color:inherit;text-decoration:none;"
                        f"border-bottom:1px dotted var(--line-2)'>{name}</a>")
            if row.get("is_deciding"):
                name += " <span class=badge-deciding>deciding</span>"
            rowcls = " class='deciding'" if row.get("is_deciding") else ""
            cov = row.get("framework_can_evidence")
            out.append(f"<tr{rowcls}><td>{name}</td>"
                       f"<td><span class='chip {cls}'><span class=g>{glyph}</span> {statlab}</span></td>"
                       f"<td>{finding}</td>"
                       f"<td class=sub>{_esc(_COVERAGE_LABEL.get(cov, cov) if cov else '—')}</td></tr>")
        out.append("</table></section>")
        return out

    # --- Deciding axis (deterministic router) — closure; HIDDEN by default (show_deciding_axis).
    def _deciding_html() -> list[str]:
        if not (deciding_axis and show_deciding_axis):
            return []
        out = ["<section id=s-deciding><span class=tag>Deterministic router</span>"
               "<h2>Deciding axis <span class=n>— what the call hinges on</span></h2>",
               f"<div class=banner>{_esc(deciding_axis.get('routing',''))}</div>"]
        if deciding_axis.get("basis") == "abstention_coverage_gaps" and deciding_axis.get("unevidenced_gates"):
            out.append("<p class=sub>Can't decide from framework evidence — questions left unassessed:</p>")
            out.append("<table><tr><th>Axis</th><th>Subskill</th><th>Coverage</th></tr>")
            for g in deciding_axis["unevidenced_gates"]:
                out.append(f"<tr><td>{_esc(g.get('gate'))}</td>"
                           f"<td>{_esc(_GATE_SHORT_LABEL.get(g.get('short'), _humanize(g.get('short'))))}</td>"
                           f"<td class=sub>{_esc(_COVERAGE_LABEL.get(g.get('framework_can_evidence'), g.get('framework_can_evidence')))}</td></tr>")
            out.append("</table>")
        out.append("</section>")
        return out

    # --- Tension analysis (LLM) → "Conflicting signals & trade-offs" — closure.
    def _tension_html() -> list[str]:
        return ["<div class=llm id=s-tension><span class=tag>AI-generated</span>"
                "<h2>Conflicting signals &amp; trade-offs</h2>"
                f"<p>{_esc(_val('tension_analysis'))}</p></div>"]

    n_plotly = n_gate_plotly

    # --- Ordinal matrix heatmap (deterministic VIEW) — closure; the modality-fit summary (#7 → top).
    def _matrix_html() -> list[str]:
        out: list[str] = []
        if ordinal_matrix:
            cols = ordinal_matrix["axes"]["columns"]
            out.append("<section id=s-matrix class=det><span class=tag>Ordering, not a score</span>"
                       "<h2>Modality-fit matrix <span class=n>— strongest signal per (question, "
                       "modality); the verdict, not a cell, is the call</span></h2>")
            col_lbl = {"small_molecule": "Small mol.", "degrader": "Degrader", "adc": "ADC",
                       "bite_tce": "BiTE/TCE", "antibody": "Antibody"}
            out.append("<table class=mtx><tr><th>Question</th>"
                       + "".join(f"<th>{_esc(col_lbl.get(c, c))}</th>" for c in cols) + "<th>Verdict</th></tr>")
            for row in ordinal_matrix["rows"]:
                cells = row["cells"]
                tds = "".join(f"<td class='{_mtx_cell_class(cells[m])}'>{_esc(ordinal_view._cell_glyph(cells[m]))}</td>"
                              for m in cols)
                out.append(f"<tr><td>{_esc(_GATE_SHORT_LABEL.get(row['short'], _humanize(row['short'])))}</td>{tds}"
                           f"<td>{_esc(_humanize(row.get('verdict')))}</td></tr>")
            out.append("</table>")
            out.append(f"<p class=disclaimer>{_esc(ordinal_matrix.get('_disclaimer',''))}</p>")
            if catalogue_rows:
                out.append("<details><summary>Data catalogue — what backed this run</summary>")
                out.append("<table><tr><th>Manifest / source</th><th>Consumed by</th></tr>")
                for cr in catalogue_rows:
                    out.append(f"<tr><td><code>{_esc(cr.get('manifest_id'))}</code></td>"
                               f"<td>{_esc(', '.join(cr.get('consumed_by', [])) or '—')}</td></tr>")
                out.append("</table></details>")
            out.append("</section>")
        elif catalogue_rows:
            out.append("<section class=det><h2>Data catalogue</h2>"
                       "<table><tr><th>Manifest / source</th><th>Consumed by</th></tr>")
            for cr in catalogue_rows:
                out.append(f"<tr><td><code>{_esc(cr.get('manifest_id'))}</code></td>"
                           f"<td>{_esc(', '.join(cr.get('consumed_by', [])) or '—')}</td></tr>")
            out.append("</table></section>")
        return out

    # --- Provenance trace (deterministic) — the full skill run, for audit/reproducibility.
    # A collapsible per-sub-skill trace: which sub-skill ran, its verdict + driving rule, each card
    # it resolved (with the data-source manifest/release it read + a 'missing' flag), and the rule
    # ids that fired. Pure projection of sub_results (skill_dir/cards/_data_source/fired/verdict) —
    # nothing new is computed. Sinks to the bottom (reference material) as a <details>, collapsed.
    def _provenance_trace_html() -> list[str]:
        if presence_only or not sub_results:
            return []
        out = ["<section id=s-provenance class=det><span class=tag>Computed from the evidence</span>"
               "<h2>Provenance trace <span class=n>— the full skill run behind this profile</span></h2>",
               "<p class=sub>Every sub-skill invoked, the evidence cards it resolved (+ the data "
               "source each read), and the rules that fired — the reproducibility spine of "
               "<code>nomination.json</code>. Collapsed by default.</p>",
               "<details><summary>Show run trace "
               f"({len(sub_results)} sub-skills)</summary>"]
        for short, r in sub_results.items():
            skill_dir = r.get("skill_dir") or "(inline)"
            v = r.get("verdict")
            verdict_str = _humanize(v[0]) if v else "not evaluated"
            driving = (v[1] if (v and len(v) > 1) else None)
            cards = r.get("cards") or []
            fired = r.get("fired") or []
            n_missing = sum(1 for c in cards if c.get("_missing"))
            out.append(f"<div class=trace-skill><p class=trace-h><b>{_esc(short)}</b> "
                       f"<span class=sub>{_esc(skill_dir)}</span> → {_esc(verdict_str)}"
                       + (f" <span class=sub><code>{_esc(driving)}</code></span>" if driving else "")
                       + f" <span class=sub>· {len(cards)} card{'s' if len(cards) != 1 else ''}"
                       + (f", {n_missing} missing" if n_missing else "")
                       + f", {len(fired)} rule{'s' if len(fired) != 1 else ''} fired</span></p>")
            if cards:
                out.append("<table class=trace-cards><tr><th>Card</th><th>Data source</th>"
                           "<th>Rules fired</th></tr>")
                for c in cards:
                    cid = c.get("card_id") or "?"
                    summ = c.get("summary") or {}
                    dsrc = summ.get("_data_source") or ("— (missing)" if c.get("_missing") else "—")
                    s3 = summ.get("_data_s3_uri") or ""
                    src_cell = (f"<span title='{_esc(str(s3))}'><code>{_esc(str(dsrc))}</code></span>"
                                if s3 else f"<code>{_esc(str(dsrc))}</code>")
                    card_rules = [fr.get("rule_id") for fr in fired if fr.get("card_id") == cid]
                    rules_cell = (", ".join(f"<code>{_esc(rid)}</code>" for rid in card_rules)
                                  if card_rules else "<span class=sub>—</span>")
                    miss = " class=trace-missing" if c.get("_missing") else ""
                    out.append(f"<tr{miss}><td><code>{_esc(cid)}</code></td>"
                               f"<td>{src_cell}</td><td>{rules_cell}</td></tr>")
                out.append("</table>")
            out.append("</div>")
        out.append("</details></section>")
        return out

    # === ORDERED ASSEMBLY: summaries lead, then the flat subskill sections, conflicting signals,
    # About last. Exec + Literature-risk are already in `p` (rendered right after the exec summary).
    # Now: Evidence summary → Modality-fit matrix → deciding-axis → [subskill sections] →
    #   Conflicting signals → About (bottom). Nav order (built above) mirrors this exactly.
    p.extend(_evidence_summary_html("".join(p) + "".join(bands_html)))  # link rows to rendered sections
    p.extend(_matrix_html())
    p.extend(_deciding_html())
    p.extend(bands_html)
    p.extend(_tension_html())
    p.extend(_provenance_trace_html())
    p.extend(_about_html())

    kind = "Interactive" if n_plotly else "Static"
    p.append("<footer>"
             f"Generated {_esc(datetime.now(timezone.utc).isoformat(timespec='seconds'))}"
             + (f" · lenses <code>{_esc(invoked_lenses)}</code>" if invoked_lenses else "")
             + f"<br>{kind} self-contained governance artifact — a projection of nomination.json. "
             + ("Charts are pre-computed by the methods (drawn from the same series as the static "
                "figures) and embedded, not re-plotted here. " if n_plotly else "")
             + "AI-generated sections are tinted; all other sections are deterministic and "
             "reproducible from the same inputs. No content is recomputed at render time.</footer>")
    p.append("</div>")   # close .wrap

    # --- Interactive layer (Phase B): inline plotly.js + a small vanilla-JS bootstrap that draws
    # every embedded spec. Emitted ONLY when ≥1 figure was produced — the no-figure report stays
    # pure static HTML (no JS, no 4.6 MB payload). Self-contained: plotly.js is INLINED, never a CDN.
    if n_plotly:
        bundle = _plotly_bundle()
        if bundle:
            p.append(f"<script>{bundle}</script>")
            p.append(_PLOTLY_BOOTSTRAP_JS)
    # Tab bootstrap whenever a gate section (with subtabs) was rendered — independent of Plotly, so
    # the tabs work even on a static/no-figure run. Presence gate is the current trigger.
    if "expression" in sub_results:
        p.append(_TAB_BOOTSTRAP_JS)
    p.append("</body></html>")
    return "".join(p)


__all__ = [
    '_ACTION_GLOSS',
    '_BAND_LABEL',
    '_CARD_FIGURE_ORDER',
    '_CARD_KEYFACTS',
    '_CARD_REPORTS_INTO_FALLBACK',
    '_CARD_TITLE',
    '_CARD_V2_ROLE',
    '_COVERAGE_LABEL',
    '_GATE_SHORT_LABEL',
    '_HTML_CSS',
    '_HTML_STATUS',
    '_INDICATION_LINEAGE',
    '_PLOTLY_BOOTSTRAP_JS',
    '_RISK_CATEGORY_LABEL',
    '_RISK_CATEGORY_ORDER',
    '_SHORT_TO_GATE_ANCHOR',
    '_SIG_CLASS',
    '_TAB_BOOTSTRAP_JS',
    '_V2_ROLE_BADGE',
    '_VERDICT_LABEL',
    '_card_fired_rules',
    '_card_key_facts',
    '_card_plot_divs',
    '_card_reports_into',
    '_esc',
    '_expression_indication_focus',
    '_fmt_fact_value',
    '_humanize',
    '_inline_svg',
    '_mtx_cell_class',
    '_plotly_bundle',
    '_prettify_field',
    '_read_card_plotly_specs',
    '_render_card_data_html',
    '_render_gate_section_html',
    '_render_target_profile_html',
    '_risk_category_rollup',
]
