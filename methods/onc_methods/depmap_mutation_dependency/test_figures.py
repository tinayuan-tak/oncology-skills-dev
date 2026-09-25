#!/usr/bin/env python3
"""Quick test script to generate sample figures for depmap_mutation_dependency.

Run from the repo root:
    PYTHONPATH="$PWD" python methods/onc_methods/depmap_mutation_dependency/test_figures.py

Requires TARGET_CONTRACTS_PATH environment variable.
"""

from pathlib import Path
import os
import random
import numpy as np

random.seed(42)
np.random.seed(42)

# Sample data: KRAS mutation dependency
# Based on real DepMap 26Q1 data:
#   - 1538 cell lines total
#   - 338 hotspot mutants (22%)
#   - Median Chronos hotspot: -1.73, WT: -0.59
#   - COADREAD ~5% of DepMap, ~40% KRAS mutation rate in COADREAD
TARGET = "KRAS"
INDICATION = "COADREAD"

N_TOTAL_LINES = 1538


def generate_chronos():
    """Generate synthetic Chronos data matching real DepMap 26Q1 KRAS statistics."""
    chronos = {}
    hotspot = {}
    damaging = {}
    lineage = {}

    # Lineage distribution (approximate DepMap 26Q1)
    lineages = ["Colorectal", "Lung", "Breast", "Pancreas", "Skin", "Ovary", "Blood", "Other"]
    lineage_weights = [0.05, 0.15, 0.10, 0.05, 0.08, 0.06, 0.12, 0.39]

    # Generate all cell lines first
    for i in range(N_TOTAL_LINES):
        mid = f"ACH-{i:04d}"
        lin = np.random.choice(lineages, p=lineage_weights)
        lineage[mid] = lin
        hotspot[mid] = False
        damaging[mid] = False
        # Default Chronos (WT) - matches real median of -0.59
        chronos[mid] = np.random.normal(-0.59, 0.40)

    # Assign hotspot mutations based on lineage
    # KRAS hotspot mutations are enriched in Colorectal (~40%) and Pancreas (~90%), Lung (~30%)
    hotspot_rates = {
        "Colorectal": 0.40,
        "Pancreas": 0.90,
        "Lung": 0.30,
        "Breast": 0.05,
        "Skin": 0.05,
        "Ovary": 0.10,
        "Blood": 0.02,
        "Other": 0.05,
    }

    for mid, lin in lineage.items():
        rate = hotspot_rates.get(lin, 0.05)
        if np.random.random() < rate:
            hotspot[mid] = True
            # Hotspot mutants are strongly dependent - matches real median of -1.73
            if lin == "Colorectal":
                chronos[mid] = np.random.normal(-1.75, 0.30)
            elif lin == "Pancreas":
                chronos[mid] = np.random.normal(-1.85, 0.25)
            else:
                chronos[mid] = np.random.normal(-1.70, 0.35)

    # KRAS is an oncogene - no damaging mutations in real data
    # Keep damaging dict but leave all False

    return chronos, hotspot, damaging, lineage


