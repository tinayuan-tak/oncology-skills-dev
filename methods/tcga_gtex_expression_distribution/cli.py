#!/usr/bin/env python3
"""tcga-gtex-expression-distribution CLI — per-sample tumor expression distribution (Q1).

Emits the expression-build bar (Tier1 summary.json + Tier2 plot_data.parquet + Tier3 SVG + plotly,
threaded into the manifest) for the per-sample TUMOR distribution of a target in an indication,
plus the matched-normal GTEx arm for the Q2 fraction-above-normal-percentile overlay.

Reads the two long products via read.py (predicate-pushdown, cached). data_unavailable-safe.

Usage:
    python -m methods.tcga_gtex_expression_distribution.cli \\
        --target KRAS --indication COADREAD --out ~/dev/framework-runs/kras-coadread-exprdist
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from . import read as _read
from . import stats as _stats

METHOD_VERSION = "0.1.0"
DEFAULT_TARGET_CONTRACTS = "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"

_TUMOR_FILL, _TUMOR_LINE = "#1f4e79", "#0a2540"
_NORMAL_FILL, _NORMAL_LINE = "#a9c5db", "#5b7f99"


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def build_summary(target: str, indication: str) -> dict:
    """Q1 tumor distribution + the Q2 fraction-above-normal-p95/p99 overlay (matched GTEx normal)."""
    summary = _read.read_tumor_expression_distribution(target, indication)
    tumor = _read.read_tumor_samples(target, indication)
    normal, tissue = _read.read_normal_samples(target, indication)
    summary["matched_normal_tissue"] = tissue
    summary["n_normal_samples"] = len(normal)
    # Q2 headline enrichment metric at p95 + p99 (normal-relative cutoffs).
    for pct in (95, 99):
        fa = _stats.fraction_above_normal_percentile(tumor, normal, pct)
        summary[f"fraction_tumor_above_normal_p{pct}"] = fa["fraction_tumor_above"]
        summary[f"normal_p{pct}_log2tpm"] = fa["normal_pN"]
    summary["distribution_overlap_tumor_normal"] = _stats.distribution_overlap(tumor, normal)
    # Subtype layer (COMPUTE-ALL): fan out over the indication's assignment shard, if landed.
    # The landscape assembler returns the pooled summary as its base + the subtype-specific
    # keys; take ONLY the subtype keys here so the pooled/normal fields above stay the single
    # source of truth (no recomputation drift). No shard for the indication → axis_unavailable.
    land = _read.read_tumor_expression_subtype_landscape(target, indication)
    for k in ("subtype_axis_available", "subtype_landscape", "spotlight_subtype",
              "n_subtypes_measured", "n_subtypes_enriched", "assignment_manifest",
              "_subtype_note"):
        if k in land:
            summary[k] = land[k]
    summary["method_version"] = METHOD_VERSION
    return summary


def emit_plot_data(target: str, indication: str, out_dir: Path) -> Path:
    """Tier-2: the per-sample long-format rows behind the figure (tumor + matched normal)."""
    import pandas as pd
    tumor = _read.read_tumor_samples(target, indication)
    normal, tissue = _read.read_normal_samples(target, indication)
    rows = ([{"group": "tumor", "source": "TCGA", "log2_tpm": v} for v in tumor]
            + [{"group": "normal", "source": f"GTEx:{tissue}", "log2_tpm": v} for v in normal])
    out = Path(out_dir) / "plot_data_expression_distribution.parquet"
    pd.DataFrame(rows, columns=["group", "source", "log2_tpm"]).to_parquet(out, index=False)
    return out


def _load_style(contracts_dir):
    try:
        import matplotlib.pyplot as plt
        style = Path(contracts_dir) / "plot_styles" / "takeda_oncology.mplstyle"
        if style.exists():
            plt.style.use(str(style))
    except Exception:  # noqa: BLE001
        pass


def emit_svg(target: str, indication: str, summary: dict, out_dir: Path,
             contracts_dir=DEFAULT_TARGET_CONTRACTS) -> Path:
    """Tier-3 SVG: tumor vs matched-normal per-sample distribution (box + strip), with the
    normal-p95 line + fraction-above annotation."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    _load_style(contracts_dir)
    out_path = Path(out_dir) / "figure_expression_distribution.svg"

    tumor = _read.read_tumor_samples(target, indication)
    normal, tissue = _read.read_normal_samples(target, indication)
    if not tumor:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, f"{target} — no TCGA tumor samples for {indication}", ha="center",
                va="center", fontsize=10, color="#777"); ax.set_axis_off()
        fig.savefig(out_path); plt.close(fig); return out_path

    groups, labels, colors = [tumor], [f"TCGA tumor\n(n={len(tumor)})"], [(_TUMOR_FILL, _TUMOR_LINE)]
    if normal:
        groups.append(normal); labels.append(f"GTEx {tissue}\n(n={len(normal)})")
        colors.append((_NORMAL_FILL, _NORMAL_LINE))

    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    bp = ax.boxplot(groups, orientation="horizontal", widths=0.55, patch_artist=True,
                    showfliers=False, medianprops={"color": "#222", "linewidth": 1.3})
    for patch, (fill, line) in zip(bp["boxes"], colors):
        patch.set(facecolor=fill, edgecolor=line, alpha=0.5, linewidth=1.0)
    rng = np.random.default_rng(seed=42)
    for i, (vals, (fill, line)) in enumerate(zip(groups, colors)):
        yy = rng.uniform(i + 1 - 0.16, i + 1 + 0.16, size=len(vals))
        ax.scatter(vals, yy, s=5, color=line, alpha=0.35, edgecolor="none", zorder=3)
    # normal p95 line + fraction-above annotation
    p95 = summary.get("normal_p95_log2tpm")
    fa95 = summary.get("fraction_tumor_above_normal_p95")
    if p95 is not None:
        ax.axvline(p95, color="#cf2828", linewidth=1.0, linestyle="--", zorder=1)
        if fa95 is not None:
            ax.text(p95, len(groups) + 0.5, f"{fa95*100:.0f}% of tumors > normal p95",
                    color="#cf2828", fontsize=7, ha="left", va="bottom")
    ax.set_yticks(range(1, len(labels) + 1)); ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("log2(TPM + 1) — recount3 / GENCODE v26 (per sample)")
    ax.set_title(f"{target} in {indication} — per-sample expression "
                 f"({summary.get('tumor_expression_class', '')}, {summary.get('distribution_pattern','')})")
    ax.grid(axis="x", alpha=0.25, linewidth=0.4)
    fig.tight_layout(); fig.savefig(out_path); plt.close(fig)
    return out_path


