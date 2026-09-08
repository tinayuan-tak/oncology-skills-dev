"""Per-axis (sub-group) signals-first figure — the productionized reference figure.

Renders decision['headline']['subgroup_signals'] as small multiples: one panel per orthogonal
sub-group (ranked by signal), each with an ordinal SIGNAL bar + backing, CONFIDENCE as independent-
source markers (fill=agrees, red ring=conflict, size=sample size), and — when subtype is measured —
a FIRST-CLASS per-stratum row (by_stratum) + the subtype axis (ε²). Reads only the headline; offline;
best-effort ([] when no subgroup_signals). House palette (validated; conflict=status red).
"""

from __future__ import annotations

import json
from pathlib import Path

from _skills_common.figure_palette import esc as _esc

_TIER = {"strong": 3, "moderate": 2, "weak": 1, "absent": 0, "unmeasured": None}
# Deliberately NOT the shared figure_palette.TIER_FILL: tier-0 (absent) is NEUTRAL gray here, not red —
# red (#d03b3b) is reserved for _CONFLICT in this sub-group view, so "no signal in this subgroup" must
# read as neutral, not as a negative verdict. (Tiers 3/2/1 do match the shared signal palette.)
_FILL = {3: "#184f95", 2: "#2a78d6", 1: "#f0a030", 0: "#c9ccd1", None: "#c9ccd1"}
_AGREE, _CONFLICT, _INK, _MUT = "#2a78d6", "#d03b3b", "#1a1a19", "#8a8d91"
_RANK = {"strong": 3, "moderate": 2, "weak": 1, "absent": 0, "unmeasured": -1}


def _rad(n):
    return (
        8
        if isinstance(n, (int, float)) and n >= 1e5
        else 7
        if isinstance(n, (int, float)) and n >= 100
        else 6
        if isinstance(n, (int, float)) and n >= 20
        else 5
    )


