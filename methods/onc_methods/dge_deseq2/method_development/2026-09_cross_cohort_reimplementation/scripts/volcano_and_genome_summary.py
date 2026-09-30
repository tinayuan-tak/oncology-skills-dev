#!/usr/bin/env python
"""volcano_and_genome_summary.py — Stage-1 calibration visualization.

Reads the per-cell TSVs (gene_symbol, log2fc, padj, svalue, baseMean) written by
run_calibration_cells.R for each (substrate, indication) and produces:

  1. A 4-row (substrate/indication) x 3-col (cell A / C / Cr) volcano grid:
     x = log2FC, y = -log10(padj), colored by significance direction at the
     shipped effect-size gate (padj < 0.05 AND |log2FC| >= log2(1.5)).
  2. A genome-wide summary-stats table (markdown + CSV): per cell, n tested,
     n/frac significant (padj-only and padj+effect-gate and s-value gate),
     median |log2FC|, up/down split, median baseMean.

Cell A = within-TCGA anchor; C = naive cross-cohort; Cr = RUVg-corrected.
"""

import math
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

WORK = Path(os.environ.get("DGE_CALIB_WORK", "/home/sagemaker-user/dge_calib_work"))
HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "outputs"
PLOTS = OUT / "plots"
PLOTS.mkdir(parents=True, exist_ok=True)

LFC_GATE = math.log2(1.5)  # 0.585 — the apeglm lfcThreshold
Q = 0.05
COMBOS = [("recount3", "brca"), ("recount3", "paad"), ("xena-toil", "brca"), ("xena-toil", "paad")]
CELLS = ["A", "C", "Cr"]
CELL_TITLE = {"A": "A · within-TCGA (anchor)", "C": "C · naive cross-cohort", "Cr": "Cr · RUVg-corrected"}


def load_cell(substrate, ind, cell):
    p = WORK / f"cells__{substrate}__{ind}" / f"cell_{cell}.tsv"
    if not p.exists():
        return None
    df = pd.read_csv(p, sep="\t")
    return df


def sig_mask(df):
    padj = df["padj"].to_numpy()
    lfc = df["log2fc"].to_numpy()
    ok = np.isfinite(padj) & np.isfinite(lfc)
    return ok & (padj < Q) & (np.abs(lfc) >= LFC_GATE)


# ---- volcano grid ----------------------------------------------------------
fig, axes = plt.subplots(len(COMBOS), len(CELLS), figsize=(15, 18), sharex=False, sharey=False)
for r, (sub, ind) in enumerate(COMBOS):
    for c, cell in enumerate(CELLS):
        ax = axes[r, c]
        df = load_cell(sub, ind, cell)
        if df is None:
            ax.set_axis_off()
            ax.text(0.5, 0.5, f"{sub}/{ind}\ncell {cell}\n(absent)", ha="center", va="center")
            continue
        padj = df["padj"].to_numpy()
        lfc = df["log2fc"].to_numpy()
        ok = np.isfinite(padj) & np.isfinite(lfc)
        # clip -log10(padj) so a handful of ~0 padj genes don't crush the axis
        y = np.full_like(padj, np.nan, dtype=float)
        y[ok] = -np.log10(np.clip(padj[ok], 1e-300, 1.0))
        ycap = 60.0
        y = np.clip(y, 0, ycap)
        up = ok & (padj < Q) & (lfc >= LFC_GATE)
        dn = ok & (padj < Q) & (lfc <= -LFC_GATE)
        ns = ok & ~(up | dn)
        ax.scatter(lfc[ns], y[ns], s=2, c="#b0b0b0", alpha=0.3, rasterized=True)
        ax.scatter(lfc[dn], y[dn], s=2, c="#2c7fb8", alpha=0.5, rasterized=True)
        ax.scatter(lfc[up], y[up], s=2, c="#d7301f", alpha=0.5, rasterized=True)
        ax.axvline(LFC_GATE, ls=":", c="k", lw=0.6)
        ax.axvline(-LFC_GATE, ls=":", c="k", lw=0.6)
        ax.axhline(-math.log10(Q), ls=":", c="k", lw=0.6)
        ax.set_xlim(-12, 12)
        ax.set_ylim(0, ycap + 2)
        nsig = int((up | dn).sum())
        ntot = int(ok.sum())
        ax.set_title(
            f"{sub}/{ind} — {CELL_TITLE[cell]}\nsig={nsig:,}/{ntot:,} ({100 * nsig / max(ntot, 1):.0f}%)", fontsize=8
        )
        if c == 0:
            ax.set_ylabel("-log10(padj)", fontsize=8)
        if r == len(COMBOS) - 1:
            ax.set_xlabel("log2 fold-change", fontsize=8)
        ax.tick_params(labelsize=7)
