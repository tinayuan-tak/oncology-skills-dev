"""Single source of truth for classifying a Go/No-Go recommendation string.

Two independent code paths used to classify the recommendation into a badge
color: the integrated-report context builder (`context._build_recommendation_context`)
and the PDF title-slide/summary renderers (`generate_target_report_pdf`). They
DISAGREED on the compound verdict ``CONDITIONAL NO-GO`` — the context builder
correctly treated it as a NO-GO (red), while the PDF used
``is_conditional = 'CONDITIONAL' in rec and not is_go`` and painted it AMBER
("caution"). A rejected target therefore rendered as amber on the committee
title slide. Both now call this one function, so the classification can never
diverge again.

Precedence (most-restrictive first): NO-GO > CONDITIONAL > GO. This means
``CONDITIONAL NO-GO`` is a ``no_go`` — the substring ``NO-GO`` wins, exactly
as the (correct) context builder always did.
"""
from __future__ import annotations

# The four decision kinds, most- to least-restrictive.
RECOMMENDATION_KINDS = ("no_go", "conditional", "go", "unknown")

# Semantic badge-color name per kind (callers map these to their own palette
# constants — e.g. the PDF maps 'RED' -> COLORS['TAKEDA_RED'] on one slide and
# COLORS['RED'] on another).
BADGE_COLOR = {
    "no_go": "RED",
    "conditional": "AMBER",
    "go": "GREEN",
    "unknown": "GRAY",
}


def classify_recommendation(rec: str | None) -> str:
    """Return the decision kind for a recommendation string.

    NO-GO takes precedence (so ``CONDITIONAL NO-GO`` is ``no_go``), then
    CONDITIONAL, then GO. Empty / ``TBD`` / anything unrecognized is
    ``unknown``. Case-insensitive; tolerant of priority qualifiers such as
    ``GO - HIGH PRIORITY``.
    """
    rec_upper = (rec or "").upper()
    if "NO-GO" in rec_upper:
        return "no_go"
    if "CONDITIONAL" in rec_upper:
        return "conditional"
    if "GO" in rec_upper:
        return "go"
    return "unknown"


def badge_color_for(rec: str | None) -> str:
    """Semantic badge-color name ('RED' / 'AMBER' / 'GREEN' / 'GRAY')."""
    return BADGE_COLOR[classify_recommendation(rec)]