def render_subgroup_svg(subgroup_signals: dict, target: str, indication: str) -> str:
    sgs = sorted(
        ((k, v) for k, v in subgroup_signals.items() if isinstance(v, dict)),
        key=lambda kv: _RANK.get(kv[1].get("signal"), -1),
        reverse=True,
    )
    W, header_h = 640, 46
    heights, bodies = [], []
    for name, sg in sgs:
        has_strat = bool(sg.get("by_stratum"))
        h = 92 + (46 if has_strat else 0)
        heights.append(h)
    H = header_h + sum(heights) + 12 * len(sgs) + 14
    x0 = 14
    s = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'font-family="Inter, Helvetica, Arial, sans-serif">',
        f'<rect width="{W}" height="{H}" fill="#f4f5f7"/>',
        '<defs><pattern id="sgna" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
        '<line x1="0" y1="0" x2="0" y2="6" stroke="#d5d7da" stroke-width="1.4"/></pattern></defs>',
        f'<text x="{x0}" y="24" font-size="14" font-weight="700" fill="{_INK}">{_esc(target)} · {_esc(indication)} '
        f"— by sub-group</text>",
        f'<text x="{x0}" y="40" font-size="10" fill="{_MUT}">Bar = ordinal signal · markers = independent sources '
        f"(fill=agrees, ring=conflict, size=sample size) · subtype shown per stratum.</text>",
    ]
    y = header_h
    for (name, sg), ph in zip(sgs, heights):
        tier = _TIER.get(sg.get("signal"))
        col = _FILL[tier]
        s.append(f'<rect x="{x0}" y="{y}" width="{W - 2 * x0}" height="{ph}" rx="9" fill="#fff" stroke="#eceef1"/>')
        s.append(
            f'<text x="{x0 + 14}" y="{y + 22}" font-size="12.5" font-weight="700" fill="{_INK}">{_esc(name)}</text>'
        )
        # signal bar
        bx, by, bmax = x0 + 14, y + 32, 240
        s.append(f'<rect x="{bx}" y="{by}" width="{bmax}" height="12" rx="4" fill="#f0f0ee"/>')
        s.append(
            f'<rect x="{bx}" y="{by}" width="{max(8, int((tier or 0.15) / 3 * bmax))}" height="12" rx="4" fill="{col}"/>'
        )
        s.append(
            f'<text x="{bx + bmax + 12}" y="{by + 11}" font-size="11" font-weight="700" fill="{col}">{_esc(sg.get("signal"))}</text>'
        )
        # confidence summary (top-right)
        cflag = " · ⚠ conflict" if sg.get("conflict") else ""
        s.append(
            f'<text x="{W - x0 - 14}" y="{y + 22}" font-size="11" text-anchor="end" fill="{_INK}">'
            f'confidence <tspan font-weight="700">{_esc(sg.get("confidence"))}</tspan></text>'
        )
        s.append(
            f'<text x="{W - x0 - 14}" y="{y + 37}" font-size="9" text-anchor="end" fill="{_MUT}">'
            f"{sg.get('n_agree')}/{sg.get('n_sources')} agree · power {_esc(sg.get('power'))}{cflag}</text>"
        )
        # source markers
        srcs = sg.get("sources") or []
        mx, my, step = x0 + 24, y + 62, min(150, (W - 60) // max(1, len(srcs)))
        for i, sc in enumerate(srcs):
            cx = mx + i * step
            r = _rad(sc.get("n"))
            if sc.get("conflict"):
                s.append(f'<circle cx="{cx}" cy="{my}" r="{r}" fill="#fff" stroke="{_CONFLICT}" stroke-width="2.5"/>')
                s.append(
                    f'<text x="{cx}" y="{my + 3.5}" font-size="10" text-anchor="middle" fill="{_CONFLICT}">!</text>'
                )
            else:
                st = _TIER.get(sc.get("tier"))
                s.append(
                    f'<circle cx="{cx}" cy="{my}" r="{r}" fill="{_FILL[st] if st else "#fff"}" '
                    + ("" if st else f'stroke="{_MUT}" stroke-dasharray="2 2"')
                    + "/>"
                )
            s.append(
                f'<text x="{cx}" y="{my + 18}" font-size="8.5" text-anchor="middle" fill="{_INK}">{_esc(sc.get("label"))}</text>'
            )
        # FIRST-CLASS subtype: a per-stratum mini-BAR strip (signal conditioned on subtype), dimmed +
        # hatched when underpowered. More prominent than a dot-row — subtype reads as its own signal band.
        if sg.get("by_stratum"):
            eps = (sg.get("subtype_axis") or {}).get("epsilon_squared")
            sy = y + ph - 40
            lbl = f"subtype signal per stratum (ε²={eps})" if eps is not None else "subtype signal per stratum"
            s.append(f'<text x="{x0 + 14}" y="{sy}" font-size="9" font-weight="600" fill="{_MUT}">{_esc(lbl)}</text>')
            sx, bw = x0 + 14, 48
            for sid, st in list(sg["by_stratum"].items())[:8]:
                stier = _TIER.get(st.get("signal"))
                c = _FILL[stier] if stier is not None else _MUT
                powered = st.get("powered")
                op = "1" if powered else "0.45"
                by2 = sy + 7
                s.append(f'<rect x="{sx}" y="{by2}" width="{bw}" height="9" rx="2" fill="#f0f0ee"/>')
                fillw = max(5, int((stier or 0) / 3 * bw))
                s.append(
                    f'<rect x="{sx}" y="{by2}" width="{fillw}" height="9" rx="2" fill="{c}" opacity="{op}"/>'
                    + (
                        ""
                        if powered
                        else f'<rect x="{sx}" y="{by2}" width="{bw}" height="9" rx="2" fill="url(#sgna)"/>'
                    )
                )
                s.append(f'<text x="{sx}" y="{by2 + 21}" font-size="8" fill="{_INK}" opacity="{op}">{_esc(sid)}</text>')
                if not powered:
                    s.append(f'<text x="{sx}" y="{by2 + 30}" font-size="6.5" fill="{_MUT}">underpowered</text>')
                sx += bw + 14 + 5 * max(0, len(str(sid)) - 5)
        y += ph + 12
    s.append("</svg>")
    return "\n".join(s)


def emit_subgroup_figure(decision: dict, figures_root) -> list:
    """Emit figure_subgroup_signals.{svg,json}. [] when no subgroup_signals (spine unaffected)."""
    try:
        headline = (decision or {}).get("headline") or {}
        sgs = headline.get("subgroup_signals")
        if not isinstance(sgs, dict) or not sgs:
            return []
        root = Path(figures_root)
        root.mkdir(parents=True, exist_ok=True)
        target = decision.get("target", "") or ""
        indication = decision.get("indication", "") or "pan-cancer"
        out = []
        svg = root / "figure_subgroup_signals.svg"
        svg.write_text(render_subgroup_svg(sgs, target, indication), encoding="utf-8")
        out.append(svg)
        js = root / "figure_subgroup_signals.json"
        js.write_text(json.dumps(sgs, indent=2, default=str), encoding="utf-8")
        out.append(js)
        return out
    except Exception:  # noqa: BLE001 — display-only; never break the run
        return []


__all__ = ["render_subgroup_svg", "emit_subgroup_figure"]