def emit_plotly_specs(target: str, indication: str, out_dir: Path,
                      contracts_dir=DEFAULT_TARGET_CONTRACTS) -> list:
    """Interactive twin — same per-sample values as the SVG (no drift). Best-effort."""
    try:
        import plotly.graph_objects as go
    except Exception as e:  # noqa: BLE001
        _log(f"[expr-dist] plotly skipped: {e}")
        return []
    tumor = _read.read_tumor_samples(target, indication)
    normal, tissue = _read.read_normal_samples(target, indication)
    if not tumor:
        return []
    fig = go.Figure()
    fig.add_trace(go.Box(x=tumor, name=f"TCGA tumor (n={len(tumor)})", orientation="h",
                         marker_color=_TUMOR_LINE, fillcolor=_TUMOR_FILL, line=dict(width=1),
                         boxpoints="all", jitter=0.4, pointpos=0, marker=dict(size=3, opacity=0.4)))
    if normal:
        fig.add_trace(go.Box(x=normal, name=f"GTEx {tissue} (n={len(normal)})", orientation="h",
                             marker_color=_NORMAL_LINE, fillcolor=_NORMAL_FILL, line=dict(width=1),
                             boxpoints="all", jitter=0.4, pointpos=0, marker=dict(size=3, opacity=0.4)))
    fig.update_layout(title=f"{target} in {indication} — per-sample expression distribution",
                      xaxis_title="log2(TPM + 1) — recount3 / GENCODE v26",
                      template="plotly_white", margin=dict(l=120, r=40, t=50, b=50))
    (Path(out_dir) / "figure_expression_distribution.plotly.json").write_text(fig.to_json())
    return [{"id": "expression_distribution_per_sample",
             "path": "figure_expression_distribution.plotly.json", "type": "plotly"}]


def emit_manifest(target: str, indication: str, summary: dict, out_dir: Path,
                  plotly_specs: Optional[list] = None) -> Path:
    """Tier-describing manifest with the plotly_figures slot (matches the expression bar)."""
    manifest = {
        "method": "tcga_gtex_expression_distribution", "method_version": METHOD_VERSION,
        "target": target, "indication": indication,
        "tumor_expression_class": summary.get("tumor_expression_class"),
        "n_tumor_samples": summary.get("n_tumor_samples"),
        "artifacts": {"summary": "summary.json",
                      "plot_data": "plot_data_expression_distribution.parquet",
                      "svg": "figure_expression_distribution.svg"},
        "plotly_figures": plotly_specs or [],
    }
    out = Path(out_dir) / "manifest.json"
    out.write_text(json.dumps(manifest, indent=2, default=str))
    return out


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--target-contracts", default=DEFAULT_TARGET_CONTRACTS)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    summary = build_summary(args.target, args.indication)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    emit_plot_data(args.target, args.indication, args.out)
    emit_svg(args.target, args.indication, summary, args.out, args.target_contracts)
    specs = emit_plotly_specs(args.target, args.indication, args.out, args.target_contracts)
    emit_manifest(args.target, args.indication, summary, args.out, specs)
    _log(f"[expr-dist] {args.target}/{args.indication}: "
         f"{summary.get('tumor_expression_class')} "
         f"n={summary.get('n_tumor_samples')} -> {args.out} (plotly {len(specs)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
