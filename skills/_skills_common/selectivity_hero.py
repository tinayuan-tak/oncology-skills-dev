"""Selectivity evidence-strip hero — a compact skill-level DISPLAY VIEW of tumor-selectivity's
tumor-vs-normal call across its INDEPENDENT comparators, for a dashboard tile.

WHAT THIS IS: a one-glance projection of decision['headline'] onto a verdict banner + a strip of
selectivity AXES (cross-comparator agreement, fold-change, per-sample percentile-crossing, in-cohort
rank, the normal-tissue WINDOW/veto, malignant-cell-intrinsic single-cell, in-situ spatial), each
scored supports / caution / opposes / unmeasured. Unlike tumor-presence's "is it there" matrix, the
selectivity question is a CONTRAST — "is the tumor-over-normal window real AND robust?" — so the hero
foregrounds concordance across comparators and, above all, whether the normal-breadth VETO closed the
window (the one case bulk fold-change gets wrong: a broadly-normal gene like TROP2/GAPDH).

WHAT THIS IS NOT — the honesty discipline (mirrors _skills_common.presence_matrix / ordinal_view):
  * NOT calibrated measurement. Each axis renders a categorical support-status (a color + WORD +
    value), never a hue alone; the status encodes direction-of-support, not a metric.
  * NOT a verdict input. A one-way VIEW over the already-resolved selectivity_class. It must NEVER
    feed a rule, resolver, gate, or nomination.
  * unmeasured / data_unavailable axes are OFF-SCALE — a hatched blank with the word "n/a", NEVER
    scored as "opposes". Absence of an axis is not evidence against selectivity.
  * The normal-tissue WINDOW axis is the safety-facing polarity: window CLOSED (veto fired) is drawn
    on the reserved status-red, because high expression in NORMAL tissue is a liability, not presence.
    The window veto is owned by the resolver/clamp; this only DISPLAYS its outcome.

Reads ONLY decision['headline'] (the computed spine) — no S3 re-read — so it is deterministic given a
decision.json and cheap to emit as an additive --figures artifact.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from _skills_common.figure_palette import esc as _esc

# The axis-A "selective" set is single-sourced in selectivity_veto (the veto owns which verdicts are
# downgradable); the hero reads it so the "window open" tile can never drift from the clamp's view.
from _skills_common.selectivity_veto import (
    _AXIS_A_SELECTIVE,
    _LIABILITY_VERDICT,
    _STROMAL_CONFOUND_VERDICT,
    _VETO_VERDICT,
)

# --- verdict → banner status (the resolved selectivity_class) --------------------------------------
# Green tiers = a supported tumor-over-normal window; red = window CLOSED by the normal-breadth veto;
# amber = discordant (comparators disagree); gray = not-selective / off. Substring match, specific first.
_VERDICT_STATUS = [
    ("strong_tumor_selective", ("good", "strong tumor-selective")),
    ("modest_tumor_selective", ("good", "modest tumor-selective")),
    ("field_effect_tumor_selective", ("good", "field-effect tumor-selective")),
    ("selective_but_broadly_normal", ("bad", "selective BUT broadly normal — window closed")),
    ("selective_but_stromal_confound", ("bad", "stroma-driven — NOT tumor-cell-intrinsic (false window)")),
    ("selective_with_normal_liability", ("warn", "selective — normal-tissue liability")),
    ("discordant_across_comparators", ("warn", "discordant across comparators")),
    ("not_selective", ("off", "not selective")),
    ("data_unavailable", ("na", "data unavailable")),
    ("insufficient", ("na", "insufficient evidence")),
]

_STATUS_FILL = {"good": "#0ca30c", "warn": "#fab219", "bad": "#d03b3b", "off": "#6b6f76", "na": "#b8bcc2"}
_STATUS_INK = {"good": "#ffffff", "warn": "#1a1a19", "bad": "#ffffff", "off": "#ffffff", "na": "#1a1a19"}
# ASCII-safe glyphs (× ! ✓ render across non-emoji fonts/SVG rasterizers). WORD is load-bearing (CVD).
_STATUS_ICON = {"good": "✓", "warn": "!", "bad": "×", "off": "–", "na": "·"}
_AXIS_WORD = {"good": "supports", "warn": "caution", "bad": "opposes", "off": "neutral", "na": "n/a"}


def _verdict_status(cls: Optional[str]) -> tuple[str, str]:
    if not cls:
        return ("na", "insufficient evidence")
    for token, res in _VERDICT_STATUS:
        if token in cls:
            return res
    return ("na", cls.replace("_", " "))


def _fnum(x, fmt="{:.1f}"):
    try:
        return fmt.format(float(x))
    except (TypeError, ValueError):
        return None


def build_selectivity_axes(headline: dict) -> dict:
    """Structured (testable) projection of headline onto the ordered selectivity AXES + the verdict
    banner. Returns a labeled VIEW — never a verdict input. Each axis carries a support-status
    ('good'|'warn'|'bad'|'off'|'na'), a short value string, and a one-line note."""
    h = headline or {}
    cls = h.get("selectivity_class")
    axis_a = h.get("axis_a_selectivity_class")
    driving = h.get("driving_rule_id")
    vetoed = cls == _VETO_VERDICT  # window CLOSED (housekeeping / no-window KILL)
    liability = cls == _LIABILITY_VERDICT  # window OPEN but a NON-origin critical-organ liability
    stromal_confound = cls == _STROMAL_CONFOUND_VERDICT  # INT-axis KILL: signal in the WRONG cells (CAF/stroma)
    axes: list[dict] = []

    def add(key, label, status, value, note):
        axes.append({"key": key, "label": label, "status": status, "value": value, "note": note})

    # 1. cross-comparator agreement (the four-cell DESeq2 sensitivity design)
    cs, cr = h.get("cells_supporting"), h.get("cells_ran")
    disc = h.get("discordant")
    if cr:
        frac = (cs or 0) / cr if cr else 0
        st = "bad" if disc else ("good" if frac >= 0.99 else ("warn" if frac > 0 else "off"))
        add(
            "comparators",
            "Cross-comparator",
            st,
            f"{int(cs or 0)}/{int(cr)} agree" + (" · discordant" if disc else ""),
            "independent tumor-vs-normal contrasts (TCGA-adjacent raw + ComBat, GTEx)",
        )
    else:
        add("comparators", "Cross-comparator", "na", "n/a", "no comparator cells ran")

    # 2. fold-change magnitude + direction
    fc = h.get("max_abs_log2fc")
    dr = h.get("dominant_direction")
    fcs = _fnum(fc)
    if fcs is not None:
        up = dr == "up"
        st = "off" if not up else ("good" if float(fc) >= 1.0 else "warn")
        add(
            "fold_change",
            "Fold-change",
            st,
            f"{'↑' if up else '↓'} {fcs} log2FC",
            "max |log2FC| across comparators + direction",
        )
    else:
        add("fold_change", "Fold-change", "na", "n/a", "no fold-change")

    # 3. per-sample percentile-crossing corroboration
    pcx = h.get("percentile_crossing_class")
    frac_p95 = h.get("fraction_tumor_above_normal_p95")
    fps = _fnum(frac_p95, "{:.0%}")
    if pcx:
        st = "good" if "strongly" in pcx else ("warn" if ("enriched" in pcx or "moderate" in pcx) else "off")
        add(
            "crossing",
            "Per-sample crossing",
            st,
            (f"{fps} > normal p95" if fps else pcx.replace("_", " ")),
            "fraction of tumors above the matched-normal 95th percentile",
        )
    else:
        add("crossing", "Per-sample crossing", "na", "n/a", "no per-sample corroboration")

    # 4. in-cohort relative rank (where this gene's fold-change sits among all genes)
    pct = h.get("selectivity_allgene_percentile")
    pcls = h.get("selectivity_allgene_percentile_class")
    ps = _fnum(pct, "{:.0f}")
    if pcls:
        st = "good" if pcls in ("top_decile", "high") else ("warn" if pcls == "mid" else "off")
        add(
            "rank",
            "In-cohort rank",
            st,
            (f"{ps}th pct · {pcls}" if ps else pcls),
            "selectivity percentile vs all genes in-indication (context)",
        )
    else:
        add("rank", "In-cohort rank", "na", "n/a", "no in-cohort rank")

    # 5. NORMAL-TISSUE WINDOW — the veto axis (the one bulk fold-change gets wrong)
    if vetoed:
        add(
            "window",
            "Normal-tissue window",
            "bad",
            "CLOSED — no window",
            f"broadly expressed in normal tissue; veto: {driving or 'normal-breadth'}",
        )
    elif liability:
        organ = h.get("sc_normal_max_detection_cell_type")
        add(
            "window",
            "Normal-tissue window",
            "warn",
            "open · critical-organ liability",
            "a real tumor-vs-normal window, but expressed in a non-origin critical organ"
            + (f" ({organ})" if organ else "")
            + " — a safety/therapeutic-index liability (owned by on-target-safety), not loss of selectivity",
        )
    elif cls in _AXIS_A_SELECTIVE:
        add(
            "window",
            "Normal-tissue window",
            "good",
            "open",
            "tumor elevated over the worst critical normal — a therapeutic window",
        )
    else:
        add("window", "Normal-tissue window", "na", "n/a", "window axis not evaluated (target not axis-A selective)")

    # 6. malignant-cell-intrinsic (single-cell) — is the signal tumor cells or stroma/CAF?
    scf = h.get("sc_malignant_detection_fraction")
    caf = h.get("sc_caf_vs_malignant_class")
    sctc = h.get("sc_tumor_expression_class")
    scs = _fnum(scf, "{:.0%}")
    if sctc and sctc != "data_unavailable":
        # a fired stromal-confound veto = the signal is NOT in malignant cells → this axis OPPOSES
        if stromal_confound or h.get("sc_stromal_confound_class") == "stromal_confounded":
            st = "bad"
        else:
            st = (
                "good"
                if (caf == "caf_low" and "broadly" in (sctc or ""))
                else ("warn" if caf in ("caf_low", "caf_moderate") or "detected" in (sctc or "") else "off")
            )
        val = f"malignant {scs}" if scs else sctc.replace("_", " ")
        if caf:
            val += f" · {caf}"
        add(
            "malignant_intrinsic",
            "Malignant-intrinsic (sc)",
            st,
            val,
            "single-cell: is the selective signal in malignant cells vs stroma/CAF?",
        )
    else:
        add(
            "malignant_intrinsic",
            "Malignant-intrinsic (sc)",
            "na",
            "n/a",
            "no tumor single-cell coverage for this indication",
        )

    # 7. in-situ spatial (deconvolution-free tumour-compartment enrichment)
    spr = h.get("spatial_rna_class")
    adj = h.get("spatial_normal_epithelium_adjacency_fraction")
    if spr and spr != "data_unavailable":
        st = "good" if "enriched" in spr else ("warn" if "present" in spr else "off")
        note = "in-situ tumour-vs-microenvironment RNA enrichment (GeoMx WTA)"
        if adj is not None:
            note += f"; normal-epithelium adjacency {_fnum(adj, '{:.2%}')}"
        add("spatial", "In-situ spatial", st, spr.replace("_", " "), note)
    else:
        add("spatial", "In-situ spatial", "na", "n/a", "no spatial coverage for this indication")

    # 8. absolute surface density (modality context — verdict-inert, informational)
    dcl = h.get("absolute_surface_density_class")
    cpc = h.get("absolute_copies_per_cell")
    cps = _fnum(cpc, "{:,.0f}")
    if dcl and dcl not in ("no_absolute_measurement", "data_unavailable"):
        st = "good" if dcl in ("high", "very_high") else ("warn" if dcl == "moderate" else "off")
        add(
            "density",
            "Absolute density",
            st,
            (f"{cps}/cell · {dcl}" if cps else dcl),
            "calibrated surface copies/cell (modality context)",
        )
    else:
        add("density", "Absolute density", "na", "n/a", "no calibrated absolute-density anchor")

    v_status, v_label = _verdict_status(cls)
    return {
        "target_verdict": cls,
        "verdict_status": v_status,
        "verdict_label": v_label,
        "axis_a_selectivity_class": axis_a,
        "vetoed": vetoed,
        "liability": liability,
        "stromal_confound": stromal_confound,
        "driving_rule_id": driving,
        "axes": axes,
        "_disclaimer": (
            "SELECTIVITY EVIDENCE STRIP — a display projection of decision['headline'] across the "
            "independent tumor-vs-normal comparators. NOT calibrated measurement, NOT a verdict input; "
            "n/a axes are coverage gaps, not evidence against selectivity. The normal-tissue WINDOW "
            "axis DISPLAYS the normal-breadth veto outcome (owned by the resolver/clamp)."
        ),
    }


# --- SVG geometry (dashboard hero tile) ------------------------------------------------------------
_W = 720
_PAD = 16
_BANNER_H = 62
_TILE_W = 336
_TILE_H = 58
_TILE_GAP = 8
_COLS = 2


def render_selectivity_hero_svg(headline: dict, target: str, indication: str) -> str:
    """Render the selectivity evidence-strip hero to a standalone SVG string. Deterministic given
    `headline`. Display-only; see module docstring for the honesty discipline."""
    view = build_selectivity_axes(headline)
    axes = view["axes"]
    n = len(axes)
    rows = (n + _COLS - 1) // _COLS
    grid_h = rows * (_TILE_H + _TILE_GAP) - _TILE_GAP
    H = _PAD + 26 + _BANNER_H + 14 + grid_h + 26 + _PAD
    vstat = view["verdict_status"]
    s: list[str] = []
    s.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_W}" height="{H}" '
        f'viewBox="0 0 {_W} {H}" font-family="Inter, Helvetica, Arial, sans-serif">'
    )
    s.append(f'<rect x="0" y="0" width="{_W}" height="{H}" fill="#ffffff"/>')
    s.append(
        '<defs><pattern id="na_h" width="6" height="6" patternUnits="userSpaceOnUse" '
        'patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" stroke="#d5d7da" '
        'stroke-width="1.4"/></pattern></defs>'
    )
    # title
    s.append(
        f'<text x="{_PAD}" y="20" font-size="13" font-weight="700" fill="#1a1a19">'
        f"{_esc(target)} · {_esc(indication)} — tumor-vs-normal selectivity</text>"
    )

    # verdict banner
    by = _PAD + 26
    bfill = _STATUS_FILL.get(vstat, "#b8bcc2")
    bink = _STATUS_INK.get(vstat, "#1a1a19")
    s.append(
        f'<rect x="{_PAD}" y="{by}" width="{_W - 2 * _PAD}" height="{_BANNER_H}" rx="8" fill="{bfill}" opacity="0.95"/>'
    )
    s.append(
        f'<text x="{_PAD + 16}" y="{by + 25}" font-size="16" font-weight="800" fill="{bink}">'
        f"{_STATUS_ICON.get(vstat, '')}  {_esc(view['verdict_label'])}</text>"
    )
    sub = f"resolved selectivity_class: {view['target_verdict'] or 'insufficient'}"
    if view.get("stromal_confound") and view["axis_a_selectivity_class"]:
        sub = (
            f"axis-A: {view['axis_a_selectivity_class']}  →  STROMA-DRIVEN (not tumor-cell-intrinsic)  ·  "
            f"{view['driving_rule_id'] or ''}"
        )
    elif view["vetoed"] and view["axis_a_selectivity_class"]:
        sub = (
            f"axis-A: {view['axis_a_selectivity_class']}  →  VETOED (no therapeutic window)  ·  "
            f"{view['driving_rule_id'] or ''}"
        )
    elif view.get("liability") and view["axis_a_selectivity_class"]:
        sub = (
            f"axis-A: {view['axis_a_selectivity_class']}  →  SELECTIVE, normal-tissue liability  ·  "
            f"{view['driving_rule_id'] or ''}"
        )
    s.append(f'<text x="{_PAD + 16}" y="{by + 46}" font-size="10.5" fill="{bink}" opacity="0.92">{_esc(sub)}</text>')

    # axis tiles (2-col grid)
    gy = by + _BANNER_H + 14
    for i, ax in enumerate(axes):
        r, c = divmod(i, _COLS)
        x = _PAD + c * (_TILE_W + _TILE_GAP)
        y = gy + r * (_TILE_H + _TILE_GAP)
        st = ax["status"]
        if st == "na":
            s.append(
                f'<rect x="{x}" y="{y}" width="{_TILE_W}" height="{_TILE_H}" rx="6" '
                f'fill="url(#na_h)" stroke="#e3e4e6" stroke-width="1"/>'
            )
        else:
            s.append(
                f'<rect x="{x}" y="{y}" width="{_TILE_W}" height="{_TILE_H}" rx="6" '
                f'fill="#ffffff" stroke="#e3e4e6" stroke-width="1"/>'
            )
            # status pip
            s.append(
                f'<rect x="{x}" y="{y}" width="6" height="{_TILE_H}" rx="0" fill="{_STATUS_FILL.get(st, "#b8bcc2")}"/>'
            )
        # label
        s.append(
            f'<text x="{x + 16}" y="{y + 18}" font-size="10" font-weight="700" fill="#6b6f76" '
            f'letter-spacing="0.3">{_esc(ax["label"].upper())}</text>'
        )
        # value + status word
        pip = _STATUS_FILL.get(st, "#b8bcc2")
        val = ax["value"]
        if len(val) > 34:
            val = val[:33] + "…"
        s.append(
            f'<text x="{x + 16}" y="{y + 35}" font-size="12.5" font-weight="700" fill="#1a1a19">{_esc(val)}</text>'
        )
        s.append(
            f'<text x="{x + _TILE_W - 12}" y="{y + 18}" font-size="9.5" text-anchor="end" '
            f'font-weight="700" fill="{pip}">{_STATUS_ICON.get(st, "")} '
            f"{_esc(_AXIS_WORD.get(st, ''))}</text>"
        )
        note = ax["note"]
        if len(note) > 62:
            note = note[:61] + "…"
        s.append(f'<text x="{x + 16}" y="{y + 50}" font-size="8.8" fill="#8a8d91">{_esc(note)}</text>')

    # legend / disclaimer
    ly = gy + grid_h + 16
    s.append(
        f'<text x="{_PAD}" y="{ly}" font-size="8.5" fill="#8a8d91">'
        f"✓ supports · ! caution · × opposes/closed · · n/a (coverage gap, not counter-evidence) "
        f"— display view over the resolved verdict, not a verdict input</text>"
    )
    s.append("</svg>")
    return "\n".join(s)


def emit_selectivity_hero(decision: dict, figures_root) -> list[Path]:
    """Emit the selectivity hero into <figures_root>/figure_selectivity_evidence_strip.{svg,json}.

    ADDITIVE / best-effort — a skill-level aggregate figure read from decision['headline']. Returns
    written paths (empty if no headline / no verdict). Never raises for a missing field; the caller
    (run_wired_skill --figures hook) also guards."""
    headline = (decision or {}).get("headline") or {}
    if not headline.get("selectivity_class"):
        return []
    target = decision.get("target", "")
    indication = decision.get("indication", "") or "pan-cancer"
    figures_root = Path(figures_root)
    figures_root.mkdir(parents=True, exist_ok=True)
    svg_path = figures_root / "figure_selectivity_evidence_strip.svg"
    json_path = figures_root / "selectivity_evidence_strip.json"
    svg_path.write_text(render_selectivity_hero_svg(headline, target, indication), encoding="utf-8")
    json_path.write_text(json.dumps(build_selectivity_axes(headline), indent=2), encoding="utf-8")
    return [svg_path, json_path]


__all__ = ["build_selectivity_axes", "render_selectivity_hero_svg", "emit_selectivity_hero"]
