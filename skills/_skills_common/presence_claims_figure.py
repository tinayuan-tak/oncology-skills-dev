"""Claim-vector figure — a compact SVG of the presence claim vector (A/B/C/D signal × corroboration),
the visual twin of _skills_common.presence_claims. Additive / display-only, emitted via the
--figures hook alongside the presence-context matrix.

Honesty discipline (mirrors presence_matrix / ordinal_view): tiers are ORDER, not magnitude; the bar
length encodes the ordinal tier only; corroboration is a SEPARATE channel (dots); an UNMEASURED claim
is a hatched gap — NEVER a zero-length bar (a coverage gap is not a measured absence). Reads only
decision['headline']['claim_vector'] — deterministic and cheap.
"""

from __future__ import annotations
import json
from pathlib import Path

from _skills_common.figure_palette import (
    esc as _esc,
    SIG_TIER as _SIG_TIER,
    TIER_FILL as _TIER_FILL,
    REL_DOTS as _REL_DOTS,
)

_CLAIM = [("A", "abundance"), ("B", "tumor-elevation"), ("C", "malignant-intrinsic"), ("D", "generality")]


def render_claim_vector_svg(claim_vector: dict, target: str, indication: str) -> str:
    W, H = 560, 44 + len(_CLAIM) * 34 + 46
    x0, rowh, barmax = 14, 34, 150
    s = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'font-family="Inter, Helvetica, Arial, sans-serif">',
        f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
        '<defs><pattern id="cvna" width="6" height="6" patternUnits="userSpaceOnUse" '
        'patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" stroke="#d5d7da" stroke-width="1.4"/></pattern></defs>',
        f'<text x="{x0}" y="20" font-size="13" font-weight="700" fill="#1a1a19">{_esc(target)} · {_esc(indication)}</text>',
        f'<text x="{x0}" y="35" font-size="10" fill="#6b6f76">Presence claim vector — signal (bar, ordinal) × corroboration (dots). '
        f"Modality-blind, verdict-inert; hatched = unmeasured gap.</text>",
    ]
    y = 50
    for k, name in _CLAIM:
        cl = (claim_vector or {}).get(k) or {}
        tier = _SIG_TIER.get(cl.get("signal"))
        s.append(f'<text x="{x0}" y="{y + 15}" font-size="11" font-weight="600" fill="#1a1a19">{k}</text>')
        s.append(f'<text x="{x0 + 14}" y="{y + 15}" font-size="10.5" fill="#3a3a39">{_esc(name)}</text>')
        bx = x0 + 150
        if tier is None:
            s.append(
                f'<rect x="{bx}" y="{y + 4}" width="{barmax}" height="13" rx="3" fill="url(#cvna)" stroke="#e3e4e6"/>'
            )
            s.append(f'<text x="{bx + barmax + 8}" y="{y + 15}" font-size="9.5" fill="#8a8d91">unmeasured (gap)</text>')
        else:
            bw = max(6, int(tier / 3 * barmax))
            s.append(f'<rect x="{bx}" y="{y + 4}" width="{barmax}" height="13" rx="3" fill="#f0f0ee"/>')
            s.append(f'<rect x="{bx}" y="{y + 4}" width="{bw}" height="13" rx="3" fill="{_TIER_FILL[tier]}"/>')
            nrel = _REL_DOTS.get(cl.get("corroboration"), 0)
            dots = "".join(
                f'<circle cx="{bx + barmax + 14 + j * 11}" cy="{y + 10}" r="3.5" '
                f'fill="{"#184f95" if j < nrel else "none"}" stroke="#184f95" stroke-width="1"/>'
                for j in range(3)
            )
            s.append(dots)
            s.append(
                f'<text x="{bx + barmax + 58}" y="{y + 14}" font-size="9.5" fill="#3a3a39">{_esc(cl.get("signal"))} · {_esc(cl.get("corroboration"))}</text>'
            )
        y += rowh
    hom = (claim_vector or {}).get("homogeneity")
    s.append(
        f'<text x="{x0}" y="{y + 14}" font-size="9.5" fill="#6b6f76">homogeneity (TCE lens): '
        f"{_esc(hom) if hom and hom != 'unmeasured' else 'n/a'}  ·  claims are orthogonal — not additive</text>"
    )
    s.append("</svg>")
    return "\n".join(s)


def emit_claim_vector_figure(decision: dict, figures_root) -> list:
    """Emit figure_claim_vector.{svg,json} from decision['headline']['claim_vector']. Additive /
    best-effort; returns [] when the decision predates the claim vector (spine unaffected)."""
    headline = (decision or {}).get("headline") or {}
    cv = headline.get("claim_vector")
    if not isinstance(cv, dict):
        return []
    figures_root = Path(figures_root)
    figures_root.mkdir(parents=True, exist_ok=True)
    target = decision.get("target", "")
    indication = decision.get("indication", "") or "pan-cancer"
    svg = figures_root / "figure_claim_vector.svg"
    js = figures_root / "claim_vector.json"
    svg.write_text(render_claim_vector_svg(cv, target, indication), encoding="utf-8")
    js.write_text(json.dumps(cv, indent=2, default=str), encoding="utf-8")
    return [svg, js]


__all__ = ["render_claim_vector_svg", "emit_claim_vector_figure"]
