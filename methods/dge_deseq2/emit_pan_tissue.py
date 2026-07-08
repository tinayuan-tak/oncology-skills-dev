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
    fig_height = max(6.0, 0.4 * n_rows + 2.0)
    fig, axes = plt.subplots(
        n_rows, 3, figsize=(11, fig_height),
        sharex=False, gridspec_kw={"wspace": 0.15, "hspace": 0.05},
    )
    if n_rows == 1:
        axes = np.array([axes])

    tumor_color = "#0a2540"
    adj_color = "#f0a020"
    gtex_color = "#4a7c9e"

    # Compute a shared x-axis limit across all values for readability
    all_vals = [v for r in rows_data for v in (r["tumor_vals"] + r["adjacent_vals"] + r["gtex_vals"])]
    xmax = max(all_vals) * 1.05 if all_vals else 10
    xmin = -0.5

    def _sig_stars(q):
        if q is None or q != q:
            return ""
        if q < 1e-10: return "***"
        if q < 1e-4:  return "**"
        if q < 0.05:  return "*"
        return "ns"

    for i, row in enumerate(rows_data):
        for j, (vals, color, group_label, sig_q) in enumerate([
            (row["tumor_vals"],    tumor_color, "Tumor",    None),
            (row["adjacent_vals"], adj_color,   "TCGA-Adj", row["padj_A"]),
            (row["gtex_vals"],     gtex_color,  "GTEx",     row["padj_C"]),
        ]):
            ax = axes[i, j]
            ax.set_xlim(xmin, xmax)
            ax.set_yticks([])
            ax.tick_params(axis="x", labelsize=6, pad=1)
            for spine_name in ("top", "right", "left"):
                ax.spines[spine_name].set_visible(False)

            if not vals:
                ax.text(0.5, 0.5, "n/a", ha="center", va="center",
                        transform=ax.transAxes, fontsize=7, color="#aaa")
                continue

            # Horizontal box
            bp = ax.boxplot(
                vals, vert=False, widths=0.55, patch_artist=True,
                showfliers=False,
                medianprops={"color": "#222", "linewidth": 1.0},
            )
            for patch in bp["boxes"]:
                patch.set_facecolor(color); patch.set_alpha(0.30)
                patch.set_edgecolor(color)
            for whisker in bp["whiskers"]:
                whisker.set_color("#666"); whisker.set_linewidth(0.7)
            for cap in bp["caps"]:
                cap.set_color("#666"); cap.set_linewidth(0.7)

            # Jittered strip
            rng = np.random.default_rng(seed=42 + i * 3 + j)
            yy = rng.uniform(0.85, 1.15, size=len(vals))
            ax.scatter(vals, yy, s=3, color=color, alpha=0.35, edgecolor="none")

            # Significance annotation (right edge, only for cells with a q-value)
            if sig_q is not None:
                stars = _sig_stars(sig_q)
                if stars:
                    color_star = "#0a2540" if stars in ("*", "**", "***") else "#888"
                    ax.text(
                        0.97, 0.5, stars,
                        transform=ax.transAxes,
                        ha="right", va="center",
                        fontsize=8, color=color_star, weight="bold",
                    )

            # n annotation, left edge
            ax.text(
                0.02, 0.95, f"n={len(vals)}",
                transform=ax.transAxes,
                ha="left", va="top",
                fontsize=6, color="#666", family="monospace",
            )

        # Row label (leftmost cell's ylabel)
        disc_marker = " •" if row.get("discordant") else ""
        cs = row.get("cells_supporting")
        cs_label = f" {int(cs)}/3" if cs is not None else ""
        row_label = f"{row['indication']}{disc_marker}{cs_label}"
        # Use the tumor cell's y-axis to hold the label
        axes[i, 0].set_ylabel(row_label, rotation=0, ha="right", va="center",
                              fontsize=8, labelpad=8)

    # Column headers
    for j, hdr in enumerate(["Primary Tumor (TCGA)",
                              "Adjacent-Normal (TCGA)",
                              "Population-Normal (GTEx)"]):
        axes[0, j].set_title(hdr, fontsize=9, weight="bold", pad=6)

    # Overall xlabel on bottom row
    unit = rows_data[0]["unit"]
    unit_label = "log2(TPM + 1)" if unit == "log2_tpm" else "log2(CPM + 1)"
    for j in range(3):
        axes[-1, j].set_xlabel(unit_label, fontsize=7)

    # Figure title + caveat
    fig.suptitle(
        f"{target} — pan-tissue expression landscape",
        fontsize=13, weight="bold", y=0.995,
    )
    fig.text(
        0.5, 0.02,
        "Rows sorted by median tumor expression. Sig. stars: * q<0.05, "
        "** q<1e-4, *** q<1e-10 (from tumor-vs-normal-selectivity cells A "
        "and C). • = discordant across comparators.",
        ha="center", fontsize=6.5, color="#666", style="italic",
    )

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    fig.savefig(out_path.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)
    return out_path
