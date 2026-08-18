"""Subtype-refinement figure — a compact SVG of the per-stratum claim vector
(headline['claim_vector_by_subtype'], from #527). Shows the strata-varying claims (A abundance,
distributional B) per molecular subtype, so a target-indication-SUBTYPE reader sees where the pooled
signal concentrates (e.g. CD274 → MSI-H). Additive / display-only, emitted via the --figures hook.

Honesty discipline (mirrors presence_matrix / presence_claims_figure): bar length = ORDINAL tier
only; underpowered strata (n < 30) are dimmed; the header states whether subtype is a real selection
axis (ε² effect-size class), so a negligible-ε² panel is not read as a selection signal. C /
protein-confirmation are indication-grain (not stratified) and are labelled as such, never drawn per
stratum. Reads only the decision headline — deterministic and cheap.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

_TIER = {"strong": 3, "moderate": 2, "weak": 1, "absent": 0, "unmeasured": None}
_FILL = {3: "#184f95", 2: "#2a78d6", 1: "#f0a030", 0: "#d03b3b", None: "#c9ccd1"}


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _bar(sig, x, y, w=88):
    t = _TIER.get(sig)
    if t is None:
        return f'<text x="{x}" y="{y+10}" font-size="9" fill="#b8bcc2">n/a</text>'
    bw = max(4, int(t / 3 * w))
    return (f'<rect x="{x}" y="{y+1}" width="{w}" height="11" rx="2" fill="#f0f0ee"/>'
            f'<rect x="{x}" y="{y+1}" width="{bw}" height="11" rx="2" fill="{_FILL[t]}"/>')


def render_subtype_refinement_svg(cvbs: dict, target: str, indication: str) -> str:
    strata = cvbs.get("strata") or {}
    # order by abundance-tier then median-in-evidence; keep it stable + readable (top 10)
    def _atier(sid):
        return _TIER.get((strata[sid].get("A") or {}).get("signal")) or -1
    ordered = sorted(strata, key=lambda s: -(_atier(s) if _atier(s) is not None else -1))[:10]
    eff = cvbs.get("subtype_effect_size_class"); eps = cvbs.get("subtype_variance_explained")
    sep = cvbs.get("which_subtypes_separate") or {}
    axis_note = ("subtype is NOT a useful selection axis (variance negligible)"
                 if eff in ("negligible", None) else
                 f"expression concentrates by subtype (ε² {eff}); highest: {sep.get('highest')}")
    W = 470; H = 78 + len(ordered) * 22 + 28
    x0, xa, xb = 14, 150, 250
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
         f'font-family="Inter, Helvetica, Arial, sans-serif"><rect width="{W}" height="{H}" fill="#fff"/>',
         f'<text x="{x0}" y="18" font-size="13" font-weight="700" fill="#1a1a19">{_esc(target)} · {_esc(indication)} — subtype refinement</text>',
         f'<text x="{x0}" y="33" font-size="10" fill="#6b6f76">{_esc(cvbs.get("stratification_class"))} · '
         f'ε²={eps:.3f} ({_esc(eff)}) · {cvbs.get("n_subtypes_measured")} strata</text>' if isinstance(eps, (int, float))
         else f'<text x="{x0}" y="33" font-size="10" fill="#6b6f76">{_esc(cvbs.get("stratification_class"))}</text>',
         f'<text x="{x0}" y="47" font-size="9.5" fill="#8a4b1a">→ {_esc(axis_note)}</text>',
         f'<text x="{xa}" y="64" font-size="9" fill="#6b6f76">A abundance</text>',
         f'<text x="{xb}" y="64" font-size="9" fill="#6b6f76">B elev (%&gt;normal)</text>']
    y = 70
    for sid in ordered:
        st = strata[sid]; n = st.get("n_tumor_samples")
        dim = ' opacity="0.5"' if not (isinstance(n, int) and n >= 30) else ""
        mk = " ◀hi" if sid == sep.get("highest") else (" ◀lo" if sid == sep.get("lowest") else "")
        s.append(f'<g{dim}>')
        s.append(f'<text x="{x0}" y="{y+10}" font-size="10" font-weight="600" fill="#1a1a19">{_esc(sid)}{mk}</text>')
        s.append(f'<text x="{x0+96}" y="{y+10}" font-size="8.5" fill="#8a8d91">n={n}</text>')
        s.append(_bar((st.get("A") or {}).get("signal"), xa, y))
        s.append(_bar((st.get("B") or {}).get("signal"), xb, y, w=120))
        s.append('</g>')
        y += 22
    s.append(f'<text x="{x0}" y="{y+14}" font-size="8.5" fill="#8a8d91">C (single-cell) &amp; protein: '
             f'indication-grain (not stratified) · n&lt;30 dimmed · bar = ordinal tier</text>')
    s.append("</svg>")
    return "\n".join(s)


def emit_subtype_refinement_figure(decision: dict, figures_root) -> list:
    """Emit figure_subtype_refinement.{svg,json} from headline['claim_vector_by_subtype']. Additive /
    best-effort; returns [] when the indication has no subtype axis (field is None)."""
    cvbs = ((decision or {}).get("headline") or {}).get("claim_vector_by_subtype")
    if not isinstance(cvbs, dict) or not (cvbs.get("strata")):
        return []
    figures_root = Path(figures_root); figures_root.mkdir(parents=True, exist_ok=True)
    target = decision.get("target", ""); indication = decision.get("indication", "") or "pan-cancer"
    svg = figures_root / "figure_subtype_refinement.svg"
    js = figures_root / "subtype_refinement.json"
    svg.write_text(render_subtype_refinement_svg(cvbs, target, indication), encoding="utf-8")
    js.write_text(json.dumps(cvbs, indent=2, default=str), encoding="utf-8")
    return [svg, js]


__all__ = ["render_subtype_refinement_svg", "emit_subtype_refinement_figure"]
