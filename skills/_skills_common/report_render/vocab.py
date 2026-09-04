"""Shared display vocabulary for the renderer — the SINGLE source for skill labels, ordering, the
slot→tier map, and polarity glyphs. Polarity glyphs/ranks are drawn from `_skills_common.ordinal_view`
(the framework's one order-preserving signal scale) so the renderer NEVER invents a second vocabulary
(the divergence the old render-evidence-package / example-gallery icon maps introduced).
"""
from __future__ import annotations

from typing import Optional

from ..ordinal_view import ordinal_of, scale_legend  # single-source polarity scale

# ---------------------------------------------------------------------------------------------------
# Skills — canonical short → human title, and the canonical fan-out order (matches tp_fanout.SUB_SKILLS).
# A short absent here is NOT an error: the renderer falls back to a titleized short (fail-soft), so a
# newly-wired skill renders sanely before this map is updated.
# ---------------------------------------------------------------------------------------------------
SKILL_DISPLAY: dict[str, str] = {
    "expression": "Tumor presence",
    "selectivity": "Tumor selectivity",
    "dependency": "Functional dependency",
    "mechanism": "Mechanism & pharmacology",
    "genomic_alteration": "Genomic alteration",
    "differentiation": "Differentiation landscape",
    "tractability_sm": "Small-molecule tractability",
    "surface_modality": "Surface / modality fit",
    "immune_context": "Immune context",
    "safety": "On-target safety",
    "target_intrinsic": "Target-intrinsic dossier",
    "cis_coherence": "Cis-feature coherence",
    "combination_vulnerability": "Combination & vulnerability",
    "translational_readiness": "Translational readiness",
    "literature_context": "Literature context",
}

# Canonical order (SUB_SKILLS order). Used as the stable within-role tiebreak so output is deterministic.
SKILL_ORDER: tuple = (
    "expression", "selectivity", "dependency", "mechanism", "genomic_alteration",
    "differentiation", "tractability_sm", "surface_modality", "immune_context", "safety",
    "target_intrinsic", "cis_coherence", "combination_vulnerability",
    "translational_readiness", "literature_context",
)

# The 8 gating shorts (mirror of tp_fanout._SHORT_TO_GATE keys). Role in the spine is authoritative
# (skill_report.role); this is only the fallback when a report omits role.
GATING_SHORTS: frozenset = frozenset({
    "selectivity", "dependency", "mechanism", "genomic_alteration",
    "differentiation", "tractability_sm", "surface_modality", "safety",
})

# role → sort rank (gating leads, then descriptive context, then inert).
ROLE_RANK: dict[str, int] = {"gating": 0, "descriptive": 1, "inert": 2}


# full skill DIR name (as written in a standalone decision.json's `skill` field) → fan-out short.
# Mirror of tp_fanout.SUB_SKILLS. Lets a standalone-skill renderer resolve a nice title/role from the
# `decision["skill"]` value (the `short` is NOT present in a standalone artifact).
SKILL_NAME_TO_SHORT: dict[str, str] = {
    "tumor-presence": "expression",
    "tumor-selectivity": "selectivity",
    "functional-requirement": "dependency",
    "mechanism-and-pharmacology": "mechanism",
    "genomic-alteration-profile": "genomic_alteration",
    "differentiation-landscape": "differentiation",
    "tractability-small-molecule": "tractability_sm",
    "surface-modality-fit": "surface_modality",
    "immune-context": "immune_context",
    "on-target-safety-liability": "safety",
    "target-intrinsic": "target_intrinsic",
    "cis-feature-coherence": "cis_coherence",
    "combination-and-vulnerability": "combination_vulnerability",
    "translational-readiness": "translational_readiness",
    "literature-context": "literature_context",
}


def skill_short_for_name(name) -> Optional[str]:
    """Map a full skill dir name (decision.json `skill`) → fan-out short, or None if unknown."""
    return SKILL_NAME_TO_SHORT.get(name) if isinstance(name, str) else None


def skill_title(short: str) -> str:
    """Human label for a skill short; fail-soft titleization for an unmapped short."""
    return SKILL_DISPLAY.get(short) or short.replace("_", " ").replace("-", " ").capitalize()


def skill_order_index(short: str) -> int:
    try:
        return SKILL_ORDER.index(short)
    except ValueError:
        return len(SKILL_ORDER)  # unknown skills sort last, stably


