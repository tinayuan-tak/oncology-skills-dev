"""composite_panel — render a target-profile "at a glance" composite figure.

Layout: 3×2 grid of verdict badges, one per major phase (A/B/C/F/H + K
summary). Each badge shows:
  - Phase letter + sub-skill name
  - Verdict class (color-coded)
  - Driving rule id
  - 2-3 key metrics from the underlying card summary

Design rationale: composed target-profile output needs ONE slide-droppable
image that captures the whole target-in-indication picture. Card-level
figures (4-panel forest, box+strip) are too detailed for a summary panel.
Text-based verdict badges give a clean glance without hiding the numbers.

Emitted as PNG at 300 DPI + SVG. Consumed by target-profile.scripts.run
via _skills_common.write_package's figures/ slot.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


# Color palette — muted, print-safe, colorblind-considered.
VERDICT_COLORS = {
    # Strong-supportive (green family)
    "strong_tumor_selective":         "#0a2540",
    "concordant_dependent":           "#0a2540",
    "pan_essential_killer":           "#5a1e1e",  # actually killer, dark red
    "biomarker_stratified_dependency": "#0a2540",
    "well_covered":                   "#0a2540",
    "strongly_upregulated_in_tumor":  "#0a2540",
    "broadly_high_expression":        "#0a2540",

    # Modest / partial-supportive (blue family)
    "modest_tumor_selective":         "#4a7c9e",
    "lineage_selective":              "#4a7c9e",
    "moderate_biomarker_dependency":  "#4a7c9e",
    "chemically_confirmed_genetic":   "#4a7c9e",
    "chemically_active":              "#4a7c9e",
    "lineage_restricted":             "#4a7c9e",
    "modestly_upregulated_in_tumor":  "#4a7c9e",
    "recurrent_lof_driver":           "#4a7c9e",
    "recurrent_missense_driver":      "#4a7c9e",

    # Neutral / caution (ochre)
    "tool_compound_only":             "#c07a20",
    "weakly_active":                  "#c07a20",
    "discordant_across_comparators":  "#c07a20",
    "discordant":                     "#c07a20",
    "broadly_moderate_expression":    "#c07a20",
    "mixed_pattern":                  "#c07a20",

    # Not-selective / no-signal (red-brown)
    "not_selective":                  "#a63d2e",
    "non_dependent":                  "#a63d2e",
    "chemically_unhit":               "#a63d2e",
    "broadly_low_expression":         "#a63d2e",
    "passenger_pattern":              "#a63d2e",

    # Uninformative / insufficient (gray)
    "not_informative":                "#888888",
    "insufficient":                   "#888888",
    "data_unavailable":               "#bbbbbb",
    "phase_not_yet_wired":            "#bbbbbb",
    None:                             "#bbbbbb",
}


# Phase → display metadata
PHASE_META = {
    "A": {"name": "Presence",       "sub_key": "expression"},
    "B": {"name": "Selectivity",    "sub_key": "selectivity"},
    "C": {"name": "Requirement",    "sub_key": "dependency"},
    "F": {"name": "Tractability",   "sub_key": "tractability"},
    "H": {"name": "Population",     "sub_key": "population"},
    "K": {"name": "Overall",        "sub_key": "_overall"},
}


def _metric_lines_for(short: str, sub_result: dict) -> list[str]:
    """Return up to 3 short metric lines to render inside the badge for the
    given sub-skill. Reads from `sub_result['cards'][*]['summary']` fields
    the sub-skill's cards actually expose."""
    if short == "_overall":
        return []
    cards = sub_result.get("cards") or []
    if not cards:
        return []
    # Take first card's summary as the "primary" for the badge.
    s = (cards[0].get("summary") or {})

    if short == "expression":
        m = s.get("median_log2tpm_panel")
        f = s.get("fraction_expressed")
        return [
            f"median log2TPM: {m:.2f}" if isinstance(m, (int, float)) else "",
            f"expressed in: {f*100:.0f}% cell lines" if isinstance(f, (int, float)) else "",
        ]
    if short == "selectivity":
        cs = s.get("cells_supporting")
        cr = s.get("cells_ran")
        m = s.get("max_abs_log2fc")
        return [
            f"supporting: {int(cs)}/{int(cr)}" if cs is not None and cr else "",
            f"max |log2FC|: {m:.2f}" if isinstance(m, (int, float)) else "",
            f"discordant: {s.get('discordant')}" if s.get("discordant") is not None else "",
        ]
    if short == "dependency":
        # First card is CRISPR distribution
        return [
            f"median CRISPR: {s.get('median_chronos_indication'):.2f}"
            if isinstance(s.get("median_chronos_indication"), (int, float)) else "",
            f"pct dependent: {s.get('pct_dependent_indication'):.1f}%"
            if isinstance(s.get("pct_dependent_indication"), (int, float)) else "",
        ]
    if short == "tractability":
        return [
            f"n compounds: {s.get('n_compounds_screened')}"
            if s.get("n_compounds_screened") is not None else "",
            f"activity class: {s.get('activity_class') or ''}",
        ]
    if short == "population":
        f = s.get("overall_mutation_frequency")
        hs = s.get("hotspot_frequencies")
        top = hs[0] if isinstance(hs, list) and hs else None
        return [
            f"mut freq: {f*100:.1f}%" if isinstance(f, (int, float)) else "",
            f"top hotspot: {top.get('protein_change')} ({top.get('frequency')*100:.1f}%)"
            if top and isinstance(top.get("frequency"), (int, float)) else "",
        ]
    if short == "mutation":
        # not currently in the 6-panel layout; kept for future
        return [
            f"landscape: {s.get('mutation_landscape_class') or ''}",
        ]
    return []