def emit_mut_vs_wt_strip_plot(
    chronos_by_model, hotspot_by_model, damaging_by_model, lineage_by_model,
    target_symbol, indication, indication_lineage, summary, out_path, contracts_root
):
    """Strip plot with indication-specific highlighting and dual statistics."""
    import sys
    import matplotlib.pyplot as plt

    sys.path.insert(0, str(contracts_root / "plot_styles"))
    style_path = contracts_root / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))

    # Try to import from takeda_palette, fallback to defaults
    try:
        from takeda_palette import (
            CHRONOS_STRONG_DEPENDENCY,
            REFLINE_KILLER,
            REFLINE_NOMINAL,
        )
    except ImportError:
        CHRONOS_STRONG_DEPENDENCY = -0.5
        REFLINE_KILLER = {"color": "#D62728", "linestyle": "--", "linewidth": 1.0, "alpha": 0.7}
        REFLINE_NOMINAL = {"color": "#888888", "linestyle": "-", "linewidth": 0.8, "alpha": 0.5}

    fig, ax = plt.subplots(figsize=(8.0, 5.5))

    if not chronos_by_model:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        fig.savefig(out_path / "figure_mut_vs_wt_strip.svg", bbox_inches="tight")
        plt.close(fig)
        return

    rng = np.random.default_rng(seed=42)

    # Build groups with indication membership
    def build_group(label, model_filter, color):
        models = [m for m in chronos_by_model if model_filter(m)]
        scores = [chronos_by_model[m] for m in models]
        is_indication = [lineage_by_model.get(m) == indication_lineage for m in models]
        return label, models, scores, is_indication, color

    groups = []
    if hotspot_by_model:
        groups.append(build_group(
            "hotspot\nmutant",
            lambda m: m in hotspot_by_model and hotspot_by_model[m],
            "#B22222",
        ))
        groups.append(build_group(
            "hotspot\nWT",
            lambda m: m in hotspot_by_model and not hotspot_by_model[m],
            "#888888",
        ))
    if damaging_by_model:
        groups.append(build_group(
            "damaging\nmutant",
            lambda m: m in damaging_by_model and damaging_by_model[m],
            "#E69F00",
        ))
        groups.append(build_group(
            "damaging\nWT",
            lambda m: m in damaging_by_model and not damaging_by_model[m],
            "#888888",
        ))

    # Plot each group
    for i, (label, models, scores, is_ind, color) in enumerate(groups):
        if not scores:
            continue

        scores_arr = np.array(scores)
        is_ind_arr = np.array(is_ind)
        xs = i + rng.uniform(-0.25, 0.25, size=len(scores_arr))

        # Plot non-indication points (no outline, smaller)
        non_ind_mask = ~is_ind_arr
        if np.any(non_ind_mask):
            ax.scatter(xs[non_ind_mask], scores_arr[non_ind_mask], s=30, alpha=0.4,
                       color=color, edgecolor="white", linewidth=0.3, zorder=2)

        # Plot indication points with black outline (larger, thinner outline)
        ind_mask = is_ind_arr
        if np.any(ind_mask):
            ax.scatter(xs[ind_mask], scores_arr[ind_mask], s=50, alpha=0.9,
                       color=color, edgecolor="black", linewidth=0.8, zorder=3,
                       label=f"{indication}" if i == 0 else None)

        # Pan-lineage median (solid black line)
        med_all = float(np.median(scores_arr))
        ax.plot([i - 0.35, i + 0.35], [med_all, med_all], color="#222222",
                linewidth=2.0, zorder=4, linestyle="-")

        # Indication-specific median (dashed black line, same length)
        if np.any(ind_mask):
            med_ind = float(np.median(scores_arr[ind_mask]))
            ax.plot([i - 0.35, i + 0.35], [med_ind, med_ind], color="#222222",
                    linewidth=2.0, zorder=5, linestyle="--")

    ax.axhline(y=0, **REFLINE_NOMINAL, zorder=1)
    ax.axhline(y=CHRONOS_STRONG_DEPENDENCY, **REFLINE_KILLER, zorder=1)

    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels([label for label, _, _, _, _ in groups], fontsize=10)
    ax.set_ylabel("Chronos score (more dependent ↓)", fontsize=10)
    cls = summary.get("mutation_stratification_class", "?")
    ax.set_title(f"{target_symbol}: dependency stratified by mutation status  ({cls})", fontsize=11)
    ax.grid(axis="y", alpha=0.3)

    # Statistics table at bottom
    hot_q_pan = summary.get("hotspot_mannwhitney_q_pan")
    hot_q_ind = summary.get("hotspot_mannwhitney_q_indication")
    med_mut_pan = summary.get("median_chronos_hotspot_mutant_pan")
    med_wt_pan = summary.get("median_chronos_hotspot_wildtype_pan")
    med_mut_ind = summary.get("median_chronos_hotspot_mutant_indication")
    med_wt_ind = summary.get("median_chronos_hotspot_wildtype_indication")

    # Create table data
    col_labels = ["", "Median (Mut)", "Median (WT)", "q-value", ""]
    table_data = [
        ["Pan-DepMap",
         f"{med_mut_pan:.2f}" if med_mut_pan else "—",
         f"{med_wt_pan:.2f}" if med_wt_pan else "—",
         f"{hot_q_pan:.1e}" if hot_q_pan else "—",
         "— solid"],
        [f"{indication}",
         f"{med_mut_ind:.2f}" if med_mut_ind else "—",
         f"{med_wt_ind:.2f}" if med_wt_ind else "—",
         f"{hot_q_ind:.1e}" if hot_q_ind else "—",
         "-- dashed, ● outlined"],
    ]

    # Add table below the plot
    table = ax.table(
        cellText=table_data,
        colLabels=col_labels,
        loc="bottom",
        cellLoc="center",
        bbox=[0.0, -0.35, 1.0, 0.20],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)

    # Style the table
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("#CCCCCC")
        cell.set_linewidth(0.5)
        if row == 0:  # Header row
            cell.set_text_props(fontweight="bold")
            cell.set_facecolor("#F0F0F0")
        else:
            cell.set_facecolor("white")

    # Adjust layout to make room for table
    fig.subplots_adjust(bottom=0.25)
    fig.savefig(out_path / "figure_mut_vs_wt_strip.svg", bbox_inches="tight")
    plt.close(fig)


