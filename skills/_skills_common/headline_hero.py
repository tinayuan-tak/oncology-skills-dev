"""headline_hero — the SHARED reference renderer for the canonical Headline block.

Turns the renderer-agnostic `hero` plot_data (built by headline_core.build_headline) into a compact
hero graphic: an SVG (hand-rolled, matching the house style of presence_claims_figure / presence_matrix)
plus a matplotlib PNG twin and the JSON payload. This is THE ONE hero every skill emits —
`figure_headline_hero.{svg,png,json}` — replacing the ad-hoc per-skill figure names and the SVG-vs-PNG
format split.

Discipline (mirrors presence_claims_figure): tiers are ORDER, not magnitude; the bar length encodes the
ordinal signal tier only; corroboration is a SEPARATE dot channel; an UNMEASURED axis is a hatched gap,
NEVER a zero-length bar. Reads ONLY `decision['headline']['headline_block']` + decision target/indication
— deterministic, offline, no live read. Best-effort: missing block → [] (spine unaffected); a PNG
backend failure degrades to SVG+JSON only.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

_SIG_TIER = {"strong": 3, "moderate": 2, "weak": 1, "absent": 0, "negative": 0, "unmeasured": None}
_TIER_FILL = {3: "#184f95", 2: "#2a78d6", 1: "#f0a030", 0: "#d03b3b", None: "#c9ccd1"}
_REL_DOTS = {"high": 3, "moderate": 2, "low": 1, "insufficient": 0, "unmeasured": 0}
_CONF_PIPS = {"strong": 3, "moderate": 2, "weak": 1, "insufficient": 0}

# Verdict-badge polarity → color. A generic lexical heuristic (the headline layer is skill-agnostic):
# a positive call reads blue, a negative/empty call reads red, anything else stays neutral gray.
_POS = ("present", "elevated", "dependen", "favorable", "viable", "druggable", "selective",
        "altered", "driver", "essential", "yes")
_NEG = ("absent", "not ", "no ", "neither", "non-", "non_", "tolerant", "undruggable",
        "insufficient", "unavailable", "passenger")


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_POLARITY_COLOR = {"positive": "#184f95", "negative": "#8a1f1f", "neutral": "#5a5f66"}

# Per-modality-ARM call → colour (used only when a skill supplies plot_data["modality_arms"], e.g.
# surface-modality-fit's {adc, bite_tce, antibody}). Positive-viable=blue, foreclosed/opposed=red,
# caveat/soft=amber, gap/undefined=gray. Skill-agnostic (any arm-decomposing skill can populate it).
_ARM_CALL_COLOR = {
    "viable": "#184f95", "preferred": "#184f95", "supported": "#184f95",
    "unsafe": "#8a1f1f", "not_viable": "#8a1f1f", "opposed": "#8a1f1f", "escape_risk": "#8a1f1f",
    "caveated": "#c8892a", "not_preferred": "#c8892a", "ambiguous": "#c8892a",
}
_ARM_LABEL = {"adc": "ADC", "bite_tce": "TCE", "antibody": "mAb", "pmhc_tce": "pMHC-TCE"}


def _verdict_color(verdict: dict) -> str:
    """Colour the badge by the skill's OWN declared polarity when present (authoritative); otherwise
    fall back to a lexical heuristic over the phrase."""
    pol = (verdict or {}).get("polarity")
    if pol in _POLARITY_COLOR:
        return _POLARITY_COLOR[pol]
    p = ((verdict or {}).get("phrase") or "").lower()
    if any(t in p for t in _POS):
        return "#184f95"
    if any(t in p for t in _NEG):
        return "#8a1f1f"
    return "#5a5f66"


def _truncate(s: str, n: int = 96) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def render_headline_hero_svg(plot_data: dict, target: str, indication: str) -> str:
    """Compact hero SVG: title, verdict badge, confidence meter, per-axis signal×corroboration, tension."""
    axes = plot_data.get("axes") or []
    verdict = plot_data.get("verdict") or {}
    confidence = plot_data.get("confidence") or {}
    tension = plot_data.get("tension") or None
    arms = plot_data.get("modality_arms") or {}
    W = 620
    header_h, badge_h, rowh = 44, 46, 30
    tension_h = 34 if tension else 0
    arms_h = 28 if arms else 0
    H = header_h + badge_h + 12 + len(axes) * rowh + arms_h + tension_h + 20
    x0 = 16
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
         f'font-family="Inter, Helvetica, Arial, sans-serif">',
         f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
         '<defs><pattern id="hhna" width="6" height="6" patternUnits="userSpaceOnUse" '
         'patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" stroke="#d5d7da" '
         'stroke-width="1.4"/></pattern></defs>',
         f'<text x="{x0}" y="20" font-size="13" font-weight="700" fill="#1a1a19">'
         f'{_esc(target)} · {_esc(indication)}</text>',
         f'<text x="{x0}" y="36" font-size="10" fill="#6b6f76">Headline — verdict · confidence · top '
         f'tension. Verdict-inert projection; bar = ordinal signal, dots = corroboration.</text>']

    # verdict badge
    by = header_h
    bw = 320
    color = _verdict_color(verdict)
    s.append(f'<rect x="{x0}" y="{by}" width="{bw}" height="{badge_h-8}" rx="6" fill="{color}"/>')
    s.append(f'<text x="{x0+14}" y="{by+17}" font-size="15" font-weight="700" fill="#ffffff">'
             f'{_esc(_truncate(verdict.get("phrase") or "No call", 40))}</text>')
    s.append(f'<text x="{x0+14}" y="{by+32}" font-size="9.5" fill="#e7ecf5">'
             f'gate: {_esc(verdict.get("gate") or "—")}</text>')

    # confidence meter (to the right of the badge)
    cx = x0 + bw + 22
    lvl = confidence.get("level", "insufficient")
    npips = _CONF_PIPS.get(lvl, 0)
    s.append(f'<text x="{cx}" y="{by+13}" font-size="10" font-weight="600" fill="#3a3a39">confidence</text>')
    for j in range(3):
        fill = "#184f95" if j < npips else "none"
        s.append(f'<rect x="{cx+j*22}" y="{by+20}" width="18" height="10" rx="2" fill="{fill}" '
                 f'stroke="#184f95" stroke-width="1"/>')
    s.append(f'<text x="{cx}" y="{by+42}" font-size="10" fill="#3a3a39">{_esc(lvl)}</text>')

    # per-axis signal × corroboration
    y = header_h + badge_h + 12
    lbl_x, bar_x, barmax = x0, x0 + 168, 150
    for ax in axes:
        tier = _SIG_TIER.get(ax.get("signal"))
        s.append(f'<text x="{lbl_x}" y="{y+13}" font-size="10.5" fill="#3a3a39">'
                 f'{_esc(ax.get("key"))} · {_esc(ax.get("label"))}</text>')
        if tier is None:
            s.append(f'<rect x="{bar_x}" y="{y+3}" width="{barmax}" height="12" rx="3" '
                     f'fill="url(#hhna)" stroke="#e3e4e6"/>')
            s.append(f'<text x="{bar_x+barmax+8}" y="{y+13}" font-size="9.5" fill="#8a8d91">unmeasured (gap)</text>')
        else:
            bw2 = max(6, int(tier / 3 * barmax))
            s.append(f'<rect x="{bar_x}" y="{y+3}" width="{barmax}" height="12" rx="3" fill="#f0f0ee"/>')
            s.append(f'<rect x="{bar_x}" y="{y+3}" width="{bw2}" height="12" rx="3" fill="{_TIER_FILL[tier]}"/>')
            nrel = _REL_DOTS.get(ax.get("corroboration"), 0)
            dots = "".join(f'<circle cx="{bar_x+barmax+14+j*11}" cy="{y+9}" r="3.5" '
                           f'fill="{"#184f95" if j < nrel else "none"}" stroke="#184f95" '
                           f'stroke-width="1"/>' for j in range(3))
            s.append(dots)
            warn = " ⚠" if ax.get("conflict") else ""
            s.append(f'<text x="{bar_x+barmax+58}" y="{y+13}" font-size="9.5" fill="#3a3a39">'
                     f'{_esc(ax.get("signal"))} · {_esc(ax.get("corroboration"))}{warn}</text>')
        y += rowh

    # per-modality-arm decomposition (optional; e.g. surface-modality-fit adc/bite_tce/antibody). The
    # arms are the modality CHANNELS (orthogonal to the evidence axes above) — a colored chip per arm.
    if arms:
        s.append(f'<text x="{x0}" y="{y+13}" font-size="10" font-weight="600" fill="#3a3a39">modality arms</text>')
        cxp = x0 + 108
        for arm in [a for a in ("adc", "bite_tce", "antibody", "pmhc_tce") if a in arms] + \
                   [a for a in arms if a not in ("adc", "bite_tce", "antibody", "pmhc_tce")]:
            call = arms.get(arm)
            col = _ARM_CALL_COLOR.get(call, "#8a8d91")
            chip = f'{_ARM_LABEL.get(arm, arm)}: {call}'
            wchip = 8 + int(6.2 * len(chip))
            s.append(f'<rect x="{cxp}" y="{y+1}" width="{wchip}" height="16" rx="8" fill="none" '
                     f'stroke="{col}" stroke-width="1.2"/>')
            s.append(f'<text x="{cxp+7}" y="{y+13}" font-size="9.5" fill="{col}">{_esc(chip)}</text>')
            cxp += wchip + 8
        y += arms_h

    # tension callout
    if tension:
        s.append(f'<rect x="{x0}" y="{y+2}" width="4" height="{tension_h-8}" fill="#c8892a"/>')
        s.append(f'<text x="{x0+12}" y="{y+13}" font-size="10" font-weight="600" fill="#9a6412">'
                 f'top tension</text>')
        s.append(f'<text x="{x0+12}" y="{y+27}" font-size="10" fill="#3a3a39">'
                 f'{_esc(_truncate(tension.get("text", ""), 92))}</text>')
    s.append("</svg>")
    return "\n".join(s)


def render_headline_hero_png(plot_data: dict, target: str, indication: str, path) -> Optional[Path]:
    """matplotlib PNG twin of the hero (the reference raster renderer). Offline; returns the path, or
    None when a backend is unavailable (SVG+JSON remain the primary artifacts)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import FancyBboxPatch
    except Exception:  # noqa: BLE001 — matplotlib optional; degrade to no PNG
        return None
    axes = plot_data.get("axes") or []
    verdict = plot_data.get("verdict") or {}
    confidence = plot_data.get("confidence") or {}
    tension = plot_data.get("tension") or None
    n = len(axes)
    fig, ax = plt.subplots(figsize=(6.2, 1.4 + 0.42 * max(n, 1) + (0.5 if tension else 0)), dpi=300)
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.text(0.0, 0.98, f"{target} · {indication}", fontsize=11, fontweight="bold", va="top")
    # verdict badge
    color = _verdict_color(verdict)
    ax.add_patch(FancyBboxPatch((0.0, 0.80), 0.55, 0.12, boxstyle="round,pad=0.008",
                                linewidth=0, facecolor=color, transform=ax.transAxes))
    ax.text(0.02, 0.86, _truncate(verdict.get("phrase") or "No call", 38), fontsize=11,
            fontweight="bold", color="white", va="center")
    ax.text(0.62, 0.86, f"confidence: {confidence.get('level', 'insufficient')}", fontsize=9, va="center")
    # axis bars
    top = 0.70
    step = 0.62 / max(n, 1)
    for i, a in enumerate(axes):
        y = top - i * step
        tier = _SIG_TIER.get(a.get("signal"))
        ax.text(0.0, y, f"{a.get('key')} {a.get('label')}", fontsize=8, va="center")
        if tier is None:
            ax.barh(y, 0.30, left=0.42, height=step * 0.5, color="#e6e7ea", hatch="///",
                    edgecolor="#c9ccd1")
            ax.text(0.74, y, "unmeasured", fontsize=7, va="center", color="#8a8d91")
        else:
            ax.barh(y, 0.30 * (tier / 3), left=0.42, height=step * 0.5, color=_TIER_FILL[tier])
            ax.text(0.74, y, f"{a.get('signal')}·{a.get('corroboration')}", fontsize=7, va="center")
    if tension:
        ax.text(0.0, 0.03, "tension: " + _truncate(tension.get("text", ""), 78), fontsize=7.5,
                va="bottom", color="#9a6412")
    path = Path(path)
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def emit_headline_hero(decision: dict, figures_root) -> list:
    """Emit figure_headline_hero.{svg,png,json} from decision['headline']['headline_block'].
    Best-effort / additive; returns [] when the decision predates the headline block (spine unaffected)."""
    headline = (decision or {}).get("headline") or {}
    block = headline.get("headline_block")
    if not isinstance(block, dict) or not isinstance(block.get("hero"), dict):
        return []
    figures_root = Path(figures_root)
    figures_root.mkdir(parents=True, exist_ok=True)
    target = decision.get("target", "") or ""
    indication = decision.get("indication", "") or "pan-cancer"
    hero = block["hero"]
    out = []
    svg = figures_root / "figure_headline_hero.svg"
    svg.write_text(render_headline_hero_svg(hero, target, indication), encoding="utf-8")
    out.append(svg)
    js = figures_root / "figure_headline_hero.json"
    js.write_text(json.dumps(block, indent=2, default=str), encoding="utf-8")
    out.append(js)
    png = render_headline_hero_png(hero, target, indication, figures_root / "figure_headline_hero.png")
    if png is not None:
        out.append(png)
    return out


__all__ = ["render_headline_hero_svg", "render_headline_hero_png", "emit_headline_hero"]
