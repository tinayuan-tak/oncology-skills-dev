"""tcga_fusion_consensus.figures — figure emission functions for fusion visualizations.

Provides:
- emit_fusion_frequency_pie: dual pie charts showing fusion frequency in indication vs pan-cancer
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


def emit_fusion_frequency_pie(
    target: str,
    indication: str,
    target_freq_indication: float,
    n_samples_indication: int,
    n_assayed_indication: int,
    indication_gene_frequencies: list[tuple[str, float]],
    target_freq_pancancer: float,
    n_samples_pancancer: int,
    n_assayed_pancancer: int,
    pancancer_gene_frequencies: list[tuple[str, float]],
    out_path: Path,
    contracts_root: Path = DEFAULT_TARGET_CONTRACTS,
) -> Optional[Path]:
    """Emit dual pie charts showing fusion frequency in indication vs pan-cancer.

    Two donut-style pie charts side by side: indication (purple) on left, pan-cancer
    (black) on right. Shows the percentage of samples with the target gene fused.

    Args:
        target: gene symbol
        indication: indication code (e.g., LUAD)
        target_freq_indication: target's fusion frequency in indication
        n_samples_indication: number of samples with fusion in indication
        n_assayed_indication: total samples assayed in indication
        indication_gene_frequencies: list of (gene, freq) for indication
        target_freq_pancancer: target's fusion frequency pan-cancer
        n_samples_pancancer: number of samples with fusion pan-cancer
        n_assayed_pancancer: total samples assayed pan-cancer
        pancancer_gene_frequencies: list of (gene, freq) for pan-cancer
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
        svg_path = out_path / "figure_fusion_frequency_pie.svg"
        fig.savefig(svg_path, bbox_inches="tight")
        plt.close(fig)
        return svg_path

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    style_path = contracts_root / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))

    # Process gene frequencies for ranking
    if indication_gene_frequencies and isinstance(indication_gene_frequencies[0], (list, tuple)):
        gene_freq_pairs = [(g, f) for g, f in indication_gene_frequencies if f is not None and f > 0]
    else:
        gene_freq_pairs = []

    # Purple color scheme for fusions
    color_ind = "#7B2D8E"  # Purple for indication
    color_pan = "#333333"  # Black for pan-cancer

    # Create square figure with two pie charts
    fig = plt.figure(figsize=(5.5, 5.0))
    fig.subplots_adjust(top=0.85, bottom=0.15, left=0.10, right=0.90)

    # Two pie chart axes
    ax_pie_ind = fig.add_axes([0.08, 0.35, 0.38, 0.50])
    ax_pie_pan = fig.add_axes([0.54, 0.35, 0.38, 0.50])

    # Indication pie chart
    if target_freq_indication is not None:
        ind_pct = target_freq_indication * 100
        ind_not = 100 - ind_pct

        ax_pie_ind.pie(
            [ind_pct, ind_not],
            colors=[color_ind, "#E8E8E8"],
            startangle=90,
            wedgeprops=dict(width=0.4, edgecolor="white", linewidth=1),
        )
        # Show percentage and sample count in center
        ax_pie_ind.text(0, 0.08, f"{ind_pct:.1f}%", ha="center", va="center",
                        fontsize=12, fontweight="bold", color=color_ind)
        ax_pie_ind.text(0, -0.18, f"(n={n_samples_indication}/{n_assayed_indication})", ha="center", va="center",
                        fontsize=8, color=color_ind)
        ax_pie_ind.text(0, -1.1, f"{indication}", ha="center", va="top",
                        fontsize=9, fontweight="bold", color=color_ind)
        ax_pie_ind.set_aspect("equal")

    # Pan-cancer pie chart
    if target_freq_pancancer is not None:
        pan_pct = target_freq_pancancer * 100
        pan_not = 100 - pan_pct

        ax_pie_pan.pie(
            [pan_pct, pan_not],
            colors=[color_pan, "#E8E8E8"],
            startangle=90,
            wedgeprops=dict(width=0.4, edgecolor="white", linewidth=1),
        )
        # Show percentage and sample count in center
        ax_pie_pan.text(0, 0.08, f"{pan_pct:.1f}%", ha="center", va="center",
                        fontsize=12, fontweight="bold", color=color_pan)
        ax_pie_pan.text(0, -0.18, f"(n={n_samples_pancancer}/{n_assayed_pancancer})", ha="center", va="center",
                        fontsize=8, color=color_pan)
        ax_pie_pan.text(0, -1.1, "Pan-Cancer", ha="center", va="top",
                        fontsize=9, fontweight="bold", color=color_pan)
        ax_pie_pan.set_aspect("equal")

    # Title and provenance
    figure_title(fig, target, None, "fusion frequency", y=0.94)
    provenance_tag(fig, "TCGA Fusion Consensus (3-caller)", y=0.90)

    # Calculate ranks
    ind_rank = None
    if gene_freq_pairs:
        all_sorted_ind = sorted(gene_freq_pairs, key=lambda x: x[1], reverse=True)
        for i, (gene, freq) in enumerate(all_sorted_ind):
            if gene == target:
                ind_rank = i + 1
                break

    pan_rank = None
    if pancancer_gene_frequencies:
        if isinstance(pancancer_gene_frequencies[0], (list, tuple)):
            pan_pairs = [(g, f) for g, f in pancancer_gene_frequencies if f is not None and f > 0]
        else:
            pan_pairs = []
        if pan_pairs:
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
                 f"{target} is the {ordinal(ind_rank)} most frequently fused gene in {indication}",
                 ha="center", va="top", fontsize=10, color=color_ind, fontweight="bold")
    elif target_freq_indication is not None and target_freq_indication > 0:
        fig.text(0.5, caption_y,
                 f"{target} fusion frequency in {indication}: {target_freq_indication*100:.2f}%",
                 ha="center", va="top", fontsize=10, color=color_ind, fontweight="bold")
    else:
        fig.text(0.5, caption_y,
                 f"{target} has no detected fusions in {indication}",
                 ha="center", va="top", fontsize=10, color=color_ind, fontweight="bold")

    if pan_rank:
        fig.text(0.5, caption_y - line_spacing,
                 f"{target} is the {ordinal(pan_rank)} most frequently fused gene pan-cancer",
                 ha="center", va="top", fontsize=10, color=color_pan, fontweight="bold")
    elif target_freq_pancancer is not None and target_freq_pancancer > 0:
        fig.text(0.5, caption_y - line_spacing,
                 f"{target} fusion frequency pan-cancer: {target_freq_pancancer*100:.2f}%",
                 ha="center", va="top", fontsize=10, color=color_pan, fontweight="bold")
    else:
        fig.text(0.5, caption_y - line_spacing,
                 f"{target} has no detected fusions pan-cancer",
                 ha="center", va="top", fontsize=10, color=color_pan, fontweight="bold")

    svg_path = out_path / "figure_fusion_frequency_pie.svg"
    fig.savefig(svg_path)
    plt.close(fig)
    return svg_path