def main():
    from scipy import stats

    # Use target-contracts repo from environment variable
    contracts_path = os.environ.get("TARGET_CONTRACTS_PATH")
    if not contracts_path:
        raise EnvironmentError(
            "TARGET_CONTRACTS_PATH environment variable not set."
        )
    TARGET_CONTRACTS = Path(contracts_path)

    out_dir = Path("/tmp/depmap_mutation_figures")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating figures in {out_dir}...")

    # Generate synthetic data
    chronos, hotspot, damaging, lineage = generate_chronos()

    # Indication of interest
    indication_lineage = "Colorectal"  # This maps to COADREAD

    # Compute statistics
    # Pan-lineage hotspot mutant/WT scores
    hotspot_mut_scores_pan = [chronos[m] for m in chronos if hotspot.get(m, False)]
    hotspot_wt_scores_pan = [chronos[m] for m in chronos if not hotspot.get(m, True)]

    # Indication-specific hotspot mutant/WT scores
    hotspot_mut_scores_ind = [chronos[m] for m in chronos
                              if hotspot.get(m, False) and lineage.get(m) == indication_lineage]
    hotspot_wt_scores_ind = [chronos[m] for m in chronos
                             if not hotspot.get(m, True) and lineage.get(m) == indication_lineage]

    # Compute medians
    med_mut_pan = np.median(hotspot_mut_scores_pan) if hotspot_mut_scores_pan else None
    med_wt_pan = np.median(hotspot_wt_scores_pan) if hotspot_wt_scores_pan else None
    med_mut_ind = np.median(hotspot_mut_scores_ind) if hotspot_mut_scores_ind else None
    med_wt_ind = np.median(hotspot_wt_scores_ind) if hotspot_wt_scores_ind else None

    # Compute Mann-Whitney q-values
    if hotspot_mut_scores_pan and hotspot_wt_scores_pan:
        _, p_pan = stats.mannwhitneyu(hotspot_mut_scores_pan, hotspot_wt_scores_pan, alternative='less')
        q_pan = p_pan  # In practice, this would be FDR-corrected
    else:
        q_pan = None

    if hotspot_mut_scores_ind and hotspot_wt_scores_ind:
        _, p_ind = stats.mannwhitneyu(hotspot_mut_scores_ind, hotspot_wt_scores_ind, alternative='less')
        q_ind = p_ind  # In practice, this would be FDR-corrected
    else:
        q_ind = None

    # Counts
    n_hotspot_mut = len(hotspot_mut_scores_pan)
    n_hotspot_wt = len(hotspot_wt_scores_pan)
    n_damaging_mut = sum(1 for m in damaging if damaging[m])
    n_damaging_wt = sum(1 for m in damaging if not damaging[m])

    # Create summary with both pan-lineage and indication-specific stats
    summary = {
        "n_hotspot_mutant": n_hotspot_mut,
        "n_hotspot_wildtype": n_hotspot_wt,
        "n_damaging_mutant": n_damaging_mut,
        "n_damaging_wildtype": n_damaging_wt,
        "mutation_stratification_class": "mutant_strongly_dependent",
        # Pan-lineage stats
        "hotspot_mannwhitney_q_pan": q_pan,
        "median_chronos_hotspot_mutant_pan": med_mut_pan,
        "median_chronos_hotspot_wildtype_pan": med_wt_pan,
        # Indication-specific stats
        "hotspot_mannwhitney_q_indication": q_ind,
        "median_chronos_hotspot_mutant_indication": med_mut_ind,
        "median_chronos_hotspot_wildtype_indication": med_wt_ind,
        "per_hotspot_stats": [],
    }

    # === Test 1: Mut vs WT strip plot ===
    print(f"\n=== Test 1: KRAS mut vs WT strip plot ===")
    print(f"  Pan-DepMap: {len(hotspot_mut_scores_pan)} mut, {len(hotspot_wt_scores_pan)} WT")
    print(f"  {INDICATION}: {len(hotspot_mut_scores_ind)} mut, {len(hotspot_wt_scores_ind)} WT")
    print(f"  Median Chronos (pan): mut={med_mut_pan:.2f}, WT={med_wt_pan:.2f}, q={q_pan:.2e}")
    print(f"  Median Chronos ({INDICATION}): mut={med_mut_ind:.2f}, WT={med_wt_ind:.2f}, q={q_ind:.2e}")

    emit_mut_vs_wt_strip_plot(
        chronos,
        hotspot,
        damaging,
        lineage,
        TARGET,
        INDICATION,
        indication_lineage,
        summary,
        out_dir,
        TARGET_CONTRACTS,
    )
    print(f"  ✓ Strip plot: {out_dir}/figure_mut_vs_wt_strip.svg")

    print(f"\nFigures saved to: {out_dir}")


if __name__ == "__main__":
    main()