def render_composite_panel(
    out_path: Path,
    target: str,
    indication: str,
    sub_results: dict,
    llm_output: Optional[dict] = None,
) -> Path:
    """Render the 3×2 composite panel as PNG (300 DPI) + companion SVG.

    Args:
        out_path: destination PNG path. Companion SVG written alongside.
        target, indication: for the title
        sub_results: dict keyed by short name (expression / selectivity /
            dependency / tractability / population), each with cards +
            verdict tuple. Missing keys render as "not covered".
        llm_output: optional target-profile LLM output. If supplied, the
            "Overall" panel uses recommendation + confidence + one-line
            executive-summary excerpt.

    Returns:
        Path to the written PNG.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(2, 3, figsize=(15, 8.5))
    fig.suptitle(f"{target} in {indication} — target-profile at a glance",
                 fontsize=13, weight="bold", y=0.98)

    phase_order = ["A", "B", "C", "F", "H", "K"]

    for idx, phase in enumerate(phase_order):
        row, col = divmod(idx, 3)
        ax = axes[row, col]
        ax.set_axis_off()

        meta = PHASE_META[phase]
        short = meta["sub_key"]

        # Fetch verdict + rule
        if short == "_overall" and llm_output:
            def _val(field):
                raw = llm_output.get(field)
                return raw.get("value") if isinstance(raw, dict) else raw
            verdict_str = _val("overall_recommendation") or "insufficient_evidence"
            driving = f"confidence: {_val('confidence') or '—'}"
            exec_summary = _val("executive_summary") or ""
            # First sentence, capped at 200 chars
            first_sent = exec_summary.split(". ")[0]
            if len(first_sent) > 200:
                first_sent = first_sent[:197] + "..."
            metric_lines = [first_sent] if first_sent else []
        else:
            r = sub_results.get(short) or {}
            v = r.get("verdict")
            if v is None:
                verdict_str = "no rule verdict"
                driving = "(raw metrics only)"
            else:
                verdict_str, driving = v
                driving = f"rule: {driving}"
            metric_lines = _metric_lines_for(short, r)
            metric_lines = [ln for ln in metric_lines if ln]

        color = VERDICT_COLORS.get(verdict_str, "#888888")

        # Draw the badge as a rounded rectangle
        box = FancyBboxPatch(
            (0.03, 0.03), 0.94, 0.94,
            boxstyle="round,pad=0.02",
            linewidth=2, edgecolor=color,
            facecolor=color, alpha=0.10,
            transform=ax.transAxes,
        )
        ax.add_patch(box)

        # Header: phase letter + name
        ax.text(0.05, 0.90, f"Phase {phase} · {meta['name']}",
                transform=ax.transAxes,
                fontsize=10, weight="bold", color="#333",
                va="top", ha="left")

        # Verdict — the big colored text
        # Wrap long verdicts
        display_verdict = verdict_str.replace("_", " ")
        if len(display_verdict) > 30:
            # Split into 2 lines at nearest space to midpoint
            mid = len(display_verdict) // 2
            left = display_verdict.rfind(" ", 0, mid)
            right = display_verdict.find(" ", mid)
            split_at = left if (mid - left) <= (right - mid) and left > 0 else right
            if split_at > 0:
                display_verdict = display_verdict[:split_at] + "\n" + display_verdict[split_at+1:]
        ax.text(0.05, 0.72, display_verdict,
                transform=ax.transAxes,
                fontsize=14 if len(display_verdict) < 25 else 12,
                weight="bold", color=color,
                va="top", ha="left")

        # Driving rule (smaller)
        ax.text(0.05, 0.48, driving,
                transform=ax.transAxes,
                fontsize=8, color="#666", style="italic",
                va="top", ha="left")

        # Metric lines
        y = 0.35
        for line in metric_lines[:3]:
            ax.text(0.05, y, line,
                    transform=ax.transAxes,
                    fontsize=9, color="#222", family="monospace",
                    va="top", ha="left")
            y -= 0.09

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    # Save PNG (300 dpi for slide-drop) + SVG (scalable)
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    svg_path = out_path.with_suffix(".svg")
    fig.savefig(svg_path, bbox_inches="tight")
    plt.close(fig)
    return out_path
