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
# faceted-rollup blocks (PR2): the signals-first spine, one level up + the embedded sub-skill view.
SIGNALS_SCATTER = "signals_scatter"    # signal × confidence scatter — report-level (skills) OR per-skill (sub-groups)
SUBGROUP_BANDS = "subgroup_bands"      # per-skill hierarchy sub-group signal/confidence bands (embedded view)
CROSS_CUTTING_QUESTIONS = "cross_cutting_questions"  # questions one skill measures that inform another lens
SYNTHESIS_BANNER = "synthesis_banner"  # persistent advisory exec-summary banner (report chrome, above tabs)
SYNTHESIS_NOTE = "synthesis_note"      # a routed LLM argument/tension surfaced inside its topical lens
# evidence-graph blocks (P3): the RICH embedded sub-skill view, rendered from the carried
# `skill_report.evidence_graph` (== the standalone dashboard) — supersedes the lean bands/scatter when a
# graph is present. See docs/COMPOSED_EVIDENCE_GRAPH_ROLLUP.md §4.
EVIDENCE_FINGERPRINT = "evidence_fingerprint"  # per-question heatmap: cards × signal/confidence + a literature dot
CARD_CHAIN = "card_chain"              # per-card dataset→data→rule→verdict chains, grouped by measurement layer
LITERATURE_AXES = "literature_axes"    # per-axis literature agreement + assertion + citations + blind spots
# composed at-a-glance block (P6 consumer): the COMPOSED analog of EVIDENCE_FINGERPRINT — reads the
# target_report.evidence_graph INDEX (verdict node + skills[] + typed edges, composed_evidence_graph.v1)
# and renders the whole decision as a lens-grouped skill grid. Leads the Decision lens. See
# docs/COMPOSED_EVIDENCE_GRAPH_ROLLUP.md §2 (the composed index) — this is its first renderer.
COMPOSED_FINGERPRINT = "composed_fingerprint"  # composed skill×lens grid + verdict + dissent, from the index

