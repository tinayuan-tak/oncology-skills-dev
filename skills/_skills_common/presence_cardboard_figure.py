"""Card-board figure — every tumor-presence card bucketed under its claim (A/B/C/D) into the honest
ternary {signal / no-signal / not-measured} with a reliability channel. The 'what's contributing /
where are the gaps' view — the drill-down beneath the collapsed claim vector.

Honesty discipline: `no-signal` (measured negative) and `not-measured` (coverage gap) are DIFFERENT
facts and rendered distinctly (○ vs ▨) — collapsing them is the most common way presence readouts
mislead. Polarity is ROLE-AWARE: for a PRESENCE claim, expression present = signal; for a
NORMAL-TISSUE comparator the polarity FLIPS (expression present = liability ▲), so a green mark never
means 'high in normal tissue'. Reads only decision['cards'] + headline — deterministic, display-only.
"""

from __future__ import annotations

import json
from pathlib import Path

from _skills_common.figure_palette import esc as _esc

# card_id -> (claim, primary field, role). role: signal | reliability | comparator.
_SPEC = [
    ("tumor-rna-distribution", "A", "tumor_expression_class", "signal"),
    ("cellline-rna-distribution", "A", "expression_class", "signal"),
    ("cellline-protein-abundance", "A", "protein_expression_class", "signal"),
    ("tumor-rna-vs-adjacent", "B", "expression_call_class", "signal"),
    ("tumor-protein-abundance-cptac", "B", "protein_expression_class", "signal"),
    ("tumor-scrna-celltype-expression", "C", "sc_expression_class", "signal"),
    ("expression-purity-confound", "C", "purity_confound_class", "signal"),
    ("tumor-elevation-breadth", "D", "tumor_elevation_breadth_class", "signal"),
    ("tumor-rna-distribution-by-subtype", "D", "subtype_stratification_class", "signal"),
    ("rna-protein-concordance-tumor", "R", "rna_as_biomarker", "reliability"),
    ("normal-tissue-liability", "W", "normal_tissue_breadth_class", "comparator"),
    ("sc-normal-celltype-expression", "W", "sc_normal_expression_class", "comparator"),
]
_GROUP = {
    "A": "A · abundance",
    "B": "B · tumor-elevation",
    "C": "C · malignant-intrinsic",
    "D": "D · generality",
    "R": "reliability (RNA↔protein proxy)",
    "W": "normal-tissue comparators (window)",
}
_SIGNAL = (
    "broadly_high",
    "broadly_moderate",
    "broadly_detected",
    "subset_high",
    "lineage_restricted",
    "moderately_expressed",
    "strong_up",
    "modest_up",
    "strong_upregulation",
    "modest_upregulation",
    "malignant_broadly_detected",
    "malignant_subset_detected",
    "broadly_tumor_elevated",
    "multi_tumor_elevated",
    "single_tumor_elevated",
    "tumor_intrinsic",
    "subtype_enriched",
    "pan_subtype_uniform",
    "subtype_restricted",
)
_NO_SIGNAL = (
    "broadly_low",
    "not_informative",
    "not_tumor_elevated",
    "microenvironment_dominant",
    "not_detected",
    "not_significant",
    "small_effect",
    "strong_down",
    "modest_down",
    "downregulation",
    "sparsely",
    "ns",
)
# glyph, colour, label — including the polarity-flipped comparator + reliability states.
_GLYPH = {
    "signal": ("●", "#2a78d6"),
    "no_signal": ("○", "#b8bcc2"),
    "not_measured": ("▨", "#c9ccd1"),
    "liability": ("▲", "#d03b3b"),
    "clean_window": ("✓", "#0ca30c"),
    "proxy_ok": ("◆", "#2a78d6"),
    "proxy_partial": ("◆", "#f0a030"),
    "proxy_poor": ("◆", "#d03b3b"),
}
_RELDOT = {"high": 3, "moderate": 2, "low": 1}


def _bucket(val, role):
    if val in (None, "data_unavailable", "") or val is False:
        return "not_measured"
    v = str(val)
    if role == "comparator":
        if any(t in v for t in ("broad", "HIGH_LIABILITY", "ubiquitous", "high", "origin_tissue")):
            return "liability"
        if any(t in v for t in ("not_detected", "absent", "low", "restricted", "not_expressed")):
            return "clean_window"
        return "liability"
    if role == "reliability":
        return (
            "proxy_ok"
            if ("adequate" in v or "confirmed" in v)
            else "proxy_partial"
            if "partial" in v
            else "proxy_poor"
            if "poor" in v
            else "proxy_partial"
        )
    if any(t in v for t in _NO_SIGNAL):
        return "no_signal"
    if any(t in v for t in _SIGNAL):
        return "signal"
    return "signal"