# ---------------------------------------------------------------------------------------------------
# Slot → detail tier. The min level int at which a block kind appears (L0=0 … L3=3). Cumulative.
# This map is the depth dial's ONLY definition — the builder reads it, backends never do.
# ---------------------------------------------------------------------------------------------------
# block kinds (closed vocabulary — every backend must handle exactly this set; enforced by the
# backend-coverage test).
REPORT_HEADER = "report_header"   # the target-level decision (recommendation / confidence / dissent)
SKILL_HEADER = "skill_header"     # per-skill: title + call + polarity + honest_phrase
CONFIDENCE = "confidence"         # confidence {level, basis, coverage}
TENSION = "tension"               # top_tension {text, source, severity}
CLAIM_CHIPS = "claim_chips"       # the reader-facing claim chips (limited at L1, full at L2+)
QUESTION_TABLE = "question_table" # the Q&A / signal rows
PHASE_METRICS = "phase_metrics"   # per-phase traceable numbers
FIGURE = "figure"                 # a figure reference (+ caption + text fallback)
PROVENANCE = "provenance"         # driving/fired rules + cards used/missing
UNMEASURED = "unmeasured"         # fail-soft placeholder: an expected slot was empty (coverage, honest)
ABOUT = "about"                   # the honesty legend / disclaimer
# report-level overview blocks (absorbed from the tp_dashboard v2 design, spine-sourced):
SIGNALS_OVERVIEW = "signals_overview"  # one row per scored skill: diverging signal strip (the lead)
RISK_6DIM = "risk_6dim"                # the 6-category deterministic risk rollup (tiles)
# parity blocks (bring report_render to content-parity with the legacy target_profile.html/.md):
SYNTHESIS = "synthesis"                # LLM narrative (executive summary / tensions / arguments)
COHERENCE = "coherence"                # target thesis + cross-axis coherence
MODALITY_MATRIX = "modality_matrix"    # gate × modality ordinal evidence matrix
LITERATURE_RISK = "literature_risk"    # literature-derived risk-by-dimension (context, never a gate)
DECIDING_AXIS = "deciding_axis"        # what the call hinges on (router basis)
# decision-critical detail blocks (surface buried spine content the summary previously dropped):
FLIP_CONDITIONS = "flip_conditions"    # "what would change the call" — recommendation-flipping counterfactuals
SUBTYPE = "subtype"                    # molecular-subtype stratification (MSI/MSS, CMS, …) convergence
BIOMARKER = "biomarker"                # patient-selection biomarker: stratification class + preferred assay

BLOCK_KINDS: frozenset = frozenset({
    REPORT_HEADER, SKILL_HEADER, CONFIDENCE, TENSION, CLAIM_CHIPS, QUESTION_TABLE,
    PHASE_METRICS, FIGURE, PROVENANCE, UNMEASURED, ABOUT, SIGNALS_OVERVIEW, RISK_6DIM,
    SYNTHESIS, COHERENCE, MODALITY_MATRIX, LITERATURE_RISK, DECIDING_AXIS,
    FLIP_CONDITIONS, SUBTYPE, BIOMARKER,
})

# min level int at which each block kind is shown.
TIER: dict[str, int] = {
    REPORT_HEADER: 0,
    SIGNALS_OVERVIEW: 0,   # the lead — a one-glance read across all scored skills
    RISK_6DIM: 1,          # governance risk rollup — summary depth up
    SYNTHESIS: 1,          # LLM narrative — summary depth up (suppressed by --no-synthesis upstream)
    COHERENCE: 1,
    DECIDING_AXIS: 1,
    FLIP_CONDITIONS: 1,    # "what would change the call" — belongs with the decision framing (summary depth)
    MODALITY_MATRIX: 2,    # evidence depth
    LITERATURE_RISK: 2,
    SUBTYPE: 2,            # subtype stratification — evidence depth
    BIOMARKER: 2,          # patient-selection biomarker — evidence depth
    SKILL_HEADER: 0,
    ABOUT: 1,
    CONFIDENCE: 1,
    TENSION: 1,
    CLAIM_CHIPS: 1,
    QUESTION_TABLE: 2,
    PHASE_METRICS: 2,
    FIGURE: 2,
    PROVENANCE: 3,
    UNMEASURED: 0,   # a fail-soft substitute; the builder decides when to emit it (not tier-gated)
}

# how many claim chips to show per skill at each level (None = all).
CHIP_LIMIT_BY_LEVEL: dict[int, Optional[int]] = {0: 0, 1: 3, 2: None, 3: None}


# ---------------------------------------------------------------------------------------------------
# Polarity — the ONE display scale (from ordinal_view). `not_scored` (descriptive/inert) and unknown
# values are off-scale context, never a fabricated rank.
# ---------------------------------------------------------------------------------------------------
_POLARITY_GLYPH: dict[str, str] = {
    "killer": "⛔", "opposing": "▽", "neutral": "•", "supportive": "△",
    "insufficient": "◌", "not_applicable": "◌", "not_scored": "·",
}
_POLARITY_LABEL: dict[str, str] = {
    "killer": "killer", "opposing": "opposing", "neutral": "neutral", "supportive": "supportive",
    "insufficient": "insufficient (coverage gap)", "not_applicable": "not applicable",
    "not_scored": "not scored (context)",
}


def polarity_glyph(polarity: Optional[str]) -> str:
    return _POLARITY_GLYPH.get(polarity or "", "·")


