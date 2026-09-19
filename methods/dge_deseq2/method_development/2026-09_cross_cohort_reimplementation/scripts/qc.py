"""Scientific QC of the TCGA DGE 'sensitivity' family: volcano, MA, p-distribution,
and within-product A-vs-C concordance. Read-only S3 pulls; writes PNGs to <OUT>/plots
and summary.json to <OUT>.

OUT defaults to this arc's outputs/ dir; override with DGE_QC_OUT. Motivating QC for the
cross-cohort reimplementation (see ../README.md). Run on demand, NOT a unit test."""

import io
import json
import os
from pathlib import Path

os.environ.pop("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", None)  # container creds outrank AWS_PROFILE
import boto3
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

BUCKET = "onc-compbio"
OUT = os.environ.get("DGE_QC_OUT") or str(Path(__file__).resolve().parent.parent / "outputs")
PLOTS = os.path.join(OUT, "plots")
os.makedirs(PLOTS, exist_ok=True)
cli = boto3.Session(profile_name="cbg").client("s3")

PANEL = {
    "brca": ("data-catalog/derived/brca-dge-tumor-vs-normal-sensitivity-v1/sensitivity.parquet", "both n=1127/114/482"),
    "paad": (
        "data-catalog/derived/paad-dge-tumor-vs-normal-sensitivity-v1/sensitivity.parquet",
        "both n_adj=4/n_gtex=360",
    ),
    "sclc": (
        "data-catalog/derived/sclc-dge-tumor-vs-normal-sensitivity-v1/sensitivity.parquet",
        "George-vs-GTEx, A/B all-NaN",
    ),
    "tgct": (
        "data-catalog/derived/tgct-dge-tumor-vs-normal-sensitivity-v1/sensitivity.parquet",
        "gtex-only n_gtex=410",
    ),
    "coadread_welch": ("data-catalog/derived/coadread-dge-tumor-vs-gtex-v1/tumor_vs_gtex.parquet", "Welch-t log2CPM"),
    "coadread_gdc": (
        "data-catalog/derived/COADREAD-dge/df06320/tumor_vs_adjacent.parquet",
        "DESeq2 GDC, tumor-vs-adjacent only",
    ),
}


def load(key):
    body = cli.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    return pd.read_parquet(io.BytesIO(body))


# effect/padj/rawp/abundance column resolution per product
CELLS = {  # label -> (lfc, padj, rawp, cellname)
    "sensitivity": [
        ("log2fc_A", "padj_A", None, "A: tumor-vs-adjacent"),
        ("log2fc_B", "padj_B", None, "B: tumor-vs-adjacent(2)"),
        ("log2fc_C", "padj_C", None, "C: tumor-vs-GTEx"),
    ],
}


def volcano(ax, lfc, padj, title):
    m = lfc.notna() & padj.notna()
    x = lfc[m].to_numpy()
    p = padj[m].to_numpy()
    floor = max(np.nanmin(p[p > 0]) / 2 if (p > 0).any() else 1e-300, 1e-300)
    y = -np.log10(np.clip(p, floor, 1))
    sig = p < 0.05
    ax.scatter(x[~sig], y[~sig], s=2, c="#b0b0b0", alpha=0.4, rasterized=True)
    ax.scatter(x[sig], y[sig], s=2, c="#c0392b", alpha=0.5, rasterized=True)
    ax.axhline(-np.log10(0.05), ls=":", c="k", lw=0.8)
    ax.axvline(0, ls=":", c="k", lw=0.6)
    ax.set_title(f"{title}\nsig={sig.mean():.1%} n={m.sum()}", fontsize=8)
    ax.set_xlabel("log2FC")
    ax.set_ylabel("-log10(padj)")


def pdist(ax, p, label, adjusted):
    p = p.dropna().to_numpy()
    ax.hist(p, bins=40, range=(0, 1), color="#2c7fb8", edgecolor="w", lw=0.3)
    ax.axhline(len(p) / 40, ls="--", c="k", lw=0.8)  # uniform-null expectation
    kind = "padj" if adjusted else "raw p"
    ax.set_title(f"{label} {kind} dist\nfrac<0.05={(p < 0.05).mean():.1%}", fontsize=8)
    ax.set_xlabel(kind)
    ax.set_ylabel("count")


def ma(ax, A, M, sig, title):
    ax.scatter(A[~sig], M[~sig], s=2, c="#b0b0b0", alpha=0.4, rasterized=True)
    ax.scatter(A[sig], M[sig], s=2, c="#c0392b", alpha=0.5, rasterized=True)
    ax.axhline(0, ls=":", c="k", lw=0.8)
    ax.set_title(f"{title}  median M={np.nanmedian(M):+.3f}", fontsize=8)
    ax.set_xlabel("A = mean log2 abundance")
    ax.set_ylabel("M = log2FC")


