"""question_table_core — shared helpers for the per-question signal/confidence tables.

The presence / selectivity / dependency question-table builders each assembled a per-question
table from three byte-identical helpers (card lookup, confidence cell, row shape) plus a
confidence dots-map. Extracted here so the builders import one copy instead of re-declaring it.

Verdict-INERT: these shape the DISPLAY table (the leading per-question signal/confidence read),
never a rule, resolver, or gate. Each skill still declares its own `_sig` / `_SIG_META` (whose
tier vocab and polarity genuinely differ per skill); only the generic pieces live here.
"""
from __future__ import annotations

# Union of the per-skill confidence dots-maps. `.get(tier, 0)` is safe for every caller: a skill
# that never emits `standard` / `unknown` is unaffected by their presence, and the dependency
# table (which does use `standard`) gets its superset. Kept as one map so the tiers stay consistent.
CONF_DOTS = {"high": 3, "moderate": 2, "low": 1, "standard": 2, "unknown": 0, "unmeasured": 0}


def cbyid(cards):
    """{card_id: summary_dict} — tolerant of None cards / missing card_id / missing summary."""
    return {c.get("card_id"): (c.get("summary") or {}) for c in (cards or [])}


def conf(tier: str, label: str = "") -> dict:
    """A confidence cell: the tier, its ordinal dots, and a display label (defaults to the tier)."""
    return {"tier": tier, "dots": CONF_DOTS.get(tier, 0), "label": label or tier}


def row(qid, question, primary, support, signal, confidence):
    """One question-table row in the shared shape."""
    return {"id": qid, "question": question, "primary": primary, "support": support,
            "signal": signal, "confidence": confidence}