def emit_fusion_frequency_stacked(
    target: str,
    indication: str,
    target_freq_indication: float,
    indication_gene_frequencies: list[tuple[str, float]],
    target_freq_pancancer: float,
    pancancer_gene_frequencies: list[tuple[str, float]],
    out_path: Path,
    contracts_root: Path = DEFAULT_TARGET_CONTRACTS,
    *,
    min_frequency: float = 0.005,
) -> Optional[Path]:
    """Emit a stacked figure with indication-specific (top) and pan-cancer (bottom) fusion frequency.

    Args:
        target: gene symbol
        indication: indication code
        target_freq_indication: target's fusion frequency in indication
        indication_gene_frequencies: list of (gene, freq) tuples for indication
        target_freq_pancancer: target's fusion frequency pan-cancer
        pancancer_gene_frequencies: list of (gene, freq) tuples for pan-cancer
        out_path: directory to write figure
        contracts_root: path to target-contracts repo
        min_frequency: minimum frequency threshold for display (default 0.5%)
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
        svg_path = out_path / "figure_fusion_frequency_stacked.svg"
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

    # Purple color scheme for fusions
    color_target = "#B22222"  # Red for target gene highlight
    color_other = "#D4B8E0"   # Light purple for others

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7.0, 6.5))
    fig.subplots_adjust(top=0.88, bottom=0.08, left=0.12, right=0.95, hspace=0.35)

    def plot_panel(ax, genes, target_freq, panel_title, total_genes, label_fontsize=5):
        if not genes:
            ax.text(0.5, 0.5, f"No genes ≥{min_frequency*100:.1f}% threshold",
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
                    f"{gene} ({freq*100:.2f}%)",
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
                    f"{gene} ({freq*100:.2f}%)",
                    xy=(i, freq),
                    xytext=(0, 4),
                    textcoords="offset points",
                    fontsize=label_fontsize,
                    color="#888888",
                    ha="center",
                    va="bottom",
                    rotation=90,
                )

        if not target_in_panel and target_freq is not None:
            ax.text(
                0.5, 0.85,
                f"{target} ({target_freq*100:.2f}%) — below {min_frequency*100:.1f}% threshold",
                ha="center", va="top", transform=ax.transAxes,
                fontsize=8, fontweight="bold", color=color_target,
                bbox=dict(boxstyle="round,pad=0.5", facecolor="#F3E8F7", edgecolor=color_target, linewidth=1),
            )

        ax.axhline(y=min_frequency, **REFLINE_NEUTRAL, zorder=1)
        ax.set_xlim(-0.5, len(genes) - 0.5)
        ax.set_ylim(bottom=0)
        ax.set_xticks([])
        ax.grid(axis="y", alpha=0.3)
        ax.set_ylabel("Frequency", fontsize=9, color="#33383D")
        ax.set_title(f"{panel_title} ({len(genes)} genes ≥{min_frequency*100:.1f}%)",
                     fontsize=10, fontweight="bold", loc="left", color="#33383D")

    plot_panel(ax1, ind_genes, target_freq_indication, indication, ind_total, label_fontsize=5)
    plot_panel(ax2, pan_genes, target_freq_pancancer, "Pan-Cancer", pan_total, label_fontsize=4)

    figure_title(fig, target, None, "fusion frequency", y=0.96)
    provenance_tag(fig, f"TCGA Fusion Consensus (3-caller) · genes fused in ≥{min_frequency*100:.1f}% of samples", y=0.93)

    def get_rank(genes, target_name, target_freq):
        sorted_desc = sorted(genes, key=lambda x: x[1], reverse=True)
        for i, (gene, freq) in enumerate(sorted_desc):
            if gene == target_name or (target_freq and abs(freq - target_freq) < 1e-9):
                return i + 1
        return None

    ind_rank = get_rank(ind_genes, target, target_freq_indication) if ind_genes else None
    pan_rank = get_rank(pan_genes, target, target_freq_pancancer) if pan_genes else None

    if ind_rank and pan_rank:
        take_text = (f"{target} is the {ordinal(ind_rank)} most frequently fused gene in {indication} "
                     f"and the {ordinal(pan_rank)} most frequently fused gene pan-cancer.")
    elif ind_rank:
        take_text = (f"{target} is the {ordinal(ind_rank)} most frequently fused gene in {indication} "
                     f"but is below the {min_frequency*100:.1f}% threshold pan-cancer.")
    elif pan_rank:
        take_text = (f"{target} is the {ordinal(pan_rank)} most frequently fused gene pan-cancer "
                     f"but is below the {min_frequency*100:.1f}% threshold in {indication}.")
    else:
        take_text = (f"{target} is below the {min_frequency*100:.1f}% fusion frequency threshold "
                     f"in both {indication} and pan-cancer.")
    takeaway(fig, take_text, y=0.02)

    svg_path = out_path / "figure_fusion_frequency_stacked.svg"
    fig.savefig(svg_path)
    plt.close(fig)
    return svg_path


def emit_plot_data(
    target: str,
    indication: str,
    target_freq_indication: float,
    n_samples_indication: int,
    n_assayed_indication: int,
    indication_gene_frequencies: list,
    target_freq_pancancer: float,
    n_samples_pancancer: int,
    n_assayed_pancancer: int,
    pancancer_gene_frequencies: list,
    out_path: Path,
) -> Path:
    """Emit plot_data_fusion.parquet for offline figure re-rendering."""
    import pandas as pd

    rows = []

    # Target summary - indication
    rows.append({
        "target": target,
        "indication": indication,
        "gene_symbol": target,
        "frequency": target_freq_indication,
        "n_samples": n_samples_indication,
        "n_assayed": n_assayed_indication,
        "scope": "indication",
        "row_type": "target_summary",
    })

    # Target summary - pan-cancer
    rows.append({
        "target": target,
        "indication": indication,
        "gene_symbol": target,
        "frequency": target_freq_pancancer,
        "n_samples": n_samples_pancancer,
        "n_assayed": n_assayed_pancancer,
        "scope": "pancancer",
        "row_type": "target_summary",
    })

    # All genes context - indication
    if indication_gene_frequencies:
        for gene, freq in indication_gene_frequencies:
            rows.append({
                "target": target,
                "indication": indication,
                "gene_symbol": gene,
                "frequency": freq,
                "n_samples": None,
                "n_assayed": None,
                "scope": "indication",
                "row_type": "all_genes_context",
            })

    # All genes context - pan-cancer
    if pancancer_gene_frequencies:
        for gene, freq in pancancer_gene_frequencies:
            rows.append({
                "target": target,
                "indication": indication,
                "gene_symbol": gene,
                "frequency": freq,
                "n_samples": None,
                "n_assayed": None,
                "scope": "pancancer",
                "row_type": "all_genes_context",
            })

    df = pd.DataFrame(rows)
    parquet_path = out_path / "plot_data_fusion.parquet"
    df.to_parquet(parquet_path, index=False)
    return parquet_path


def _reconstruct(plot_data) -> dict:
    """Rebuild figure data from plot_data_fusion.parquet."""
    import pandas as pd

    df = plot_data if hasattr(plot_data, "columns") else pd.read_parquet(Path(plot_data))

    result = {
        "target": df["target"].iloc[0] if "target" in df.columns else None,
        "indication": df["indication"].iloc[0] if "indication" in df.columns else None,
    }

    # Target summary
    target_rows = df[df["row_type"] == "target_summary"]
    ind_target = target_rows[target_rows["scope"] == "indication"]
    pan_target = target_rows[target_rows["scope"] == "pancancer"]

    if len(ind_target) > 0:
        result["target_freq_indication"] = float(ind_target["frequency"].iloc[0])
        result["n_samples_indication"] = int(ind_target["n_samples"].iloc[0]) if pd.notna(ind_target["n_samples"].iloc[0]) else 0
        result["n_assayed_indication"] = int(ind_target["n_assayed"].iloc[0]) if pd.notna(ind_target["n_assayed"].iloc[0]) else 0

    if len(pan_target) > 0:
        result["target_freq_pancancer"] = float(pan_target["frequency"].iloc[0])
        result["n_samples_pancancer"] = int(pan_target["n_samples"].iloc[0]) if pd.notna(pan_target["n_samples"].iloc[0]) else 0
        result["n_assayed_pancancer"] = int(pan_target["n_assayed"].iloc[0]) if pd.notna(pan_target["n_assayed"].iloc[0]) else 0

    # All genes context
    context_rows = df[df["row_type"] == "all_genes_context"]
    ind_context = context_rows[context_rows["scope"] == "indication"]
    pan_context = context_rows[context_rows["scope"] == "pancancer"]

    result["indication_gene_frequencies"] = [(row["gene_symbol"], row["frequency"])
                                              for _, row in ind_context.iterrows()]
    result["pancancer_gene_frequencies"] = [(row["gene_symbol"], row["frequency"])
                                             for _, row in pan_context.iterrows()]

    return result


def render_from_plot_data(
    plot_data,
    summary: dict,
    out_dir,
    target: str,
    indication: Optional[str] = None,
    *,
    target_contracts_dir = None,
) -> list[dict]:
    """Render fusion figures OFFLINE from persisted plot_data_fusion.parquet."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tcd = Path(target_contracts_dir) if target_contracts_dir else DEFAULT_TARGET_CONTRACTS

    data = _reconstruct(plot_data)
    target = data.get("target") or target
    indication = data.get("indication") or indication

    figures = []

    # Emit pie chart
    if data.get("indication_gene_frequencies"):
        svg = emit_fusion_frequency_pie(
            target,
            indication,
            data.get("target_freq_indication", 0),
            data.get("n_samples_indication", 0),
            data.get("n_assayed_indication", 0),
            data.get("indication_gene_frequencies", []),
            data.get("target_freq_pancancer", 0),
            data.get("n_samples_pancancer", 0),
            data.get("n_assayed_pancancer", 0),
            data.get("pancancer_gene_frequencies", []),
            out_dir,
            tcd,
        )
        if svg:
            figures.append({
                "id": "fusion_frequency_pie",
                "path": "figure_fusion_frequency_pie.svg",
                "type": "fusion_frequency_pie",
                "primary": True,
            })

    # Emit stacked bar
    if data.get("indication_gene_frequencies"):
        svg = emit_fusion_frequency_stacked(
            target,
            indication,
            data.get("target_freq_indication", 0),
            data.get("indication_gene_frequencies", []),
            data.get("target_freq_pancancer", 0),
            data.get("pancancer_gene_frequencies", []),
            out_dir,
            tcd,
        )
        if svg:
            figures.append({
                "id": "fusion_frequency_stacked",
                "path": "figure_fusion_frequency_stacked.svg",
                "type": "fusion_frequency_stacked",
                "primary": False,
            })

    return figures
