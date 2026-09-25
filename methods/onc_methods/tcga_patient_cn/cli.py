"""tcga_patient_cn.cli — figure emission functions for patient copy-number visualizations.

Provides:
- emit_cn_frequency_pie: dual pie charts showing amp/del frequency in indication vs pan-cancer
- emit_cn_frequency_stacked: stacked panel comparing indication vs pan-cancer gene rankings
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


def emit_cn_frequency_pie(
    target: str,
    indication: str,
    target_any_indication: float,
    target_focal_indication: float,
    indication_gene_frequencies: list[tuple[str, float]],
    target_any_pancancer: float,
    target_focal_pancancer: float,
    pancancer_gene_frequencies: list[tuple[str, float]],
    out_path: Path,
    contracts_root: Path = DEFAULT_TARGET_CONTRACTS,
    *,
    cn_type: str = "amplification",
) -> Optional[Path]:
    """Emit dual pie charts showing copy-number alteration frequency in indication vs pan-cancer.

    Two donut-style pie charts side by side: indication (red/blue) on left, pan-cancer
    (black) on right. Shows both any-level (>=+1 or <=-1) and focal (+2 or -2) frequencies.

    Args:
        target: gene symbol
        indication: indication code (e.g., BRCA)
        target_any_indication: target's any-gain (>=+1) or any-loss (<=-1) frequency in indication
        target_focal_indication: target's focal (+2 high-amp or -2 homdel) frequency in indication
        indication_gene_frequencies: list of (gene, freq) for indication (any-level)
        target_any_pancancer: target's any-gain or any-loss frequency pan-cancer
        target_focal_pancancer: target's focal frequency pan-cancer
        pancancer_gene_frequencies: list of (gene, freq) for pan-cancer (any-level)
        out_path: directory to write figure
        contracts_root: path to target-contracts repo
        cn_type: "amplification" or "deletion" (affects labels and colors)
    """
    if not indication_gene_frequencies:
        return None

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
        svg_path = out_path / f"figure_cn_{cn_type}_pie.svg"
        fig.savefig(svg_path, bbox_inches="tight")
        plt.close(fig)
        return svg_path

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    style_path = contracts_root / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))

    # Process gene frequencies
    if indication_gene_frequencies and isinstance(indication_gene_frequencies[0], (list, tuple)):
        gene_freq_pairs = [(g, f) for g, f in indication_gene_frequencies if f is not None and f > 0]
    else:
        gene_freq_pairs = [(f"gene_{i}", f) for i, f in enumerate(indication_gene_frequencies) if f is not None and f > 0]

    if len(gene_freq_pairs) == 0:
        return None

    # Color scheme based on CN type
    if cn_type == "deletion":
        color_ind = "#2166AC"  # Blue for deletion
        color_pan = "#333333"
        label = "deleted"
    else:
        color_ind = "#B22222"  # Red for amplification
        color_pan = "#333333"
        label = "amplified"

    # Create square figure with two pie charts
    fig = plt.figure(figsize=(5.5, 5.0))
    fig.subplots_adjust(top=0.85, bottom=0.15, left=0.10, right=0.90)

    # Two pie chart axes
    ax_pie_ind = fig.add_axes([0.08, 0.35, 0.38, 0.50])
    ax_pie_pan = fig.add_axes([0.54, 0.35, 0.38, 0.50])

    # Labels for GISTIC levels
    if cn_type == "deletion":
        any_label = "any loss (≤-1)"
        focal_label = "homdel (-2)"
    else:
        any_label = "any gain (≥+1)"
        focal_label = "high-amp (+2)"

    # Color for low-level segment (lighter shade)
    if cn_type == "deletion":
        color_low = "#92C5DE"  # Light blue for shallow loss (-1)
    else:
        color_low = "#F4A582"  # Light red/orange for low-level gain (+1)

    # Indication pie chart - two segments: focal + low-level
    if target_any_indication is not None:
        ind_focal_pct = (target_focal_indication or 0) * 100
        ind_low_pct = (target_any_indication - (target_focal_indication or 0)) * 100
        ind_low_pct = max(0, ind_low_pct)  # Ensure non-negative
        ind_not = 100 - ind_focal_pct - ind_low_pct

        ax_pie_ind.pie(
            [ind_focal_pct, ind_low_pct, ind_not],
            colors=[color_ind, color_low, "#E8E8E8"],
            startangle=90,
            wedgeprops=dict(width=0.4, edgecolor="white", linewidth=1),
        )
        # Show total and focal breakdown in center
        total_pct = ind_focal_pct + ind_low_pct
        ax_pie_ind.text(0, 0.08, f"{total_pct:.1f}%", ha="center", va="center",
                        fontsize=12, fontweight="bold", color=color_ind)
        ax_pie_ind.text(0, -0.18, f"({ind_focal_pct:.1f}% focal)", ha="center", va="center",
                        fontsize=8, color=color_ind)
        ax_pie_ind.text(0, -1.1, f"{indication}", ha="center", va="top",
                        fontsize=9, fontweight="bold", color=color_ind)
        ax_pie_ind.set_aspect("equal")

    # Pan-cancer pie chart - two segments: focal + low-level
    if target_any_pancancer is not None:
        pan_focal_pct = (target_focal_pancancer or 0) * 100
        pan_low_pct = (target_any_pancancer - (target_focal_pancancer or 0)) * 100
        pan_low_pct = max(0, pan_low_pct)  # Ensure non-negative
        pan_not = 100 - pan_focal_pct - pan_low_pct

        ax_pie_pan.pie(
            [pan_focal_pct, pan_low_pct, pan_not],
            colors=[color_pan, "#999999", "#E8E8E8"],
            startangle=90,
            wedgeprops=dict(width=0.4, edgecolor="white", linewidth=1),
        )
        # Show total and focal breakdown in center
        total_pct = pan_focal_pct + pan_low_pct
        ax_pie_pan.text(0, 0.08, f"{total_pct:.1f}%", ha="center", va="center",
                        fontsize=12, fontweight="bold", color=color_pan)
        ax_pie_pan.text(0, -0.18, f"({pan_focal_pct:.1f}% focal)", ha="center", va="center",
                        fontsize=8, color=color_pan)
        ax_pie_pan.text(0, -1.1, "Pan-Cancer", ha="center", va="top",
                        fontsize=9, fontweight="bold", color=color_pan)
        ax_pie_pan.set_aspect("equal")

    # Title and provenance
    figure_title(fig, target, None, f"copy number {cn_type}", y=0.94)
    provenance_tag(fig, f"TCGA GISTIC PanCanAtlas · {any_label}, {focal_label}", y=0.90)

    # Calculate ranks
    all_sorted_ind = sorted(gene_freq_pairs, key=lambda x: x[1], reverse=True)
    ind_rank = None
    for i, (gene, freq) in enumerate(all_sorted_ind):
        if gene == target:
            ind_rank = i + 1
            break

    pan_rank = None
    if pancancer_gene_frequencies:
        if isinstance(pancancer_gene_frequencies[0], (list, tuple)):
            pan_pairs = [(g, f) for g, f in pancancer_gene_frequencies if f is not None and f > 0]
        else:
            pan_pairs = [(f"gene_{i}", f) for i, f in enumerate(pancancer_gene_frequencies) if f is not None and f > 0]
        all_sorted_pan = sorted(pan_pairs, key=lambda x: x[1], reverse=True)
        for i, (gene, freq) in enumerate(all_sorted_pan):
            if gene == target:
                pan_rank = i + 1
                break

    # Captions with colored ranks
    caption_y = 0.28
    line_spacing = 0.05

    if ind_rank:
        fig.text(0.5, caption_y,
                 f"{target} is the {ordinal(ind_rank)} most frequently {label} gene in {indication}",
                 ha="center", va="top", fontsize=10, color=color_ind, fontweight="bold")
    else:
        fig.text(0.5, caption_y,
                 f"{target} {cn_type} frequency in {indication}: {target_any_indication*100:.1f}%",
                 ha="center", va="top", fontsize=10, color=color_ind, fontweight="bold")

    if pan_rank:
        fig.text(0.5, caption_y - line_spacing,
                 f"{target} is the {ordinal(pan_rank)} most frequently {label} gene pan-cancer",
                 ha="center", va="top", fontsize=10, color=color_pan, fontweight="bold")
    else:
        fig.text(0.5, caption_y - line_spacing,
                 f"{target} {cn_type} frequency pan-cancer: {target_any_pancancer*100:.1f}%",
                 ha="center", va="top", fontsize=10, color=color_pan, fontweight="bold")

    svg_path = out_path / f"figure_cn_{cn_type}_pie.svg"
    fig.savefig(svg_path)
    plt.close(fig)
    return svg_path


def emit_cn_frequency_stacked(
    target: str,
    indication: str,
    target_freq_indication: float,
    indication_gene_frequencies: list[tuple[str, float]],
    target_freq_pancancer: float,
    pancancer_gene_frequencies: list[tuple[str, float]],
    out_path: Path,
    contracts_root: Path = DEFAULT_TARGET_CONTRACTS,
    *,
    min_frequency: float = 0.03,
    cn_type: str = "amplification",
    focal_events: bool = True,
) -> Optional[Path]:
    """Emit a stacked figure with indication-specific (top) and pan-cancer (bottom) CN frequency.

    Args:
        target: gene symbol
        indication: indication code
        target_freq_indication: target's frequency in indication
        indication_gene_frequencies: list of (gene, freq) tuples for indication
        target_freq_pancancer: target's frequency pan-cancer
        pancancer_gene_frequencies: list of (gene, freq) tuples for pan-cancer
        out_path: directory to write figure
        contracts_root: path to target-contracts repo
        min_frequency: minimum frequency threshold for display (default 3%)
        cn_type: "amplification" or "deletion"
        focal_events: if True, shows focal events (GISTIC ≥+2 / ≤-2); if False, any-level (≥+1 / ≤-1)
    """
    if not indication_gene_frequencies:
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
        svg_path = out_path / f"figure_cn_{cn_type}_stacked.svg"
        fig.savefig(svg_path, bbox_inches="tight")
        plt.close(fig)
        return svg_path

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    style_path = contracts_root / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))

    # Process gene frequencies for both panels
    def process_genes(gene_list, target_name, target_freq, threshold):
        if not gene_list:
            return [], 0
        if isinstance(gene_list[0], (list, tuple)):
            pairs = [(g, f) for g, f in gene_list if f is not None and f >= threshold]
        else:
            pairs = [(f"gene_{i}", f) for i, f in enumerate(gene_list) if f is not None and f >= threshold]
        pairs.sort(key=lambda x: x[1])
        total = len([g for g, f in gene_list if f is not None and f >= threshold])
        return pairs, total

    ind_genes, ind_total = process_genes(indication_gene_frequencies, target, target_freq_indication, min_frequency)
    pan_genes, pan_total = process_genes(pancancer_gene_frequencies, target, target_freq_pancancer, min_frequency)

    if not ind_genes and not pan_genes:
        return None

    # Color scheme
    if cn_type == "deletion":
        color_target = "#2166AC"  # Blue for deletion
        color_other = "#92C5DE"
        label = "deleted"
    else:
        color_target = "#B22222"  # Red for amplification
        color_other = "#FFCCCC"
        label = "amplified"

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7.0, 6.5))
    fig.subplots_adjust(top=0.88, bottom=0.08, left=0.12, right=0.95, hspace=0.35)

    def plot_panel(ax, genes, target_freq, panel_title, total_genes):
        if not genes:
            ax.text(0.5, 0.5, f"No genes ≥{min_frequency*100:.0f}% threshold",
                    ha="center", va="center", transform=ax.transAxes, fontsize=10, color="#888888")
            ax.set_xticks([])
            ax.set_yticks([])
            return

        names = [g for g, f in genes]
        freqs = [f for g, f in genes]
        colors = [color_target if g == target else color_other for g, f in genes]

        ax.bar(range(len(names)), freqs, color=colors, edgecolor="white", linewidth=0.5)

        target_in_panel = target in names
        for i, (gene, freq) in enumerate(genes):
            if gene == target:
                ax.annotate(
                    f"{gene} ({freq*100:.1f}%)",
                    xy=(i, freq),
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
                    f"{gene} ({freq*100:.1f}%)",
                    xy=(i, freq),
                    xytext=(0, 4),
                    textcoords="offset points",
                    fontsize=5,
                    color="#888888",
                    ha="center",
                    va="bottom",
                    rotation=90,
                )

        if not target_in_panel and target_freq is not None:
            ax.text(
                0.5, 0.85,
                f"{target} ({target_freq*100:.1f}%) — below {min_frequency*100:.0f}% threshold",
                ha="center", va="top", transform=ax.transAxes,
                fontsize=8, fontweight="bold", color=color_target,
                bbox=dict(boxstyle="round,pad=0.5", facecolor="#FFEEEE" if cn_type == "amplification" else "#E8F4F8",
                          edgecolor=color_target, linewidth=1),
            )

        ax.axhline(y=min_frequency, **REFLINE_NEUTRAL, zorder=1)
        ax.set_xlim(-0.5, len(genes) - 0.5)
        ax.set_ylim(bottom=0, top=0.3)  # Fixed max at 30% to avoid label overlap with verdict box
        ax.set_xticks([])
        ax.grid(axis="y", alpha=0.3)
        ax.set_ylabel("Frequency", fontsize=9, color="#33383D")
        ax.set_title(f"{panel_title} ({len(genes)} genes ≥{min_frequency*100:.0f}%)",
                     fontsize=10, fontweight="bold", loc="left", color="#33383D")

    plot_panel(ax1, ind_genes, target_freq_indication, indication, ind_total)
    plot_panel(ax2, pan_genes, target_freq_pancancer, "Pan-Cancer", pan_total)

    # Labels for GISTIC thresholds
    if focal_events:
        if cn_type == "deletion":
            level_label = "homozygous deletion (GISTIC ≤-2)"
            driver_label = "OncoKB tumor suppressors"
        else:
            level_label = "focal amplification (GISTIC ≥+2)"
            driver_label = "OncoKB oncogenes"
    else:
        if cn_type == "deletion":
            level_label = "any loss (GISTIC ≤-1)"
            driver_label = "OncoKB tumor suppressors"
        else:
            level_label = "any gain (GISTIC ≥+1)"
            driver_label = "OncoKB oncogenes"

    figure_title(fig, target, None, f"copy number {cn_type}", y=0.96)
    provenance_tag(fig, f"TCGA GISTIC PanCanAtlas · {level_label} in ≥{min_frequency*100:.0f}% of samples · {driver_label}", y=0.93)

    def get_rank(genes, target_name, target_freq):
        sorted_desc = sorted(genes, key=lambda x: x[1], reverse=True)
        for i, (gene, freq) in enumerate(sorted_desc):
            if gene == target_name or abs(freq - target_freq) < 1e-9:
                return i + 1
        return None

    ind_rank = get_rank(ind_genes, target, target_freq_indication) if ind_genes else None
    pan_rank = get_rank(pan_genes, target, target_freq_pancancer) if pan_genes else None

    if ind_rank and pan_rank:
        take_text = (f"{target} is the {ordinal(ind_rank)} most frequently {label} gene in {indication} "
                     f"and the {ordinal(pan_rank)} most frequently {label} gene pan-cancer.")
    elif ind_rank:
        take_text = (f"{target} is the {ordinal(ind_rank)} most frequently {label} gene in {indication} "
                     f"but is below the {min_frequency*100:.0f}% threshold pan-cancer.")
    elif pan_rank:
        take_text = (f"{target} is the {ordinal(pan_rank)} most frequently {label} gene pan-cancer "
                     f"but is below the {min_frequency*100:.0f}% threshold in {indication}.")
    else:
        take_text = (f"{target} is below the {min_frequency*100:.0f}% {cn_type} frequency threshold "
                     f"in both {indication} and pan-cancer.")
    takeaway(fig, take_text, y=0.02)

    svg_path = out_path / f"figure_cn_{cn_type}_stacked.svg"
    fig.savefig(svg_path)
    plt.close(fig)
    return svg_path


def emit_plot_data(
    target: str,
    indication: str,
    target_amp_freq: float,
    target_del_freq: float,
    all_gene_amp_frequencies: list,
    all_gene_del_frequencies: list,
    out_path: Path,
) -> Path:
    """Emit plot_data.parquet for offline figure re-rendering.

    Persists the data needed by emit_cn_frequency_pie and emit_cn_frequency_stacked
    so figures can be regenerated without re-querying the source data.
    """
    import pandas as pd

    rows = []

    # Target summary
    rows.append({
        "target": target,
        "indication": indication,
        "gene_symbol": target,
        "frequency": target_amp_freq,
        "cn_type": "amplification",
        "row_type": "target_summary",
    })
    rows.append({
        "target": target,
        "indication": indication,
        "gene_symbol": target,
        "frequency": target_del_freq,
        "cn_type": "deletion",
        "row_type": "target_summary",
    })

    # All genes context - amplification
    if all_gene_amp_frequencies:
        if isinstance(all_gene_amp_frequencies[0], (list, tuple)):
            for gene, freq in all_gene_amp_frequencies:
                rows.append({
                    "target": target,
                    "indication": indication,
                    "gene_symbol": gene,
                    "frequency": freq,
                    "cn_type": "amplification",
                    "row_type": "all_genes_context",
                })
        else:
            for i, freq in enumerate(all_gene_amp_frequencies):
                rows.append({
                    "target": target,
                    "indication": indication,
                    "gene_symbol": f"gene_{i}",
                    "frequency": freq,
                    "cn_type": "amplification",
                    "row_type": "all_genes_context",
                })

    # All genes context - deletion
    if all_gene_del_frequencies:
        if isinstance(all_gene_del_frequencies[0], (list, tuple)):
            for gene, freq in all_gene_del_frequencies:
                rows.append({
                    "target": target,
                    "indication": indication,
                    "gene_symbol": gene,
                    "frequency": freq,
                    "cn_type": "deletion",
                    "row_type": "all_genes_context",
                })
        else:
            for i, freq in enumerate(all_gene_del_frequencies):
                rows.append({
                    "target": target,
                    "indication": indication,
                    "gene_symbol": f"gene_{i}",
                    "frequency": freq,
                    "cn_type": "deletion",
                    "row_type": "all_genes_context",
                })

    df = pd.DataFrame(rows)
    parquet_path = out_path / "plot_data_cn.parquet"
    df.to_parquet(parquet_path, index=False)
    return parquet_path