def polarity_label(polarity: Optional[str]) -> str:
    return _POLARITY_LABEL.get(polarity or "", polarity or "—")


def polarity_rank(polarity: Optional[str]) -> Optional[int]:
    """Order-preserving rank for within-role sorting (killer −3 … supportive +2); off-scale → None
    (sorts last, NOT as worst — an absence of measurement is not a low score)."""
    return ordinal_of(polarity)


def polarity_legend() -> dict:
    """The polarity scale + honesty disclaimer, for the ABOUT block."""
    return scale_legend()


def ordinal_glyph_legend() -> str:
    """One-line inline legend for the modality-matrix cell glyphs (signed ordinals + off-scale markers)
    — so a reader decodes `+2 / −1 / ·` in place instead of hunting for a separate key."""
    leg = scale_legend()
    on = ", ".join(f"{v:+d} {k}" for k, v in sorted((leg.get("on_scale") or {}).items(),
                                                     key=lambda t: -t[1]))
    off = ", ".join(leg.get("off_scale") or [])
    return (f"Cells are an order-preserving ordinal (NOT a metric): {on}. "
            f"Off-scale (coverage gap, not a low score): {off} (shown insf/n/a); "
            f"· = the gate emits no signal on that modality.")


# ---------------------------------------------------------------------------------------------------
# Figure verdict badge — the "status beside the figure" the figure-emitter redesign (2026-09-03) moved
# OFF the figure and onto the composing layer (see target-contracts plot_styles/takeda_palette
# status_for_card / verdict_badge; FIGURE_STYLE_GUIDE §"The VERDICT does NOT appear on the figure").
# report_render is spine-sourced, so the badge is derived from the SAME `skill_report.polarity` the
# signals-overview strip reads — figure status and written verdict are one fact and cannot drift, with
# NO cross-repo import of takeda_palette. The signal vocabulary + short UPPERCASE label mirror
# VERDICT_STATUS; `signal` is a CSS-class-safe token backends colour with the reserved-status palette.
# A descriptive/inert card (or off-scale/None polarity) is an honest "context" no-call, never a grey
# killer. (Per-CARD badges — a figure showing its own card's fired-rule signal rather than the parent
# skill's — need the nomination spine to carry per-card fired-rule dicts; that is an upstream change.)
_FIGURE_STATUS: dict[str, tuple] = {          # polarity → (signal token, label, icon)
    "supportive":     ("supportive", "SUPPORTS", "△"),
    "neutral":        ("neutral", "NEUTRAL", "•"),
    "opposing":       ("opposing", "AGAINST", "▽"),
    "killer":         ("killer", "KILLER", "⛔"),
    "insufficient":   ("insufficient", "INSUFFICIENT", "◌"),
    "not_applicable": ("not_applicable", "N/A", "◌"),
}
_FIGURE_STATUS_CONTEXT = ("context", "CONTEXT", "◇")


def figure_status(polarity: Optional[str], role: Optional[str] = None) -> dict:
    """One card figure's verdict badge, derived from its section's spine polarity. Returns
    {signal, label, icon}. Off-scale / descriptive / inert / unknown → the `context` no-call."""
    if role in ("descriptive", "inert") or polarity in (None, "not_scored"):
        sig, label, icon = _FIGURE_STATUS_CONTEXT
    else:
        sig, label, icon = _FIGURE_STATUS.get(polarity, _FIGURE_STATUS_CONTEXT)
    return {"signal": sig, "label": label, "icon": icon}


def humanize_figure_type(fig_type: Optional[str], fallback: Optional[str] = None) -> str:
    """A card figure descriptor carries a machine `type`/`id` (e.g. 'density_histogram_with_kde'), not a
    prose caption — humanize it into a readable caption (fallback → id → 'figure')."""
    for cand in (fig_type, fallback):
        if cand:
            return str(cand).replace("_", " ").strip().capitalize()
    return "figure"


__all__ = [
    "SKILL_DISPLAY", "SKILL_ORDER", "GATING_SHORTS", "ROLE_RANK", "SKILL_NAME_TO_SHORT",
    "skill_title", "skill_order_index", "skill_short_for_name",
    "BLOCK_KINDS", "TIER", "CHIP_LIMIT_BY_LEVEL",
    "REPORT_HEADER", "SKILL_HEADER", "CONFIDENCE", "TENSION", "CLAIM_CHIPS", "QUESTION_TABLE",
    "PHASE_METRICS", "FIGURE", "PROVENANCE", "UNMEASURED", "ABOUT",
    "SIGNALS_OVERVIEW", "RISK_6DIM", "SYNTHESIS", "COHERENCE", "MODALITY_MATRIX",
    "LITERATURE_RISK", "DECIDING_AXIS", "FLIP_CONDITIONS", "SUBTYPE", "BIOMARKER",
    "polarity_glyph", "polarity_label", "polarity_rank", "polarity_legend", "ordinal_glyph_legend",
    "figure_status", "humanize_figure_type",
]
