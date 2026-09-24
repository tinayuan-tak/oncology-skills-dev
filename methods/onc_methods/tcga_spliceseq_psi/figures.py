"""tcga_spliceseq_psi.figures — figure emission functions for splicing visualizations.

Provides:
- emit_splicing_variability_pie: dual pie charts showing splicing variability in indication vs pan-cancer
- emit_splicing_variability_stacked: stacked panel comparing gene splicing variability rankings
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

DEFAULT_TARGET_CONTRACTS = Path(__file__).resolve().parents[3] / "target-contracts"


def ordinal(n: int) -> str:
    """Convert integer to ordinal string (1 -> '1st', 2 -> '2nd', etc.)."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def emit_splicing_variability_pie(
    target: str,
    indication: str,
    target_psi_std_indication: float,
    n_variable_events_indication: int,
    n_splice_events_indication: int,
    indication_gene_variabilities: list[tuple[str, float]],
    target_psi_std_pancancer: float,
    n_variable_events_pancancer: int,
    n_splice_events_pancancer: int,
    pancancer_gene_variabilities: list[tuple[str, float]],
    out_path: Path,
    contracts_root: Path = DEFAULT_TARGET_CONTRACTS,
) -> Optional[Path]:
    """Emit dual pie charts showing splicing variability in indication vs pan-cancer.

    Two donut-style pie charts side by side showing the max PSI standard deviation
    as a measure of splicing variability (0-0.5 scale, with 0.5 being maximum possible).

    Args:
        target: gene symbol
        indication: indication code (e.g., LUAD)
        target_psi_std_indication: target's max PSI std in indication (0-0.5)
        n_variable_events_indication: number of variable splice events in indication
        n_splice_events_indication: total splice events in indication
        indication_gene_variabilities: list of (gene, max_psi_std) for indication
        target_psi_std_pancancer: target's max PSI std pan-cancer
        n_variable_events_pancancer: number of variable splice events pan-cancer
        n_splice_events_pancancer: total splice events pan-cancer
        pancancer_gene_variabilities: list of (gene, max_psi_std) for pan-cancer
        out_path: directory to write figure
        contracts_root: path to target-contracts repo
    """
    sys.path.insert(0, str(contracts_root / "plot_styles"))
    try:
        from takeda_palette import (
            figure_title,
            provenance_tag,
        )
    except ImportError:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(5.5, 5.0))
        ax.text(0.5, 0.5, "takeda_palette not available", ha="center", va="center", transform=ax.transAxes)
        svg_path = out_path / "figure_splicing_variability_pie.svg"
        fig.savefig(svg_path, bbox_inches="tight")
        plt.close(fig)
        return svg_path

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    style_path = contracts_root / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))

    # Process gene variabilities for ranking
    if indication_gene_variabilities and isinstance(indication_gene_variabilities[0], (list, tuple)):
        gene_var_pairs = [(g, v) for g, v in indication_gene_variabilities if v is not None and v > 0]
    else:
        gene_var_pairs = []

    # Teal/cyan color scheme for splicing
    color_ind = "#008080"  # Teal for indication
    color_pan = "#333333"  # Black for pan-cancer

    # Create square figure with two pie charts
    fig = plt.figure(figsize=(5.5, 5.0))
    fig.subplots_adjust(top=0.85, bottom=0.15, left=0.10, right=0.90)

    # Two pie chart axes
    ax_pie_ind = fig.add_axes([0.08, 0.35, 0.38, 0.50])
    ax_pie_pan = fig.add_axes([0.54, 0.35, 0.38, 0.50])

    # For PSI std, max possible is 0.5 (when half samples have PSI=0 and half have PSI=1)
    # We'll show the PSI std as a fraction of this maximum
    max_possible_std = 0.5

    # Indication pie chart
    if target_psi_std_indication is not None:
        # Show PSI std as percentage of max possible (0.5)
        ind_pct = (target_psi_std_indication / max_possible_std) * 100
        ind_pct = min(ind_pct, 100)  # Cap at 100%
        ind_not = 100 - ind_pct

        ax_pie_ind.pie(
            [ind_pct, ind_not],
            colors=[color_ind, "#E8E8E8"],
            startangle=90,
            wedgeprops=dict(width=0.4, edgecolor="white", linewidth=1),
        )
        # Show actual PSI std value and variable events
        ax_pie_ind.text(0, 0.08, f"{target_psi_std_indication:.2f}", ha="center", va="center",
                        fontsize=12, fontweight="bold", color=color_ind)
        ax_pie_ind.text(0, -0.18, f"({n_variable_events_indication}/{n_splice_events_indication} variable)",
                        ha="center", va="center", fontsize=7, color=color_ind)
        ax_pie_ind.text(0, -1.1, f"{indication}", ha="center", va="top",
                        fontsize=9, fontweight="bold", color=color_ind)
        ax_pie_ind.set_aspect("equal")

    # Pan-cancer pie chart
    if target_psi_std_pancancer is not None:
        pan_pct = (target_psi_std_pancancer / max_possible_std) * 100
        pan_pct = min(pan_pct, 100)
        pan_not = 100 - pan_pct

        ax_pie_pan.pie(
            [pan_pct, pan_not],
            colors=[color_pan, "#E8E8E8"],
            startangle=90,
            wedgeprops=dict(width=0.4, edgecolor="white", linewidth=1),
        )
        ax_pie_pan.text(0, 0.08, f"{target_psi_std_pancancer:.2f}", ha="center", va="center",
                        fontsize=12, fontweight="bold", color=color_pan)
        ax_pie_pan.text(0, -0.18, f"({n_variable_events_pancancer}/{n_splice_events_pancancer} variable)",
                        ha="center", va="center", fontsize=7, color=color_pan)
        ax_pie_pan.text(0, -1.1, "Pan-Cancer", ha="center", va="top",
                        fontsize=9, fontweight="bold", color=color_pan)
        ax_pie_pan.set_aspect("equal")

    # Title and provenance
    figure_title(fig, target, None, "splicing variability", y=0.94)
    provenance_tag(fig, "TCGA SpliceSeq · max PSI std (0-0.5 scale)", y=0.90)

    # Calculate ranks
    ind_rank = None
    if gene_var_pairs:
        all_sorted_ind = sorted(gene_var_pairs, key=lambda x: x[1], reverse=True)
        for i, (gene, var) in enumerate(all_sorted_ind):
            if gene == target:
                ind_rank = i + 1
                break

    pan_rank = None
    if pancancer_gene_variabilities:
        if isinstance(pancancer_gene_variabilities[0], (list, tuple)):
            pan_pairs = [(g, v) for g, v in pancancer_gene_variabilities if v is not None and v > 0]
        else:
            pan_pairs = []
        if pan_pairs:
            all_sorted_pan = sorted(pan_pairs, key=lambda x: x[1], reverse=True)
            for i, (gene, var) in enumerate(all_sorted_pan):
                if gene == target:
                    pan_rank = i + 1
                    break

    # Captions with colored ranks
    caption_y = 0.28
    line_spacing = 0.05

    if ind_rank:
        fig.text(0.5, caption_y,
                 f"{target} is the {ordinal(ind_rank)} most variably spliced gene in {indication}",
                 ha="center", va="top", fontsize=10, color=color_ind, fontweight="bold")
    elif target_psi_std_indication is not None and target_psi_std_indication > 0:
        fig.text(0.5, caption_y,
                 f"{target} max PSI std in {indication}: {target_psi_std_indication:.2f}",
                 ha="center", va="top", fontsize=10, color=color_ind, fontweight="bold")
    else:
        fig.text(0.5, caption_y,
                 f"{target} has no splicing data in {indication}",
                 ha="center", va="top", fontsize=10, color=color_ind, fontweight="bold")

    if pan_rank:
        fig.text(0.5, caption_y - line_spacing,
                 f"{target} is the {ordinal(pan_rank)} most variably spliced gene pan-cancer",
                 ha="center", va="top", fontsize=10, color=color_pan, fontweight="bold")
    elif target_psi_std_pancancer is not None and target_psi_std_pancancer > 0:
        fig.text(0.5, caption_y - line_spacing,
                 f"{target} max PSI std pan-cancer: {target_psi_std_pancancer:.2f}",
                 ha="center", va="top", fontsize=10, color=color_pan, fontweight="bold")
    else:
        fig.text(0.5, caption_y - line_spacing,
                 f"{target} has no splicing data pan-cancer",
                 ha="center", va="top", fontsize=10, color=color_pan, fontweight="bold")

    svg_path = out_path / "figure_splicing_variability_pie.svg"
    fig.savefig(svg_path)
    plt.close(fig)
    return svg_path


