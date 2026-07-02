"""dge_deseq2.emit — matplotlib figure emitters for DGE-derived cards.

Separate from cli.py (which wraps the R DESeq2 pipeline) so the emitter has no
R dependency. Called from compose-dashboard's _figure_emitters.py at phase-2.

Public API:
    emit_tumor_vs_adjacent_compound(summary, per_sample_data, target, indication,
                                      out_dir, target_contracts_dir) -> Path
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional


def _load_takeda_palette(target_contracts_dir: Path):
    import matplotlib.pyplot as plt
    style_path = target_contracts_dir / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    sys.path.insert(0, str(target_contracts_dir / "plot_styles"))
    import takeda_palette
    return takeda_palette


def _placeholder_svg(msg_lines: list, out_path: Path, pal) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
    y = 0.7
    for line in msg_lines:
        ax.text(0.5, y, line, transform=ax.transAxes, ha="center",
                 fontsize=10 if y == 0.7 else 8, color="#444" if y == 0.7 else "#777")
        y -= 0.1
    ax.set_axis_off()
    fig.savefig(out_path); plt.close(fig)
    return out_path


def emit_tumor_vs_adjacent_compound(
    summary: dict,
    per_sample_data: Optional[dict],
    target: str,
    indication: str,
    out_dir: Path,
    target_contracts_dir: Path,
) -> Path:
    """Compound figure for expression-tumor-vs-adjacent card.

    Layout: 2-panel side-by-side.
      Panel A (left, 2/3 width): horizontal box + strip of log2(CPM+1) for
        Primary Tumor vs Solid Tissue Normal, from recount3 per-sample data.
      Panel B (right, 1/3 width): DGE stats callout (log2FC, q-value,
        expression_call_class, n_tumor/n_adjacent) with color-coded class label.

    Placeholder when per_sample_data is None (recount3 unavailable for the
    indication) or empty (no samples matched).
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    pal = _load_takeda_palette(target_contracts_dir)
    out_path = out_dir / "figure_tumor_vs_adjacent_compound.svg"

    if per_sample_data is None:
        return _placeholder_svg([
            f"{target} in {indication} — per-sample expression unavailable",
            "(recount3 does not cover this indication mapping)"
        ], out_path, pal)

    tumor = per_sample_data.get("tumor_samples") or []
    adj = per_sample_data.get("adjacent_samples") or []
    if not tumor and not adj:
        return _placeholder_svg([
            f"{target} in {indication} — no samples found",
            f"(gene_ensembl_id={per_sample_data.get('gene_ensembl_id')})"
        ], out_path, pal)

    tumor_vals = [s["log2_cpm"] for s in tumor]
    adj_vals = [s["log2_cpm"] for s in adj]

    fig = plt.figure(figsize=(pal.FIGSIZE_DOUBLE_COLUMN[0], pal.FIGSIZE_DOUBLE_COLUMN[1] * 1.1))
    gs = fig.add_gridspec(1, 3, width_ratios=[2, 2, 1.4], wspace=0.35)
    ax_box = fig.add_subplot(gs[0, :2])
    ax_txt = fig.add_subplot(gs[0, 2])

    # --- Panel A: box + strip ---
    groups = []
    labels = []
    colors = []
    if tumor_vals:
        groups.append(tumor_vals)
        labels.append(f"Primary Tumor\n(n={len(tumor_vals)})")
        colors.append("#0a2540")   # navy
    if adj_vals:
        groups.append(adj_vals)
        labels.append(f"Adjacent Normal\n(n={len(adj_vals)})")
        colors.append("#f0a020")   # ochre

    # Horizontal boxplot with fillcolors
    bp = ax_box.boxplot(
        groups, vert=False, widths=0.55, patch_artist=True,
        showfliers=False, medianprops={"color": "#222", "linewidth": 1.5},
    )
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.35)
        patch.set_edgecolor(color)
    for whisker in bp["whiskers"]:
        whisker.set_color("#666")
    for cap in bp["caps"]:
        cap.set_color("#666")

    # Overlay jittered strip
    rng = np.random.default_rng(seed=42)
    for i, (vals, color) in enumerate(zip(groups, colors)):
        yy = rng.uniform(i + 1 - 0.15, i + 1 + 0.15, size=len(vals))
        ax_box.scatter(vals, yy, s=8, color=color, alpha=0.55,
                        edgecolor="none", zorder=3)

    ax_box.set_yticks(range(1, len(labels) + 1))
    ax_box.set_yticklabels(labels, fontsize=8)
    ax_box.set_xlabel("log2(CPM + 1) — recount3 per-sample RNA-seq", fontsize=8)
    ax_box.set_title(f"{target} expression: tumor vs adjacent-normal in {indication}",
                       fontsize=9)
    ax_box.grid(axis="x", alpha=0.3, linewidth=0.5)
    # Group-median markers with values
    for i, vals in enumerate(groups):
        med = float(np.median(vals))
        ax_box.text(med, i + 1 - 0.35, f"{med:.2f}", ha="center",
                     va="top", fontsize=7, color="#222", weight="bold")

    # --- Panel B: DGE stats + class callout ---
    ax_txt.set_axis_off()
    log2_fc = summary.get("log2_fc")
    q_value = summary.get("q_value")
    n_tumor_dge = summary.get("n_tumor")
    n_adj_dge = summary.get("n_adjacent")
    cls = summary.get("expression_call_class", "data_unavailable")
    class_color = {
        "strong_upregulation": "#0a2540",
        "modest_upregulation": "#7fa7c0",
        "not_informative":     "#888888",
        "data_unavailable":    "#bbbbbb",
    }.get(cls, "#444")

    def _fmt(v, spec="+.2f"):
        try: return format(float(v), spec)
        except (TypeError, ValueError): return "NA"

    lines = [
        ("DGE stats", "bold", "#222"),
        ("(tumor vs adjacent-normal)", "italic", "#666"),
        ("", None, None),
        (f"log2 fold-change: {_fmt(log2_fc)}", "normal", "#222"),
        (f"q-value: {_fmt(q_value, '.2e')}", "normal", "#222"),
        (f"n_tumor: {n_tumor_dge if n_tumor_dge is not None else 'NA'}", "normal", "#222"),
        (f"n_adjacent: {n_adj_dge if n_adj_dge is not None else 'NA'}", "normal", "#222"),
        ("", None, None),
        ("class", "italic", "#666"),
        (cls.replace("_", " "), "bold", class_color),
    ]
    y = 0.95
    for text, style, color in lines:
        if text == "":
            y -= 0.03
            continue
        weight = "bold" if style == "bold" else "normal"
        fontstyle = "italic" if style == "italic" else "normal"
        ax_txt.text(0.02, y, text, transform=ax_txt.transAxes, ha="left", va="top",
                     fontsize=9 if style != "italic" else 8, weight=weight,
                     style=fontstyle, color=color)
        y -= 0.09

    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path
