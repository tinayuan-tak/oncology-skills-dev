"""Shared signals-first helpers for the fleet rollout (mirrors the tumor-presence pilot).

Two verdict-INERT primitives used by the per-lens narrators (synthesis_*.py) and the per-skill
strength_certainty sidecars, so every lens can LEAD with its signal vector and expose a continuous
portfolio-ranking scalar — without each skill re-implementing them:

  render_signal_vector(cv, axis_labels) — render a claim_vector dict as a leading prompt block.
  certainty_composite(strength, level)  — a monotone [0,1] certainty-discounted-strength ranking scalar.

Generic over any lens's claim_vector (top-level axis keys → {signal, corroboration, evidence, conflict})
and over the fleet's strength vocabularies. Never touches any verdict.
"""
from __future__ import annotations
from typing import Optional


def render_signal_vector(cv: Optional[dict], axis_labels: Optional[dict] = None) -> str:
    """One line per claim-vector axis: signal × corroboration + cited evidence, conflict flagged.
    Skips private/metadata keys and any entry that is not a claim (no `signal`). A no-op note when the
    decision predates the claim vector (so the narration degrades to the fields below)."""
    if not isinstance(cv, dict):
        return "  (signal vector not present in this decision — narrate from the fields below.)"
    labels = axis_labels or {}
    rows = []
    for k, cl in cv.items():
        if k.startswith("_") or not isinstance(cl, dict) or "signal" not in cl:
            continue
        name = labels.get(k, "")
        line = (f"    {k} {name}: signal={cl.get('signal')} corroboration={cl.get('corroboration')} "
                f"— {cl.get('evidence')}")
        if cl.get("conflict"):
            line += f"  CONFLICT: {cl['conflict']}"
        rows.append(line)
    return "\n".join(rows) if rows else "  (signal vector empty for this run)"


# Robust across the fleet's strength vocabularies (presence: *_positive; dependency: +broad_nonselective;
# selectivity / surface / genomic / tractability variants). Unknown tier → 0.0 (conservative).
_COMPOSITE_STRENGTH = {
    "strong_positive": 1.0, "moderate_positive": 0.66, "weak_positive": 0.33,
    "broad_nonselective": 1.0,               # a genuine (broad) dependency — strong signal, selectivity is a separate axis
    "negative": 0.0, "none": 0.0, "unmeasured": 0.0,
}
_COMPOSITE_CERTAINTY = {"high": 1.0, "medium": 0.75, "low": 0.5}


def certainty_composite(strength: str, certainty_level: str) -> float:
    """Monotone [0,1] ranking scalar = peak signal tier × weakest-link certainty. A NAMED projection
    ('certainty-discounted strength'), NOT a canonical single value — other lens weightings are equally
    valid. Non-substituting: certainty multiplies, never averages against signal. Unknown strength → 0.0;
    unknown level → 0.5."""
    return round(_COMPOSITE_STRENGTH.get(strength, 0.0) * _COMPOSITE_CERTAINTY.get(certainty_level, 0.5), 3)