def emit_splicing_variability_stacked(
    target: str,
    indication: str,
    target_psi_std_indication: float,
    indication_gene_variabilities: list[tuple[str, float]],
    target_psi_std_pancancer: float,
    pancancer_gene_variabilities: list[tuple[str, float]],
    out_path: Path,
    contracts_root: Path = DEFAULT_TARGET_CONTRACTS,
    *,
    min_psi_std: float = 0.10,
) -> Optional[Path]:
    """Emit a stacked figure with indication-specific (top) and pan-cancer (bottom) splicing variability.

    Args:
        target: gene symbol
        indication: indication code
        target_psi_std_indication: target's max PSI std in indication
        indication_gene_variabilities: list of (gene, max_psi_std) tuples for indication
        target_psi_std_pancancer: target's max PSI std pan-cancer
        pancancer_gene_variabilities: list of (gene, max_psi_std) tuples for pan-cancer
        out_path: directory to write figure
        contracts_root: path to target-contracts repo
        min_psi_std: minimum PSI std threshold for display (default 0.10)
    """
    if not indication_gene_variabilities:
        return None

    sys.path.insert(0, str(contracts_root / "plot_styles"))
    try:
        from takeda_palette import (
            REFLINE_NEUTRAL,
            figure_title,
            provenance_tag,
            takeaway,
        )
    except ImportError:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(7.0, 6.5))
        ax.text(0.5, 0.5, "takeda_palette not available", ha="center", va="center", transform=ax.transAxes)
        svg_path = out_path / "figure_splicing_variability_stacked.svg"
        fig.savefig(svg_path, bbox_inches="tight")
        plt.close(fig)
        return svg_path

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    style_path = contracts_root / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))

    # Process gene variabilities for both panels
    def process_genes(gene_list, target_name, target_var, threshold):
        if not gene_list:
            return [], 0
        if isinstance(gene_list[0], (list, tuple)):
            pairs = [(g, v) for g, v in gene_list if v is not None and v >= threshold]
        else:
            pairs = [(f"gene_{i}", v) for i, v in enumerate(gene_list) if v is not None and v >= threshold]
        pairs.sort(key=lambda x: x[1])
        total = len([g for g, v in gene_list if v is not None and v >= threshold])
        return pairs, total

    ind_genes, ind_total = process_genes(indication_gene_variabilities, target, target_psi_std_indication, min_psi_std)
    pan_genes, pan_total = process_genes(pancancer_gene_variabilities, target, target_psi_std_pancancer, min_psi_std)

    if not ind_genes and not pan_genes:
        return None

    # Teal color scheme for splicing
    color_target = "#008080"  # Teal for target
    color_other = "#A0D6D6"   # Light teal for others

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7.0, 6.5))
    fig.subplots_adjust(top=0.88, bottom=0.08, left=0.12, right=0.95, hspace=0.35)

    def plot_panel(ax, genes, target_var, panel_title, total_genes):
        if not genes:
            ax.text(0.5, 0.5, f"No genes with PSI std ≥{min_psi_std:.2f}",
                    ha="center", va="center", transform=ax.transAxes, fontsize=10, color="#888888")
            ax.set_xticks([])
            ax.set_yticks([])
            return

        names = [g for g, v in genes]
        vars_ = [v for g, v in genes]
        colors = [color_target if g == target else color_other for g, v in genes]

        ax.bar(range(len(names)), vars_, color=colors, edgecolor="white", linewidth=0.5)

        target_in_panel = target in names
        for i, (gene, var) in enumerate(genes):
            if gene == target:
                ax.annotate(
                    f"{gene} ({var:.2f})",
                    xy=(i, var),
                    xytext=(0, 4),
                    textcoords="offset points",
                    fontsize=7,
                    fontweight="bold",
                    color=color_target,
                    ha="center",
                    va="bottom",
                    rotation=90,
                )
            else:
                ax.annotate(
                    f"{gene} ({var:.2f})",
                    xy=(i, var),
                    xytext=(0, 4),
                    textcoords="offset points",
                    fontsize=5,
                    color="#888888",
                    ha="center",
                    va="bottom",
                    rotation=90,
                )

        if not target_in_panel and target_var is not None:
            ax.text(
                0.5, 0.85,
                f"{target} ({target_var:.2f}) — below {min_psi_std:.2f} threshold",
                ha="center", va="top", transform=ax.transAxes,
                fontsize=8, fontweight="bold", color=color_target,
                bbox=dict(boxstyle="round,pad=0.5", facecolor="#E0F0F0", edgecolor=color_target, linewidth=1),
            )

        ax.axhline(y=min_psi_std, **REFLINE_NEUTRAL, zorder=1)
        ax.set_xlim(-0.5, len(genes) - 0.5)
        ax.set_ylim(bottom=0, top=0.55)  # PSI std max is ~0.5
        ax.set_xticks([])
        ax.grid(axis="y", alpha=0.3)
        ax.set_ylabel("Max PSI Std", fontsize=9, color="#33383D")
        ax.set_title(f"{panel_title} ({len(genes)} genes with PSI std ≥{min_psi_std:.2f})",
                     fontsize=10, fontweight="bold", loc="left", color="#33383D")

    plot_panel(ax1, ind_genes, target_psi_std_indication, indication, ind_total)
    plot_panel(ax2, pan_genes, target_psi_std_pancancer, "Pan-Cancer", pan_total)

    figure_title(fig, target, None, "splicing variability", y=0.96)
    provenance_tag(fig, f"TCGA SpliceSeq · genes with max PSI std ≥{min_psi_std:.2f}", y=0.93)

    def get_rank(genes, target_name, target_var):
        sorted_desc = sorted(genes, key=lambda x: x[1], reverse=True)
        for i, (gene, var) in enumerate(sorted_desc):
            if gene == target_name or (target_var and abs(var - target_var) < 1e-9):
                return i + 1
        return None

    ind_rank = get_rank(ind_genes, target, target_psi_std_indication) if ind_genes else None
    pan_rank = get_rank(pan_genes, target, target_psi_std_pancancer) if pan_genes else None

    if ind_rank and pan_rank:
        take_text = (f"{target} is the {ordinal(ind_rank)} most variably spliced gene in {indication} "
                     f"and the {ordinal(pan_rank)} most variably spliced gene pan-cancer.")
    elif ind_rank:
        take_text = (f"{target} is the {ordinal(ind_rank)} most variably spliced gene in {indication} "
                     f"but is below the {min_psi_std:.2f} threshold pan-cancer.")
    elif pan_rank:
        take_text = (f"{target} is the {ordinal(pan_rank)} most variably spliced gene pan-cancer "
                     f"but is below the {min_psi_std:.2f} threshold in {indication}.")
    else:
        take_text = (f"{target} is below the {min_psi_std:.2f} splicing variability threshold "
                     f"in both {indication} and pan-cancer.")
    takeaway(fig, take_text, y=0.02)

    svg_path = out_path / "figure_splicing_variability_stacked.svg"
    fig.savefig(svg_path)
    plt.close(fig)
    return svg_path
