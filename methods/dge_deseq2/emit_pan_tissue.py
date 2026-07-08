"""emit_pan_tissue — pan-indication expression box+scatter figure.

For a single (target, gene), renders a compact matrix visualization
showing target's expression distribution across all wired indications,
grouped into three normal-comparator families:

  - TCGA Primary Tumor (per indication)
  - TCGA Adjacent-Normal (per indication, when available)
  - GTEx tissue-of-origin (per indication's canonical GTEx mapping)

Each row = one indication. Each cell = box + jittered scatter of
log2(TPM+1) per sample. Significance annotations from the sensitivity
parquet's cell A / cell C q-values are overlaid per row.

Consumer: `tumor-vs-normal-selectivity` card gains a new figure_id
`tumor_vs_normal_pan_tissue_landscape`. Also invocable as a standalone
skill artefact by target-profile in a future extension.

Design decisions:
- TPM (log2(TPM+1)) is the unit — cross-tissue comparability is the point.
  If TPM is unavailable for a target (Gencode-v26 length missing), rows
  fall back to log2(CPM+1) with a visible caveat annotation.
- Rows sorted by median tumor log2TPM descending (draws the eye to
  highest-expressing tissues first).
- Q-value stars: * <0.05, ** <1e-4, *** <1e-10; ns otherwise.
- Discordant indications (cells A vs C disagree in direction) flagged
  with a small dot marker next to the row label.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


# Indication → TCGA-study + GTEx-tissue mapping (mirrors
# INDICATION_TO_TCGA_STUDIES + INDICATION_TO_GTEX_TISSUE in read.py).
# The set below is limited to the 18 indications the batch produced.
PAN_TISSUE_INDICATIONS = [
    "COAD", "READ", "COADREAD", "LUAD", "LUSC", "BRCA", "PAAD",
    "SKCM", "STAD", "PRAD", "OV", "KIRC", "GBM", "LGG",
    "BLCA", "LIHC", "CESC", "ESCA", "HNSC",
]

# Local batch output root (for dev-mode reads when S3 isn't populated yet).
LOCAL_BATCH_ROOT = Path.home() / "dev" / "framework-runs" / "tvn-batch-2026-07-07"


def _find_sensitivity_row(
    indication: str, target: str,
) -> Optional[dict]:
    """Load one gene's sensitivity row from the batch-produced parquet.

    Prefers local disk (batch output); falls back to S3 if not found locally.
    Returns dict with cells_supporting + per-cell log2fc/padj OR None if
    unavailable.
    """
    import pandas as pd

    local_path = LOCAL_BATCH_ROOT / indication.upper() / "sensitivity.parquet"
    if local_path.exists():
        try:
            df = pd.read_parquet(local_path)
        except Exception:
            df = None
    else:
        # S3 fallback (works once upload PR lands)
        try:
            import pyarrow.fs as fs
            import pyarrow.parquet as pq
            os.environ.setdefault("AWS_PROFILE", "cbg")
            s3fs = fs.S3FileSystem()
            s3_path = (
                f"onc-compbio/data-catalog/derived/"
                f"{indication.lower()}-dge-tumor-vs-normal-sensitivity-v1/"
                f"sensitivity.parquet"
            )
            table = pq.read_table(s3_path, filesystem=s3fs,
                                  filters=[("gene_symbol", "=", target)])
            df = table.to_pandas() if table.num_rows > 0 else None
        except Exception:
            df = None

    if df is None:
        return None
    hit = df[df["gene_symbol"] == target]
    if hit.empty:
        return None
    row = hit.iloc[0].to_dict()
    return row


def render_pan_tissue_landscape(
    target: str,
    out_path: Path,
    indications: Optional[list[str]] = None,
    include_gtex: bool = True,
    include_adjacent: bool = True,
) -> Path:
    """Render a compact pan-tissue box+scatter matrix for `target`.

    Layout: N rows (one per indication) × 3 columns (Tumor / TCGA-Adj /
    GTEx). Each cell: horizontal box + jittered strip of log2(TPM+1).
    Q-value stars annotated per (indication, cells A/C) cell.

    Args:
        target: HGNC symbol
        out_path: PNG destination (SVG companion written alongside)
        indications: which indications to include (default: all 18 wired)
        include_gtex, include_adjacent: toggle columns

    Returns:
        PNG path.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    if indications is None:
        indications = PAN_TISSUE_INDICATIONS

    # Import readers lazily so this module's import doesn't pull the whole
    # DEG pipeline unless the figure is actually requested.
    from .read import read_per_sample_expression_all_three_groups

    # For each indication, fetch per-sample TPM + sensitivity row
    rows_data = []
    for ind in indications:
        expr = read_per_sample_expression_all_three_groups(target, ind)
        sens = _find_sensitivity_row(ind, target)
        if expr is None:
            continue

        def _log2tpm_or_cpm(samples):
            """Return log2TPM values if available, else log2CPM as fallback."""
            vals = [s.get("log2_tpm") for s in samples if s.get("log2_tpm") is not None]
            if vals:
                return vals, "log2_tpm"
            return [s["log2_cpm"] for s in samples], "log2_cpm"

        tumor_vals, tumor_unit = _log2tpm_or_cpm(expr.get("tumor_samples", []))
        adj_vals, adj_unit = _log2tpm_or_cpm(expr.get("adjacent_samples", []))
        gtex_vals, gtex_unit = _log2tpm_or_cpm(expr.get("gtex_samples", []))

        rows_data.append({
            "indication": ind,
            "tumor_vals": tumor_vals,
            "adjacent_vals": adj_vals,
            "gtex_vals": gtex_vals,
            "n_tumor": len(tumor_vals),
            "n_adj": len(adj_vals),
            "n_gtex": len(gtex_vals),
            "log2fc_A": (sens or {}).get("log2fc_A"),
            "padj_A":   (sens or {}).get("padj_A"),
            "log2fc_C": (sens or {}).get("log2fc_C"),
            "padj_C":   (sens or {}).get("padj_C"),
            "discordant": (sens or {}).get("discordant"),
            "cells_supporting": (sens or {}).get("cells_supporting"),
            "unit": tumor_unit if tumor_vals else "log2_cpm",
        })

    if not rows_data:
        raise RuntimeError(
            f"No expression data found for {target!r} across any indication in "
            f"{indications}"
        )

    # Sort by median tumor value (descending — highest expression first)
    rows_data.sort(
        key=lambda r: (np.median(r["tumor_vals"]) if r["tumor_vals"] else -np.inf),
        reverse=True,
    )

    n_rows = len(rows_data)
    # Layout: compact one-row-per-indication with 3 boxes stacked vertically
    # within each row (Tumor top, Adj middle, GTEx bottom). Row title moved
    # OUT of ax.set_title slot (which collided with neighbor row's data at
    # aggressive hspace) INTO the leftmost side as a horizontally-anchored
    # text block spanning the row.
    fig_height = max(4.5, 0.55 * n_rows + 0.8)
    fig, axes = plt.subplots(
        n_rows, 1, figsize=(9.5, fig_height),
        sharex=True, gridspec_kw={"hspace": 0.15, "left": 0.13, "right": 0.93},
    )
    if n_rows == 1:
        axes = np.array([axes])

    tumor_color = "#0a2540"
    adj_color = "#f0a020"
    gtex_color = "#4a7c9e"

    # Clip x-axis at the 99th percentile of all values so the meaningful
    # density (medians 2-6 log2TPM) fills the visual space instead of being
    # compressed by rare outliers (some indications have single samples out
    # at log2TPM=10 that stretch the axis without adding information).
    all_vals = [v for r in rows_data for v in (r["tumor_vals"] + r["adjacent_vals"] + r["gtex_vals"])]
    if all_vals:
        xmax = float(np.percentile(all_vals, 99)) * 1.05
    else:
        xmax = 10
    xmin = -0.3

    def _sig_stars(q):
        if q is None or q != q:
            return ""
        if q < 1e-10: return "***"
        if q < 1e-4:  return "**"
        if q < 0.05:  return "*"
        return "ns"

    # Y positions within each row (3 boxes stacked top → bottom)
    Y_TUMOR, Y_ADJ, Y_GTEX = 3, 2, 1

    for i, row in enumerate(rows_data):
        ax = axes[i]
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(0.4, 3.6)
        # Only bottom row shows x-tick labels; interior rows suppress them.
        if i < n_rows - 1:
            ax.tick_params(axis="x", labelbottom=False, length=0)
        else:
            ax.tick_params(axis="x", labelsize=7, pad=1)
        for spine_name in ("top", "right", "left"):
            ax.spines[spine_name].set_visible(False)
        ax.grid(axis="x", alpha=0.20, linewidth=0.4)
        # NOTE: y-tick suppression happens AFTER the boxplot calls below —
        # boxplot(positions=[y_pos]) re-sets ticks each call, so any
        # set_yticks([]) issued now would be silently overwritten.

        # Draw each of the three boxes at its y-position
        for vals, color, y_pos, sig_q in [
            (row["tumor_vals"],    tumor_color, Y_TUMOR, None),
            (row["adjacent_vals"], adj_color,   Y_ADJ,   row["padj_A"]),
            (row["gtex_vals"],     gtex_color,  Y_GTEX,  row["padj_C"]),
        ]:
            if not vals:
                from matplotlib.transforms import blended_transform_factory
                trans = blended_transform_factory(ax.transAxes, ax.transData)
                ax.text(0.50, y_pos, "n/a", transform=trans,
                        ha="center", va="center",
                        fontsize=6, color="#bbb", style="italic")
                continue

            bp = ax.boxplot(
                vals, vert=False, positions=[y_pos], widths=0.55,
                patch_artist=True, showfliers=False,
                medianprops={"color": "#222", "linewidth": 1.0},
            )
            for patch in bp["boxes"]:
                patch.set_facecolor(color); patch.set_alpha(0.32)
                patch.set_edgecolor(color)
            for whisker in bp["whiskers"]:
                whisker.set_color("#666"); whisker.set_linewidth(0.7)
            for cap in bp["caps"]:
                cap.set_color("#666"); cap.set_linewidth(0.7)

            # Jittered strip
            rng = np.random.default_rng(seed=42 + i * 3 + y_pos)
            yy = rng.uniform(y_pos - 0.20, y_pos + 0.20, size=len(vals))
            ax.scatter(vals, yy, s=3, color=color, alpha=0.35, edgecolor="none")

            # n annotation — placed OUTSIDE the plot area to the right of
            # the box on its y-row. Positioned using MIXED transform
            # (axes-x, data-y) so it aligns with the box's y-position
            # regardless of ylim + never collides with box contents.
            from matplotlib.transforms import blended_transform_factory
            trans = blended_transform_factory(ax.transAxes, ax.transData)
            ax.text(
                1.015, y_pos, f"n={len(vals)}",
                transform=trans,
                ha="left", va="center",
                fontsize=6, color="#666", family="monospace",
                clip_on=False,
            )

            # Significance annotation — inside plot at right edge,
            # aligned with box y-position via mixed transform.
            if sig_q is not None:
                stars = _sig_stars(sig_q)
                if stars:
                    color_star = "#0a2540" if stars in ("*", "**", "***") else "#888"
                    ax.text(
                        0.985, y_pos, stars,
                        transform=trans,
                        ha="right", va="center",
                        fontsize=8, color=color_star, weight="bold",
                    )

        # Row label — placed in the LEFT MARGIN of the axis (not as
        # ax.set_title, which collides with neighbor row's data at compact
        # hspace). Uses figure-fraction transform so it aligns with the
        # gridspec left margin.
        #
        # Badge discipline (revised): drop the misleading "n/3" cells_supporting
        # count entirely — it read as "1 of 3 cells passed" (failure-like) for
        # every indication where cells B or C simply didn't fire on the given
        # gene, even though the rule engine's cell-A signal was strong. The
        # sig-stars on the right edge already carry the actual signal per
        # comparator. Retain only:
        #   • discordant flag  (when sig cells disagree in direction)
        #   (Adj only) / (GTEx only) qualifier when a comparator was skipped
        disc_marker = " •" if row.get("discordant") else ""
        n_adj = row.get("n_adj", 0)
        n_gtex = row.get("n_gtex", 0)
        # Qualifiers name what's MISSING (accurate) rather than what's present
        # (misleading — "GTEx only" reads as "no tumor" when it really means
        # "no adjacent-normal, tumor+GTEx both present").
        if n_adj == 0 and n_gtex > 0:
            qualifier = " (no adj)"
        elif n_gtex == 0 and n_adj > 0:
            qualifier = " (no GTEx)"
        else:
            qualifier = ""
        title_str = f"{row['indication']}{disc_marker}{qualifier}"

        # Place at left margin, centered vertically on the row
        from matplotlib.transforms import blended_transform_factory
        trans_left = blended_transform_factory(fig.transFigure, ax.transAxes)
        ax.text(
            0.12, 0.5, title_str,
            transform=trans_left,
            ha="right", va="center",
            fontsize=8, weight="bold", color="#222",
            clip_on=False,
        )

        # Suppress y-ticks AFTER all boxplot calls on this axis.
        # boxplot(positions=[y_pos]) re-sets ticks each call, so any earlier
        # set_yticks([]) is silently overwritten. Doing it here strips the
        # residual "1 / 2 / 3" numeric labels that were fighting the row
        # title text on the left margin.
        ax.set_yticks([])
        ax.set_yticklabels([])

    # X-axis label on the bottom axis only (all axes share x)
    unit = rows_data[0]["unit"]
    unit_label = "log2(TPM + 1)" if unit == "log2_tpm" else "log2(CPM + 1)"
    axes[-1].set_xlabel(unit_label, fontsize=8, labelpad=2)

    # Figure title + caveat — tight against the plot area, minimal padding.
    # Use tight_layout with explicit rect to reserve just enough room for
    # title (top) and caveat (bottom), eliminating the ~40% wasted whitespace
    # bbox_inches='tight' alone was leaving in place.
    # Title + inline color legend across the top — legend replaces the
    # per-row Y-tick text and reads as a single glance-key. Bullet dots
    # match box colors so the legend visually anchors to the plot.
    #
    # Layout: title at y=0.995, legend at y=0.98 (JUST above the first
    # row), and subplots_adjust(top=0.94) so the legend has room without
    # overlapping the first row's Tumor box. Bottom stays tight.
    fig.suptitle(
        f"{target} — pan-tissue expression landscape",
        fontsize=11, weight="bold", y=0.995,
    )
    from matplotlib.lines import Line2D
    legend_handles = [
        Line2D([0], [0], marker="s", color=tumor_color, lw=0,
                markerfacecolor=tumor_color, markersize=9, label="Tumor"),
        Line2D([0], [0], marker="s", color=adj_color, lw=0,
                markerfacecolor=adj_color, markersize=9, label="TCGA Adjacent"),
        Line2D([0], [0], marker="s", color=gtex_color, lw=0,
                markerfacecolor=gtex_color, markersize=9, label="GTEx Normal"),
    ]
    fig.legend(
        handles=legend_handles,
        loc="upper center", bbox_to_anchor=(0.5, 0.955),
        ncol=3, frameon=False, fontsize=8, handletextpad=0.4,
        columnspacing=1.8,
    )

    # Move caveat below the x-axis label so they don't overlap. The
    # x-axis label sits at ~y=0.02 in figure coords; caveat gets its own
    # sub-row at y=0.005 with fig.subplots_adjust bottom=0.06 to reserve
    # space.
    fig.text(
        0.5, 0.005,
        "Sorted by median tumor expression. Sig stars: * q<0.05, ** q<1e-4, "
        "*** q<1e-10 (cells A + C). • = discordant. X clipped at q99.",
        ha="center", fontsize=6, color="#666", style="italic",
    )

    # Reserve top=0.93 (title + legend fit above without overlapping row 1),
    # bottom=0.06 (x-label + caveat fit below without overlapping row N).
    fig.subplots_adjust(top=0.93, bottom=0.06, left=0.13, right=0.93)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=300, bbox_inches="tight", pad_inches=0.05)
    fig.savefig(out_path.with_suffix(".svg"), bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    return out_path
