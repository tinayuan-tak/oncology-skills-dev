"""sc_normal_expression — build_summary entry point for the compose-dashboard live-reader.

`build_summary(target, indication) -> dict` is the single entry point the skills dispatcher
invokes. Mirrors the sc_tumor_expression_celltype/cli.py contract: deterministic
(target, indication) → summary dict with a primary `sc_normal_expression_class` categorical
and a data_unavailable-safe branch.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import read as _read

METHOD_VERSION = "0.1.0"


def build_summary(target: str, indication: str) -> dict:
    """sc-normal-celltype-expression Tier-1 summary for a (target, indication).

    Returns the normal-tissue liability class, max-detection cell type, safety-essential
    flags, and breadth indicator. data_unavailable-safe for missing products or genes."""
    summary = _read.read_target_summary(target, indication)
    summary["method_version"] = METHOD_VERSION
    return summary


def emit_normal_celltype_liability(summary: dict, target: str, out_dir, target_contracts=None) -> None:
    """Render the normal-tissue per-cell-type liability figure to
    figure_sc_normal_celltype_liability.svg — a ranked horizontal bar of the most-detected normal
    cell types (from `per_cell_type_top`), with SAFETY-ESSENTIAL cell types highlighted (the
    on-target-toxicity concern: cardiomyocyte / hepatocyte / neuron / nephron / marrow). This is the
    therapeutic-window framing the presence read needs; the safety verdict itself is owned by
    on-target-safety-liability. Self-contained matplotlib (import-guarded). No-op when there is
    nothing to plot (data_unavailable / no reliable cell types)."""
    rows = (summary or {}).get("per_cell_type_top") or []
    if not rows:
        return
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from pathlib import Path as _Path

    out_dir = _Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = sorted(rows, key=lambda r: r.get("median_detection_fraction") or 0.0)  # ascending → top at top
    labels = [f"{r['cell_type']}" + (f" · {r['tissue']}" if r.get("tissue") else "") for r in rows]
    vals = [r.get("median_detection_fraction") or 0.0 for r in rows]
    # safety-essential (critical-organ) cell types in red; all others neutral gray-blue.
    colors = ["#b2182b" if r.get("is_safety_essential") else "#92b8d8" for r in rows]
    fig, ax = plt.subplots(figsize=(6.2, max(2.4, 0.34 * len(rows) + 0.8)))
    ax.barh(range(len(rows)), vals, color=colors)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(labels, fontsize=7)
    ax.set_xlim(0, 1)
    ax.set_xlabel("cross-donor median detection fraction (normal tissue)", fontsize=8)
    liab = str((summary or {}).get("sc_normal_expression_class", "") or "").replace("_", " ")
    ess = str((summary or {}).get("sc_normal_safety_essential_class", "") or "").replace("_", " ")
    sub = " · ".join([s for s in (liab, ess if ess and ess != "none" else "") if s])
    ax.set_title(f"{target} — normal-tissue single-cell footprint" + (f"\n{sub}" if sub else ""), fontsize=8.5)
    from matplotlib.patches import Patch

    ax.legend(
        handles=[
            Patch(color="#b2182b", label="safety-essential cell type"),
            Patch(color="#92b8d8", label="other normal cell type"),
        ],
        fontsize=6.5,
        loc="lower right",
        frameon=False,
    )
    fig.tight_layout()
    fig.savefig(out_dir / "figure_sc_normal_celltype_liability.svg", format="svg")
    plt.close(fig)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="sc normal-tissue cell-type expression summary.")
    ap.add_argument("--target", required=True, help="HGNC gene symbol")
    ap.add_argument("--indication", required=True, help="OncoTree indication code (e.g. COADREAD, NSCLC)")
    args = ap.parse_args(argv)
    print(json.dumps(build_summary(args.target, args.indication), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
