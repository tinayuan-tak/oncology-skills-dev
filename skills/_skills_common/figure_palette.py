"""Shared SVG-figure primitives — HTML escaping + the signal-tier color palette.

The standalone figure/hero modules hand-roll SVG strings and had each re-declared a byte-identical
`_esc` (7 copies) and, in headline_hero / presence_claims_figure, an identical signal-tier palette
(`SIG_TIER` / `TIER_FILL` / `REL_DOTS`). Single-sourced here.

NOTE (deliberately NOT shared): presence_matrix's `_TIER_FILL` is a DIFFERENT semantic (a blue
cell-shading ramp, not the signal-tier fill), and subgroup_figure keeps its own palette — those are
intentionally distinct and stay module-local pending a design pass.
"""

from __future__ import annotations


def esc(s) -> str:
    """Minimal HTML escape for text interpolated into a hand-rolled SVG string."""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# signal tier -> ordinal rank (None = unmeasured); rank -> fill color; corroboration -> relation-dot count.
SIG_TIER = {"strong": 3, "moderate": 2, "weak": 1, "absent": 0, "negative": 0, "unmeasured": None}
TIER_FILL = {3: "#184f95", 2: "#2a78d6", 1: "#f0a030", 0: "#d03b3b", None: "#c9ccd1"}
REL_DOTS = {"high": 3, "moderate": 2, "low": 1, "insufficient": 0, "unmeasured": 0}
