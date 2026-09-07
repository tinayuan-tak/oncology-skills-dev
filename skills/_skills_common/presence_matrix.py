"""Presence × Context hero matrix — a compact skill-level DISPLAY VIEW of tumor-presence's
`presence_verdict_by_modality`, for a dashboard tile.

WHAT THIS IS: an order-preserving projection of the per-(measurement, sample_context) presence
sub-verdicts onto a small state-matrix (measurement layers as rows × sample contexts as columns),
so a reader can see — at a glance — where the modalities AGREE and where they DISAGREE, and whether
the normal-tissue comparator opens or closes a therapeutic window.

WHAT THIS IS NOT — the honesty discipline that makes it safe (mirrors _skills_common.ordinal_view):
  * NOT calibrated measurement. The presence tiers preserve ORDER (absent < low < moderate < high);
    the gaps between them are NOT metric. The cell shows the categorical verdict LABEL + a color that
    encodes only its tier — never a number-alone.
  * NOT a verdict input. This is a one-way VIEW over the already-resolved `presence_verdict_by_modality`.
    It must NEVER feed back into a rule, resolver, gate, or nomination.
  * `data_unavailable` / missing cells are OFF-SCALE — rendered as a hatched blank, NEVER on the
    presence color ramp. An ABSENCE of measurement is not a low presence value.
  * The normal-tissue column is a COMPARATOR (framing), not a presence tier. It is drawn on the
    reserved status palette (window open/closed) with an icon + word — never the presence ramp —
    because high expression in NORMAL tissue is a safety LIABILITY, the opposite polarity of high
    expression in tumor. The safety VERDICT is owned by on-target-safety-liability, not here.

The renderer reads ONLY decision['headline'] (the computed reconciliation) — no S3 re-read — so it is
deterministic given a decision.json and cheap to emit as an additive --figures artifact.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from _skills_common.figure_palette import esc as _esc

# ---------------------------------------------------------------------------
# Layout: measurement layers (rows, RNA backbone first) × sample contexts (columns).
# The columns are split into a PRESENCE group (cell_line, tumor) and a WINDOW group
# (normal) with a physical gutter + group headers — the split encodes the polarity flip.
# ---------------------------------------------------------------------------
_ROWS = [
    ("bulk_rna", "Bulk RNA"),
    ("bulk_protein_ms", "Bulk protein (MS)"),
    ("sc_rna", "Single-cell RNA"),
    ("protein_ihc", "Protein IHC"),
]
_PRESENCE_COLS = [("cell_line", "Cell line"), ("tumor", "Tumor")]
_WINDOW_COLS = [("normal", "Normal tissue")]

# Presence-tier ORDINAL (order-preserving, NOT metric). Matched by substring against the verdict
# string so a new-but-related verdict acquires the right tier; an unknown verdict → None (neutral,
# never a fabricated rank). Keyed longest-first so specific tokens win.
_TIER_SUBSTRINGS = [
    # tier 3 — strong / broadly high
    ("broadly_high", 3),
    ("broadly_expressed", 3),
    ("strongly_upregulated", 3),
    ("malignant_broadly_detected", 3),
    ("broadly_detected", 3),
    # tier 2 — moderate
    ("broadly_moderate", 2),
    ("modestly_upregulated", 2),
    ("moderately_expressed", 2),
    ("modestly_up", 2),
    ("malignant_detected", 2),
    ("sc_malignant_detected", 2),
    # tier 1 — low / restricted / present-not-elevated
    ("lineage_restricted", 1),
    ("broadly_low", 1),
    ("sparsely", 1),
    ("present_not_elevated", 1),
    ("modestly_detected", 1),
    ("focally", 1),
    # tier 0 — measured NEGATIVE (a real absence, distinct from data_unavailable)
    ("not_expressed", 0),
    ("protein_absent", 0),
    ("not_detected", 0),
    ("absent", 0),
]

# Light-mode presence ramp (sequential blue, ordinal floor ≥ step 250 per the dataviz palette).
# tier None → neutral "measured, un-ranked" gray (on-scale but no ramp position).
_TIER_FILL = {
    3: "#184f95",
    2: "#2a78d6",
    1: "#5598e7",
    0: "#c9def7",
    None: "#b8bcc2",
}
_TIER_INK = {3: "#ffffff", 2: "#ffffff", 1: "#0b1f3a", 0: "#0b1f3a", None: "#1a1a19"}
_TIER_WORD = {3: "high", 2: "moderate", 1: "low", 0: "absent", None: "measured"}

# Window/normal comparator → reserved status palette (fixed; icon+word carry meaning, never hue alone).
_STATUS_SUBSTRINGS = [
    ("high_liability", "critical"),
    ("broad_normal", "critical"),
    ("origin_tissue_liability", "critical"),
    ("broadly_expressed", "critical"),
    ("ubiquitous", "critical"),
    ("moderate", "warning"),
    ("partial", "warning"),
    ("restricted_normal", "warning"),
    ("focal", "warning"),
    ("low_liability", "good"),
    ("absent", "good"),
    ("not_detected", "good"),
    ("low", "good"),
]
_STATUS_FILL = {"critical": "#d03b3b", "warning": "#fab219", "good": "#0ca30c"}
# ASCII-safe glyphs (× ! ✓ render across non-emoji fonts / SVG rasterizers; emoji ⛔⚠ do not).
# CVD discipline: the WORD is the load-bearing channel; the glyph + color are reinforcement.
_STATUS_ICON = {"critical": "×", "warning": "!", "good": "✓"}  # × ! ✓
_STATUS_WORD = {"critical": "liability", "warning": "caution", "good": "window"}

_OFFSCALE_FILL = "#f0f0ee"  # data_unavailable — hatched blank
_OFFSCALE_INK = "#8a8d91"


def _tier_of(verdict: Optional[str]) -> Optional[int]:
    """Presence tier (3..0) or None (unknown → no fabricated rank). Substring match, most-specific first."""
    if not verdict:
        return None
    v = verdict.lower()
    for token, tier in _TIER_SUBSTRINGS:
        if token in v:
            return tier
    return None


def _status_of(verdict: Optional[str]) -> Optional[str]:
    """Normal-tissue comparator → status role ('critical'|'warning'|'good') or None if unknown."""
    if not verdict:
        return None
    v = verdict.lower()
    for token, role in _STATUS_SUBSTRINGS:
        if token in v:
            return role
    return None


def _sc_detail(headline: Optional[dict]) -> dict:
    """The single-cell detail block projected from the headline's sc_* fields. `measured` is True only
    when the sc_rna/tumor bucket carried a real read (sc_expression_class ∉ {None, data_unavailable})."""
    h = headline or {}
    cls = h.get("sc_expression_class")
    return {
        "measured": bool(cls) and cls != "data_unavailable",
        "sc_expression_class": cls,
        "malignant_detection_fraction": h.get("sc_malignant_detection_fraction"),
        "tce_homogeneity_class": h.get("sc_tce_homogeneity_class"),
        "caf_vs_malignant_class": h.get("sc_caf_vs_malignant_class"),
        "top_microenvironment_compartment": h.get("sc_top_microenvironment_compartment"),
        "compartment_detection": h.get("sc_compartment_detection") or {},
        "n_donor_groups": h.get("sc_n_donor_groups"),
        "n_datasets": h.get("sc_n_datasets"),
    }


def build_matrix_cells(headline: dict) -> dict:
    """Structured (testable) projection of headline['presence_verdict_by_modality'] onto the
    row×col grid. Returns a labeled VIEW — never a verdict input. Off-scale (data_unavailable)
    and comparator cells are flagged so the renderer can keep them OFF the presence ramp."""
    pvm = (headline or {}).get("presence_verdict_by_modality") or {}
    driving = (headline or {}).get("driving_rule_id")
    cells: dict[str, dict] = {}
    for meas, _ in _ROWS:
        for ctx, _ in _PRESENCE_COLS + _WINDOW_COLS:
            key = f"{meas}/{ctx}"
            bucket = pvm.get(key) or {}
            verdict = bucket.get("verdict")
            ev = bucket.get("evidence_state")  # measured | comparator | data_unavailable | None
            is_window = ctx == "normal"
            cell = {
                "measurement": meas,
                "sample_context": ctx,
                "key": key,
                "verdict": verdict,
                "evidence_state": ev,
                "group": "window" if is_window else "presence",
                "present": bool(bucket),
                "is_headline_lens": (driving is not None and bucket.get("driving_rule_id") == driving),
            }
            if is_window:
                cell["status"] = _status_of(verdict) if ev == "comparator" else None
                cell["tier"] = None
            else:
                cell["tier"] = _tier_of(verdict) if ev == "measured" else None
                cell["status"] = None
            cells[key] = cell
    return {
        "cells": cells,
        "collapsed_verdict": (headline or {}).get("presence_verdict"),
        "driving_rule_id": driving,
        "headline_lens": (headline or {}).get("headline_lens"),
        "cell_line_vs_tumor_discordant": (headline or {}).get("cell_line_vs_tumor_discordant"),
        # Single-cell detail (verdict-inert): the malignant-vs-microenvironment attribution + the
        # TCE-relevant homogeneity + CAF-confounder signals that bulk cannot give. Rendered as a compact
        # strip beneath the matrix and carried in the JSON twin. Empty/None when sc is not measured.
        "sc_detail": _sc_detail(headline),
        "_disclaimer": (
            "PRESENCE × CONTEXT VIEW — an order-preserving projection of the per-(measurement, "
            "sample_context) presence sub-verdicts for display ONLY. NOT calibrated measurement "
            "(tier gaps are not metric); NOT a verdict input; data_unavailable cells are off-scale "
            "(coverage gaps, not low presence); the normal column is a safety COMPARATOR whose "
            "verdict is owned by on-target-safety-liability."
        ),
    }


def _short_verdict(verdict: Optional[str]) -> str:
    """Compact cell label from a presence verdict: drop the leading measurement prefix and the trailing
    `_expression` (redundant — the row label already names the measurement), so the label fits the cell
    on at most two wrapped lines (e.g. `broadly_moderate_expression` → `broadly moderate`)."""
    if not verdict:
        return ""
    v = verdict
    for pre in ("tumor_", "protein_", "sc_", "expression_"):
        if v.startswith(pre):
            v = v[len(pre) :]
            break
    if v.endswith("_expression"):
        v = v[: -len("_expression")]
    return v.replace("_", " ")


def _wrap_two_lines(text: str, max_chars: int) -> list[str]:
    """Greedily pack `text` into AT MOST two lines of ~max_chars, so a verdict label is fully readable
    inside a cell instead of being ellipsis-truncated. Overflow past two lines is folded into the second
    line with a trailing ellipsis (rare — presence verdicts are ≤3-4 words). A single over-long word is
    truncated so it can never overrun the cell."""
    words = str(text).split()
    if not words:
        return [""]
    lines: list[str] = []
    cur = ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if len(cand) <= max_chars or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > 2:  # fold any remainder into line 2
        lines = [lines[0], " ".join(lines[1:])]
    if len(lines) == 2 and len(lines[1]) > max_chars:
        lines[1] = lines[1][: max_chars - 1] + "…"
    if len(lines) == 1 and len(lines[0]) > max_chars:  # single unbreakable long token
        lines[0] = lines[0][: max_chars - 1] + "…"
    return lines


# --- SVG geometry (compact dashboard tile) --------------------------------
_RL = 132  # row-label gutter
_CW = 96  # presence cell width (wide enough for a wrapped 2-line verdict label)
_NW = 132  # normal (window) cell width
_CH = 42  # cell height (fits two label lines without truncation)
_GAP = 4
_GUT = 14  # gutter between presence + window groups
_TOP = 52  # header band
_BOT = 76  # eyebrow band (collapsed verdict + discordance + single-cell strip + legend)


def render_presence_matrix_svg(headline: dict, target: str, indication: str) -> str:
    """Render the Presence × Context hero matrix to a standalone SVG string. Deterministic given
    `headline` (decision['headline']). Display-only; see module docstring for the honesty discipline."""
    view = build_matrix_cells(headline)
    cells = view["cells"]
    n_pres = len(_PRESENCE_COLS)
    grid_w = _RL + n_pres * _CW + (n_pres - 1) * _GAP + _GUT + _NW
    grid_h = _TOP + len(_ROWS) * (_CH + _GAP) + _BOT
    W, H = grid_w + 44, grid_h + 12  # right padding so the WINDOW group header never clips
    x0 = 12

    def col_x(i: int, group: str) -> float:
        if group == "presence":
            return x0 + _RL + i * (_CW + _GAP)
        return x0 + _RL + n_pres * (_CW + _GAP) + _GUT  # single window col

    s: list[str] = []
    s.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="Inter, Helvetica, Arial, sans-serif">'
    )
    s.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff"/>')
    # diagonal-hatch pattern for off-scale (data_unavailable) cells
    s.append(
        '<defs><pattern id="na" width="6" height="6" patternUnits="userSpaceOnUse" '
        'patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" '
        'stroke="#d5d7da" stroke-width="1.4"/></pattern></defs>'
    )
    # title
    s.append(
        f'<text x="{x0}" y="20" font-size="13" font-weight="700" fill="#1a1a19">'
        f"{_esc(target)} · {_esc(indication)}</text>"
    )
    s.append(
        f'<text x="{x0}" y="36" font-size="10.5" fill="#6b6f76">Presence × context '
        f"(per-modality sub-verdicts) — display view, not a verdict</text>"
    )

    # group headers
    pres_x = col_x(0, "presence")
    pres_w = n_pres * _CW + (n_pres - 1) * _GAP
    win_x = col_x(0, "window")
    s.append(
        f'<text x="{pres_x}" y="{_TOP - 6}" font-size="10" font-weight="700" '
        f'fill="#2a78d6" letter-spacing="0.5">PRESENCE — is it there?</text>'
    )
    s.append(
        f'<text x="{win_x}" y="{_TOP - 6}" font-size="10" font-weight="700" '
        f'fill="#8a4b1a" letter-spacing="0.5">WINDOW — spared?</text>'
    )
    # gutter divider
    div_x = pres_x + pres_w + _GUT / 2
    s.append(
        f'<line x1="{div_x}" y1="{_TOP - 2}" x2="{div_x}" y2="{_TOP + len(_ROWS) * (_CH + _GAP) - _GAP + 4}" '
        f'stroke="#e3e4e6" stroke-width="2"/>'
    )
    # column sublabels
    for i, (_, clabel) in enumerate(_PRESENCE_COLS):
        cx = col_x(i, "presence")
        s.append(
            f'<text x="{cx + _CW / 2}" y="{_TOP + 8}" font-size="9.5" text-anchor="middle" '
            f'fill="#6b6f76">{_esc(clabel)}</text>'
        )
    s.append(
        f'<text x="{win_x + _NW / 2}" y="{_TOP + 8}" font-size="9.5" text-anchor="middle" '
        f'fill="#6b6f76">{_esc(_WINDOW_COLS[0][1])}</text>'
    )

    # rows
    for r, (meas, rlabel) in enumerate(_ROWS):
        cy = _TOP + 14 + r * (_CH + _GAP)
        s.append(
            f'<text x="{x0}" y="{cy + _CH / 2 + 4}" font-size="10.5" font-weight="600" '
            f'fill="#1a1a19">{_esc(rlabel)}</text>'
        )
        # presence cells
        for i, (ctx, _) in enumerate(_PRESENCE_COLS):
            _draw_cell(s, cells[f"{meas}/{ctx}"], col_x(i, "presence"), cy, _CW)
        # window cell
        _draw_cell(s, cells[f"{meas}/normal"], win_x, cy, _NW)

    # eyebrow: collapsed verdict + driving lens + discordance
    ey = _TOP + len(_ROWS) * (_CH + _GAP) + 16
    cv = view["collapsed_verdict"] or "insufficient"
    lens = view["headline_lens"]
    star = " ★" if lens else ""
    s.append(
        f'<text x="{x0}" y="{ey}" font-size="10.5" fill="#1a1a19">'
        f'<tspan font-weight="700">Collapsed verdict:</tspan> {_esc(cv)}'
        f"{_esc(f'  (driven by {star} {lens})' if lens else '')}</text>"
    )
    sc_y = ey + 15
    if view["cell_line_vs_tumor_discordant"]:
        s.append(
            f'<text x="{x0}" y="{sc_y}" font-size="9.5" fill="#8a4b1a">'
            f"▸ one-word verdict understates tumor presence — read the tumor row, "
            f"not the headline</text>"
        )
        sc_y += 15
    # single-cell detail strip: malignant-vs-microenvironment attribution + TCE homogeneity + CAF
    # confounder — the signals bulk cannot give. Text-led (never color alone).
    _render_sc_strip(s, view.get("sc_detail") or {}, x0, sc_y)
    # legend
    s.append(
        f'<text x="{x0}" y="{H - 6}" font-size="8.5" fill="#8a8d91">'
        f"■ presence tier (order, not magnitude) · hatched = not measured · "
        f"×/!/✓ = normal-tissue comparator</text>"
    )
    s.append("</svg>")
    return "\n".join(s)


def _render_sc_strip(s: list, sc: dict, x0: float, y: float) -> None:
    """Append the single-cell detail line to the SVG. Shows the malignant detection fraction,
    homogeneity class, and CAF-vs-malignant class when single-cell is measured; an honest
    'not measured' otherwise. Verdict-inert display only."""
    if not sc.get("measured"):
        s.append(
            f'<text x="{x0}" y="{y}" font-size="9.5" fill="#8a8d91">'
            f'<tspan font-weight="700" fill="#6b6f76">Single-cell (tumor):</tspan> '
            f"not measured for this indication</text>"
        )
        return
    frac = sc.get("malignant_detection_fraction")
    bits = [f"{round(frac * 100)}% of malignant cells" if isinstance(frac, (int, float)) else "detected"]
    if sc.get("tce_homogeneity_class") and sc["tce_homogeneity_class"] != "data_unavailable":
        bits.append(_esc(str(sc["tce_homogeneity_class"]).replace("_", " ")))
    caf = sc.get("caf_vs_malignant_class")
    _caf_label = {
        "caf_low": "CAF-low",
        "caf_dominant": "CAF-dominant",
        "malignant_dominant": "malignant-dominant",
        "shared_caf_malignant": "CAF+malignant",
    }
    if caf and caf != "data_unavailable":
        bits.append(_esc(_caf_label.get(caf, str(caf).replace("_", " "))))
    nd, nds = sc.get("n_donor_groups"), sc.get("n_datasets")
    if isinstance(nd, int) and isinstance(nds, int):
        bits.append(f"{nd} donors / {nds} datasets")
    s.append(
        f'<text x="{x0}" y="{y}" font-size="9.5" fill="#1a1a19">'
        f'<tspan font-weight="700" fill="#b2182b">Single-cell (tumor):</tspan> '
        f"{' · '.join(bits)}</text>"
    )


def _draw_cell(s: list, cell: dict, x: float, y: float, w: float) -> None:
    ev = cell.get("evidence_state")
    verdict = cell.get("verdict")
    is_window = cell["group"] == "window"
    rx = 4
    if ev in (None, "data_unavailable") or not cell.get("present"):
        # OFF-SCALE — hatched blank, never on the ramp. Absence of measurement, not low presence.
        s.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{_CH}" rx="{rx}" '
            f'fill="url(#na)" stroke="#e3e4e6" stroke-width="1"/>'
        )
        s.append(
            f'<text x="{x + w / 2}" y="{y + _CH / 2 + 4}" font-size="11" text-anchor="middle" '
            f'fill="{_OFFSCALE_INK}">—</text>'
        )
        return
    if is_window:
        role = cell.get("status")
        fill = _STATUS_FILL.get(role, "#b8bcc2")
        icon = _STATUS_ICON.get(role, "")
        word = _STATUS_WORD.get(role, "")
        # comparator framing: dashed ring signals "not this skill's verdict"
        s.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{_CH}" rx="{rx}" fill="{fill}" '
            f'stroke="#ffffff" stroke-width="1" stroke-dasharray="3 2" opacity="0.92"/>'
        )
        s.append(
            f'<text x="{x + w / 2}" y="{y + _CH / 2 + 4}" font-size="10" text-anchor="middle" '
            f'font-weight="600" fill="#ffffff">{icon} {_esc(word)}</text>'
        )
        return
    # presence cell — ordinal ramp by tier + verdict LABEL (never color alone)
    tier = cell.get("tier")
    fill = _TIER_FILL.get(tier, _TIER_FILL[None])
    ink = _TIER_INK.get(tier, _TIER_INK[None])
    ring = (
        ' stroke="#0b1f3a" stroke-width="2"' if cell.get("is_headline_lens") else ' stroke="#e3e4e6" stroke-width="1"'
    )
    s.append(f'<rect x="{x}" y="{y}" width="{w}" height="{_CH}" rx="{rx}" fill="{fill}"{ring}/>')
    label = _short_verdict(verdict) or _TIER_WORD.get(tier, "")
    star = "★ " if cell.get("is_headline_lens") else ""
    # Wrap the full verdict across up to two lines (≈ w/6px per char at font 9) so it stays readable —
    # never ellipsis-truncate a label that would otherwise fit on two lines. The star marks the headline
    # lens on the first line.
    lines = _wrap_two_lines(label, max_chars=max(6, int((w - 8) / 5.2)))
    cx = x + w / 2
    if len(lines) == 1:
        s.append(
            f'<text x="{cx}" y="{y + _CH / 2 + 3.5}" font-size="9.5" text-anchor="middle" '
            f'fill="{ink}">{star}{_esc(lines[0])}</text>'
        )
    else:
        y0 = y + _CH / 2 - 4
        s.append(
            f'<text x="{cx}" y="{y0}" font-size="9" text-anchor="middle" fill="{ink}">{star}{_esc(lines[0])}</text>'
        )
        s.append(
            f'<text x="{cx}" y="{y0 + 11}" font-size="9" text-anchor="middle" fill="{ink}">{_esc(lines[1])}</text>'
        )


def emit_presence_matrix(decision: dict, figures_root) -> list[Path]:
    """Emit the hero matrix into <figures_root>/figure_presence_context_matrix.{svg,json}.

    ADDITIVE / best-effort — a skill-level aggregate figure read from the already-computed
    decision['headline']. Returns the list of written paths (empty if no headline). Never raises
    for a missing field; the caller (run_wired_skill --figures hook) also guards."""
    headline = (decision or {}).get("headline") or {}
    if not headline.get("presence_verdict_by_modality"):
        return []
    target = decision.get("target", "")
    indication = decision.get("indication", "") or "pan-cancer"
    figures_root = Path(figures_root)
    figures_root.mkdir(parents=True, exist_ok=True)
    svg_path = figures_root / "figure_presence_context_matrix.svg"
    json_path = figures_root / "presence_context_matrix.json"
    svg_path.write_text(render_presence_matrix_svg(headline, target, indication), encoding="utf-8")
    json_path.write_text(json.dumps(build_matrix_cells(headline), indent=2), encoding="utf-8")
    return [svg_path, json_path]


__all__ = [
    "build_matrix_cells",
    "render_presence_matrix_svg",
    "emit_presence_matrix",
]
