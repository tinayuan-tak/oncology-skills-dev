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


def skill_title(short: str) -> str:
    """Human label for a skill short; fail-soft titleization for an unmapped short."""
    return SKILL_DISPLAY.get(short) or short.replace("_", " ").capitalize()


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

BLOCK_KINDS: frozenset = frozenset({
    REPORT_HEADER, SKILL_HEADER, CONFIDENCE, TENSION, CLAIM_CHIPS, QUESTION_TABLE,
    PHASE_METRICS, FIGURE, PROVENANCE, UNMEASURED, ABOUT,
})

# min level int at which each block kind is shown.
TIER: dict[str, int] = {
    REPORT_HEADER: 0,
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


__all__ = [
    "SKILL_DISPLAY", "SKILL_ORDER", "GATING_SHORTS", "ROLE_RANK",
    "skill_title", "skill_order_index",
    "BLOCK_KINDS", "TIER", "CHIP_LIMIT_BY_LEVEL",
    "REPORT_HEADER", "SKILL_HEADER", "CONFIDENCE", "TENSION", "CLAIM_CHIPS", "QUESTION_TABLE",
    "PHASE_METRICS", "FIGURE", "PROVENANCE", "UNMEASURED", "ABOUT",
    "polarity_glyph", "polarity_label", "polarity_rank", "polarity_legend",
]