def _reliability(cid, s, h):
    def bq(q, n=None):
        if not isinstance(q, (int, float)):
            return "low"
        return "high" if (q < 1e-10 and (n is None or n >= 20)) else "moderate" if q < 0.05 else "low"

    if cid == "tumor-rna-vs-adjacent":
        return bq(s.get("q_value"))
    if cid == "tumor-protein-abundance-cptac":
        return bq(s.get("protein_bh_q_value"), s.get("n_tumor_samples"))
    if cid == "tumor-scrna-celltype-expression":
        n = h.get("sc_n_donor_groups") or s.get("n_donor_groups")
        return "high" if isinstance(n, int) and n >= 100 else "moderate" if isinstance(n, int) and n >= 20 else "low"
    if cid == "tumor-rna-distribution":
        n = s.get("n_tumor_samples")
        return "high" if isinstance(n, int) and n >= 100 else "moderate" if isinstance(n, int) and n >= 30 else "low"
    return "moderate"


def render_card_board_svg(cards: list, headline: dict, target: str, indication: str) -> str:
    by_id = {c["card_id"]: (c.get("summary") or {}) for c in (cards or [])}
    groups = {}
    for cid, claim, field, role in _SPEC:
        s = by_id.get(cid, {})
        val = s.get(field)
        b = _bucket(val, role)
        rel = "" if b == "not_measured" else _reliability(cid, s, headline)
        groups.setdefault(claim, []).append((cid, val, b, rel))
    order = [g for g in "ABCDRW" if g in groups]
    nrows = sum(len(groups[g]) for g in order)
    W = 540
    H = 40 + len(order) * 20 + nrows * 18 + 24
    x0 = 14
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'font-family="Inter, Helvetica, Arial, sans-serif"><rect width="{W}" height="{H}" fill="#fff"/>',
        f'<text x="{x0}" y="18" font-size="13" font-weight="700" fill="#1a1a19">{_esc(target)} · {_esc(indication)} — card board</text>',
        f'<text x="{x0}" y="32" font-size="9.5" fill="#6b6f76">every card bucketed under its claim · '
        f"● signal  ○ no signal (measured neg)  ▨ not measured (gap)  ▲ normal liability</text>",
    ]
    y = 48
    for g in order:
        out.append(
            f'<text x="{x0}" y="{y + 10}" font-size="10" font-weight="700" fill="#6b6f76">{_esc(_GROUP[g])}</text>'
        )
        y += 18
        for cid, val, b, rel in groups[g]:
            glyph, col = _GLYPH.get(b, ("?", "#888"))
            out.append(f'<text x="{x0 + 10}" y="{y + 10}" font-size="12" fill="{col}">{glyph}</text>')
            out.append(f'<text x="{x0 + 26}" y="{y + 10}" font-size="10" fill="#1a1a19">{_esc(cid)}</text>')
            out.append(f'<text x="{x0 + 250}" y="{y + 10}" font-size="9.5" fill="#555">{_esc(val)}</text>')
            if rel:
                for j in range(3):
                    fill = col if j < _RELDOT.get(rel, 0) else "none"
                    out.append(
                        f'<circle cx="{x0 + 470 + j * 11}" cy="{y + 6}" r="3" fill="{fill}" stroke="#184f95" stroke-width="0.8"/>'
                    )
            y += 18
    out.append("</svg>")
    return "\n".join(out)


def emit_card_board_figure(decision: dict, figures_root) -> list:
    """Emit figure_card_board.{svg,json} — the per-card ternary grouped by claim. Additive /
    best-effort; returns [] when no cards are present."""
    cards = (decision or {}).get("cards") or []
    headline = (decision or {}).get("headline") or {}
    if not cards:
        return []
    figures_root = Path(figures_root)
    figures_root.mkdir(parents=True, exist_ok=True)
    target = decision.get("target", "")
    indication = decision.get("indication", "") or "pan-cancer"
    svg = figures_root / "figure_card_board.svg"
    js = figures_root / "card_board.json"
    # structured twin
    by_id = {c["card_id"]: (c.get("summary") or {}) for c in cards}
    board = {}
    for cid, claim, field, role in _SPEC:
        s = by_id.get(cid, {})
        val = s.get(field)
        b = _bucket(val, role)
        board.setdefault(claim, []).append(
            {
                "card": cid,
                "value": val,
                "bucket": b,
                "reliability": ("" if b == "not_measured" else _reliability(cid, s, headline)),
            }
        )
    svg.write_text(render_card_board_svg(cards, headline, target, indication), encoding="utf-8")
    js.write_text(json.dumps(board, indent=2, default=str), encoding="utf-8")
    return [svg, js]


__all__ = ["render_card_board_svg", "emit_card_board_figure"]