BLOCK_KINDS: frozenset = frozenset({
    REPORT_HEADER, SKILL_HEADER, CONFIDENCE, TENSION, CLAIM_CHIPS, QUESTION_TABLE,
    PHASE_METRICS, FIGURE, PROVENANCE, UNMEASURED, ABOUT, SIGNALS_OVERVIEW, RISK_6DIM,
    SYNTHESIS, COHERENCE, MODALITY_MATRIX, LITERATURE_RISK, DECIDING_AXIS,
    FLIP_CONDITIONS, SUBTYPE, BIOMARKER,
    SIGNALS_SCATTER, SUBGROUP_BANDS, CROSS_CUTTING_QUESTIONS, SYNTHESIS_BANNER, SYNTHESIS_NOTE,
    EVIDENCE_FINGERPRINT, CARD_CHAIN, LITERATURE_AXES, COMPOSED_FINGERPRINT,
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
    SYNTHESIS_BANNER: 0,       # the persistent advisory banner leads the report chrome
    SIGNALS_SCATTER: 0,        # the signal×confidence scatter leads the Signals lens
    SYNTHESIS_NOTE: 1,         # routed LLM notes appear from summary depth up
    SUBGROUP_BANDS: 2,         # per-skill sub-group bands — evidence depth
    CROSS_CUTTING_QUESTIONS: 2,  # evidence depth
    EVIDENCE_FINGERPRINT: 2,   # per-question fingerprint — leads the RICH embedded view (evidence depth)
    LITERATURE_AXES: 2,        # per-axis literature panel — evidence depth
    CARD_CHAIN: 3,             # per-card dataset→data→rule→verdict chains — deepest detail
    COMPOSED_FINGERPRINT: 1,   # composed at-a-glance grid — summary depth (leads the Decision lens)
}

# how many claim chips to show per skill at each level (None = all).
CHIP_LIMIT_BY_LEVEL: dict[int, Optional[int]] = {0: 0, 1: 3, 2: None, 3: None}


# ---------------------------------------------------------------------------------------------------
# Lenses — the FACETED presentation grouping of the COMPOSED report. Each lens is one of the
# target_report projection axes (docs/UNIFIED_OUTPUT_CONTRACT.md "projections of the same skill_report[]
# signals along orthogonal axes") made navigable: the reader toggles co-equal, full-width views.
# The lens is a PRESENTATION grouping only — it re-buckets the SAME overview blocks + per-skill sections
# the builder already produced; it never changes what content is selected (that stays level/scope/lead).
# HTML renders lenses as a tab bar; text/markdown/pptx linearize them as sequential sections in
# LENS_ORDER; json exposes a `lenses[]` grouping array. A block/section with lens=None is report chrome
# (the REPORT_HEADER + ABOUT) or the standalone single-skill path — NOT bucketed into any lens, so an
# un-annotated IR (build_ir_for_skill) groups to nothing and backends fall back to the flat layout.
# ---------------------------------------------------------------------------------------------------
LENS_DECISION = "decision"     # the nomination call: recommendation rationale, deciding axis, flips
LENS_SIGNALS = "signals"       # the per-skill evidence landscape (signals overview + the skill sections)
LENS_MODALITY = "modality"     # how would we drug it — the per-channel modality-fit readout
LENS_RISK = "risk"             # what could kill it — the 6-dim risk rollup + literature-risk context
LENS_BIOLOGY = "biology"       # what is the biology — coherence, biomarker, subtype stratification

# canonical lens order — the single linearization the non-interactive backends emit sections in.
LENS_ORDER: tuple = (LENS_DECISION, LENS_SIGNALS, LENS_MODALITY, LENS_RISK, LENS_BIOLOGY)
LENS_TITLE: dict[str, str] = {
    LENS_DECISION: "Decision", LENS_SIGNALS: "Signals", LENS_MODALITY: "Modality",
    LENS_RISK: "Risk", LENS_BIOLOGY: "Biology",
}

# report-level (overview) block kind → lens. Per-skill SECTIONS are stamped LENS_SIGNALS by the builder
# (not here — a section is not a block kind). REPORT_HEADER + ABOUT are intentionally ABSENT (chrome,
# lens=None). A block kind absent from this map is un-lensed and renders in the flat fallback path.
BLOCK_LENS: dict[str, str] = {
    SIGNALS_OVERVIEW: LENS_SIGNALS,
    SIGNALS_SCATTER: LENS_SIGNALS,            # the report-level 15-skill scatter
    CROSS_CUTTING_QUESTIONS: LENS_SIGNALS,
    COMPOSED_FINGERPRINT: LENS_DECISION,     # the composed at-a-glance grid leads the Decision lens
    SYNTHESIS: LENS_DECISION,
    DECIDING_AXIS: LENS_DECISION,
    FLIP_CONDITIONS: LENS_DECISION,
    MODALITY_MATRIX: LENS_MODALITY,
    RISK_6DIM: LENS_RISK,
    LITERATURE_RISK: LENS_RISK,
    COHERENCE: LENS_BIOLOGY,
    BIOMARKER: LENS_BIOLOGY,
    SUBTYPE: LENS_BIOLOGY,
    # SYNTHESIS_BANNER is chrome (rendered above the tabs, ReportIR.banner) — intentionally absent.
    # SYNTHESIS_NOTE is pre-lensed by the router (build_ir preserves an already-set lens) — absent here.
    # SUBGROUP_BANDS is section-only (emitted inside a per-skill section) — absent here.
}

# skill short → the TOPICAL lens its LLM synthesis sentences route to (distinct from section placement:
# all 15 per-skill sections live in the Signals lens; only NARRATED argument/tension sentences route
# by topic). A sentence whose citation anchors resolve to a skill lands in that skill's topical lens;
# an unresolved / cross-cutting sentence falls back to the Decision lens (see ir._route_synthesis_to_lenses).
SKILL_TOPICAL_LENS: dict[str, str] = {
    "expression": LENS_SIGNALS, "selectivity": LENS_SIGNALS, "dependency": LENS_SIGNALS,
    "surface_modality": LENS_MODALITY, "tractability_sm": LENS_MODALITY, "immune_context": LENS_MODALITY,
    "safety": LENS_RISK, "literature_context": LENS_RISK,
    "mechanism": LENS_BIOLOGY, "genomic_alteration": LENS_BIOLOGY, "differentiation": LENS_BIOLOGY,
    "cis_coherence": LENS_BIOLOGY, "target_intrinsic": LENS_BIOLOGY,
    "combination_vulnerability": LENS_BIOLOGY, "translational_readiness": LENS_BIOLOGY,
}


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
    "LENS_DECISION", "LENS_SIGNALS", "LENS_MODALITY", "LENS_RISK", "LENS_BIOLOGY",
    "LENS_ORDER", "LENS_TITLE", "BLOCK_LENS", "SKILL_TOPICAL_LENS",
    "SIGNALS_SCATTER", "SUBGROUP_BANDS", "CROSS_CUTTING_QUESTIONS", "SYNTHESIS_BANNER", "SYNTHESIS_NOTE",
    "EVIDENCE_FINGERPRINT", "CARD_CHAIN", "LITERATURE_AXES", "COMPOSED_FINGERPRINT",
    "REPORT_HEADER", "SKILL_HEADER", "CONFIDENCE", "TENSION", "CLAIM_CHIPS", "QUESTION_TABLE",
    "PHASE_METRICS", "FIGURE", "PROVENANCE", "UNMEASURED", "ABOUT",
    "SIGNALS_OVERVIEW", "RISK_6DIM", "SYNTHESIS", "COHERENCE", "MODALITY_MATRIX",
    "LITERATURE_RISK", "DECIDING_AXIS", "FLIP_CONDITIONS", "SUBTYPE", "BIOMARKER",
    "polarity_glyph", "polarity_label", "polarity_rank", "polarity_legend", "ordinal_glyph_legend",
    "figure_status", "humanize_figure_type",
]
