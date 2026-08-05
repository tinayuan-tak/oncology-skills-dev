"""sc_tumor_expression_celltype — the build_* entry points the compose-dashboard live-reader calls.

`build_summary(target, indication) -> dict` is the single entry point the skills dispatcher
(_live_readers.py::CARD_DISPATCHERS["tumor-scrna-celltype-expression"]) invokes. Mirrors the
tcga_gtex_expression_distribution/cli.py contract: a deterministic (target, indication) -> summary
dict with a primary `*_class` categorical and a data_unavailable-safe branch.
"""
from __future__ import annotations

import argparse
import json
import sys

from . import read as _read

METHOD_VERSION = "0.1.0"


def build_summary(target: str, indication: str) -> dict:
    """Single-cell per-compartment tumor presence for a (target, indication): the malignant-anchored
    `sc_expression_class` + per-compartment detection + microenvironment-attribution readout, from the
    donor×compartment pseudobulk product. data_unavailable-safe."""
    summary = _read.read_sc_expression_presence(target, indication)
    summary["method_version"] = METHOD_VERSION
    return summary


def emit_compartment_bar(summary: dict, target: str, out_dir, target_contracts=None) -> None:
    """Render the per-compartment detection-fraction bar (malignant highlighted) to
    figure_sc_compartment_detection.svg in out_dir. Self-contained matplotlib (import-guarded so the
    pure-data read path never needs it). No-op when there is nothing to plot."""
    comp_det = (summary or {}).get("compartment_detection") or {}
    if not comp_det:
        return
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from pathlib import Path as _Path
    out_dir = _Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # order: malignant first, then microenvironment by detection, then the rest
    order = sorted(comp_det, key=lambda c: (c != "malignant", -(comp_det[c] or 0.0)))
    vals = [comp_det[c] if comp_det[c] is not None else 0.0 for c in order]
    colors = ["#b2182b" if c == "malignant" else "#4393c3" for c in order]
    fig, ax = plt.subplots(figsize=(5.5, 3.2))
    ax.bar(range(len(order)), vals, color=colors)
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels(order, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("cross-donor median detection fraction", fontsize=8)
    ax.set_ylim(0, 1)
    ax.set_title(f"{target} — single-cell detection by compartment ({summary.get('indication','')})",
                 fontsize=9)
    fig.tight_layout()
    fig.savefig(out_dir / "figure_sc_compartment_detection.svg", format="svg")
    plt.close(fig)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="single-cell per-compartment tumor presence.")
    ap.add_argument("--target", required=True, help="HGNC gene symbol")
    ap.add_argument("--indication", required=True, help="OncoTree indication code (e.g. COADREAD, NSCLC)")
    args = ap.parse_args(argv)
    print(json.dumps(build_summary(args.target, args.indication), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