summary = {}
for name, (key, desc) in PANEL.items():
    df = load(key)
    cols = list(df.columns)
    print(f"\n=== {name} :: {desc}\n cols={cols}\n n={len(df)}")
    s = {"desc": desc, "n_rows": int(len(df)), "columns": cols, "cells": {}}

    if name == "coadread_welch":
        panels = [("log2_fc", "q_value", "p_value", "tumor-vs-GTEx (Welch)")]
        A = 0.5 * (df["mean_log2cpm_tumor"] + df["mean_log2cpm_gtex_normal"])
        Acol = "welch"
    elif name == "coadread_gdc":
        panels = [("log2FoldChange", "padj", "pvalue", "tumor-vs-adjacent (DESeq2)")]
        A = np.log2(df["baseMean"].clip(lower=1e-3))
        Acol = "deseq2"
    else:
        panels = [(l, pj, rp, cn) for (l, pj, rp, cn) in CELLS["sensitivity"] if l in cols]
        A = None
        Acol = None

    live = [(l, pj, rp, cn) for (l, pj, rp, cn) in panels if l in cols and df[l].notna().any()]
    ncol = len(live) + 1 + (1 if A is not None else 0)
    fig, axes = plt.subplots(1, ncol, figsize=(4.2 * ncol, 3.8))
    if ncol == 1:
        axes = [axes]
    ai = 0
    for l, pj, rp, cn in live:
        volcano(axes[ai], df[l], df[pj], cn)
        ai += 1
        s["cells"][cn] = {
            "lfc_col": l,
            "sig_padj": float((df[pj] < 0.05).mean()),
            "median_abs_lfc": float(np.nanmedian(df[l].abs())),
            "raw_p_frac_lt05": float((df[rp] < 0.05).mean()) if rp and rp in cols else None,
        }
    # p-distribution: prefer raw p (calibration instrument); fall back to padj
    rp0 = next((rp for (_, _, rp, _) in live if rp and rp in cols), None)
    if rp0:
        pdist(axes[ai], df[rp0], name, adjusted=False)
    else:
        pdist(axes[ai], df[live[0][1]], name, adjusted=True)
    ai += 1
    if A is not None:
        l, pj = live[0][0], live[0][1]
        m = A.notna() & df[l].notna() & df[pj].notna()
        ma(axes[ai], A[m].to_numpy(), df[l][m].to_numpy(), (df[pj][m] < 0.05).to_numpy(), f"{name} MA")
    fig.suptitle(f"{name} — {desc}", fontsize=10)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(f"{PLOTS}/{name}.png", dpi=110)
    plt.close(fig)
    summary[name] = s

# --- within-product A-vs-C concordance for fused products that have both live ---
for name in ("brca", "paad"):
    df = load(PANEL[name][0])
    m = df["log2fc_A"].notna() & df["log2fc_C"].notna()
    a, c = df["log2fc_A"][m].to_numpy(), df["log2fc_C"][m].to_numpy()
    r = np.corrcoef(a, c)[0, 1]
    fig, ax = plt.subplots(figsize=(4.6, 4.4))
    ax.scatter(a, c, s=2, alpha=0.3, rasterized=True)
    lim = np.nanpercentile(np.abs(np.r_[a, c]), 99.5)
    ax.plot([-lim, lim], [-lim, lim], "r--", lw=0.8)
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_xlabel("log2FC_A (tumor-vs-adjacent, within-TCGA)")
    ax.set_ylabel("log2FC_C (tumor-vs-GTEx, cross-cohort)")
    ax.set_title(
        f"{name}: A vs C concordance  r={r:.3f}\nsig_A={(df['padj_A'] < 0.05).mean():.1%}  sig_C={(df['padj_C'] < 0.05).mean():.1%}",
        fontsize=9,
    )
    fig.tight_layout()
    fig.savefig(f"{PLOTS}/concordance_{name}.png", dpi=110)
    plt.close(fig)
    summary.setdefault("concordance", {})[name] = {
        "pearson_A_C": float(r),
        "sig_A": float((df["padj_A"] < 0.05).mean()),
        "sig_C": float((df["padj_C"] < 0.05).mean()),
    }

json.dump(summary, open(f"{OUT}/summary.json", "w"), indent=2)
print("\n=== SUMMARY ===")
print(json.dumps(summary, indent=2))
print("\nplots:", sorted(os.listdir(PLOTS)))