fig.suptitle(
    "Cross-cohort DGE calibration — volcano by substrate × cell "
    f"(sig = padj<{Q} & |log2FC|≥log2(1.5)); y clipped at 60",
    fontsize=11,
    y=0.995,
)
fig.tight_layout(rect=[0, 0, 1, 0.985])
vpath = PLOTS / "volcano_grid.png"
fig.savefig(vpath, dpi=130)
plt.close(fig)
print(f"wrote {vpath}")

# ---- genome-wide summary stats --------------------------------------------
rows = []
for sub, ind in COMBOS:
    for cell in CELLS:
        df = load_cell(sub, ind, cell)
        if df is None:
            continue
        padj = df["padj"].to_numpy()
        lfc = df["log2fc"].to_numpy()
        sval = df["svalue"].to_numpy() if "svalue" in df else np.full(len(df), np.nan)
        bm = df["baseMean"].to_numpy() if "baseMean" in df else np.full(len(df), np.nan)
        ok = np.isfinite(padj) & np.isfinite(lfc)
        sig_p = ok & (padj < Q)
        sig_g = sig_p & (np.abs(lfc) >= LFC_GATE)
        sig_s = np.isfinite(sval) & (sval < 0.005) & (np.abs(lfc) >= LFC_GATE)
        rows.append(
            {
                "substrate": sub,
                "indication": ind,
                "cell": cell,
                "n_tested": int(ok.sum()),
                "n_sig_padj": int(sig_p.sum()),
                "frac_sig_padj": round(sig_p.sum() / max(ok.sum(), 1), 4),
                "n_sig_padj_lfc": int(sig_g.sum()),
                "n_sig_svalue_lfc": int(sig_s.sum()),
                "n_up_gated": int((sig_g & (lfc >= LFC_GATE)).sum()),
                "n_down_gated": int((sig_g & (lfc <= -LFC_GATE)).sum()),
                "median_abs_lfc": round(float(np.nanmedian(np.abs(lfc[ok]))), 4),
                "median_baseMean": round(float(np.nanmedian(bm[np.isfinite(bm)])), 2)
                if np.isfinite(bm).any()
                else None,
            }
        )
summary = pd.DataFrame(rows)
csv_path = OUT / "genome_summary.csv"
summary.to_csv(csv_path, index=False)
print(f"wrote {csv_path}")

# markdown
md = [
    "# Genome-wide summary stats — Stage-1 calibration cells",
    "",
    f"Effect gate = |log2FC| ≥ log2(1.5) = {LFC_GATE:.3f}; padj/s-value cutoffs "
    f"padj<{Q}, svalue<0.005. Cell A = within-TCGA anchor; C = naive "
    "cross-cohort; Cr = RUVg-corrected.",
    "",
    "| substrate | ind | cell | n tested | n sig (padj) | frac sig | "
    "n sig (padj+lfc) | n sig (svalue+lfc) | up | down | median\\|lfc\\| | median baseMean |",
    "|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|",
]
for _, x in summary.iterrows():
    md.append(
        f"| {x.substrate} | {x.indication} | {x.cell} | {x.n_tested:,} | "
        f"{x.n_sig_padj:,} | {x.frac_sig_padj:.3f} | {x.n_sig_padj_lfc:,} | "
        f"{x.n_sig_svalue_lfc:,} | {x.n_up_gated:,} | {x.n_down_gated:,} | "
        f"{x.median_abs_lfc:.3f} | {x.median_baseMean} |"
    )
md_path = OUT / "genome_summary.md"
md_path.write_text("\n".join(md) + "\n")
print(f"wrote {md_path}")
print("\n".join(md))
