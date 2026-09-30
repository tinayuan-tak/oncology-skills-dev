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
    """Render the per-compartment single-cell presence figure to figure_sc_compartment_detection.svg.

    Uses the full `per_compartment` vector (detection fraction + abundance + CAF flag + donor support)
    rather than detection alone, so the reader sees malignant-vs-microenvironment attribution, which
    compartments are cancer-associated-fibroblast (a stromal confounder), and how the abundance tracks
    the detection. Malignant is highlighted; CAF/stromal compartments are marked. The title carries the
    malignant detection fraction + the TCE-relevant homogeneity class. Falls back to the detection-only
    `compartment_detection` dict for older summaries. Self-contained matplotlib (import-guarded so the
    pure-data read path never needs it). No-op when there is nothing to plot."""
    per_comp = (summary or {}).get("per_compartment") or []
    comp_det = (summary or {}).get("compartment_detection") or {}
    if not per_comp and not comp_det:
        return
    # Normalize to a list of per-compartment records (detection + optional abundance/CAF).
    if per_comp:
        recs = [
            {
                "compartment": r.get("compartment"),
                "det": r.get("median_detection_fraction") or 0.0,
                "abund": r.get("median_abundance_log1p_cp10k"),
                "is_caf": bool(r.get("is_caf")),
            }
            for r in per_comp
        ]
    else:
        recs = [
            {"compartment": c, "det": comp_det[c] or 0.0, "abund": None, "is_caf": c == "stromal"} for c in comp_det
        ]
    # malignant first, then remaining compartments by detection (descending).
    recs.sort(key=lambda r: (r["compartment"] != "malignant", -(r["det"] or 0.0)))

    import matplotlib

    matplotlib.use("Agg")
    from pathlib import Path as _Path

    import matplotlib.pyplot as plt

    out_dir = _Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    labels = [r["compartment"] for r in recs]
    vals = [r["det"] for r in recs]
    # malignant = signal (red); CAF/stromal = confounder (orange); other microenvironment = blue.
    colors = ["#b2182b" if r["compartment"] == "malignant" else "#e08214" if r["is_caf"] else "#4393c3" for r in recs]
    fig, ax = plt.subplots(figsize=(5.8, 3.3))
    bars = ax.bar(range(len(recs)), vals, color=colors)
    ax.set_xticks(range(len(recs)))
    ax.set_xticklabels([lb.replace("_", " ") for lb in labels], rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("cross-donor median detection fraction", fontsize=8)
    ax.set_ylim(0, 1)
    # annotate abundance (log1p CP10K) above each bar when available — the intensity behind detection.
    for bar, r in zip(bars, recs):
        if r["abund"] is not None:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                min(r["det"] + 0.03, 0.97),
                f"{r['abund']:.1f}",
                ha="center",
                va="bottom",
                fontsize=6.5,
                color="#555555",
            )
    hom = (summary or {}).get("tce_homogeneity_class")
    mal = (summary or {}).get("malignant_detection_fraction")
    sub = []
    if isinstance(mal, (int, float)):
        sub.append(f"malignant {round(mal * 100)}%")
    if hom and hom != "data_unavailable":
        sub.append(hom.replace("_", " "))
    subtitle = ("\n" + " · ".join(sub)) if sub else ""
    ax.set_title(
        f"{target} — single-cell presence by compartment ({summary.get('indication', '')}){subtitle}", fontsize=8.5
    )
    # legend clarifies the CAF/stromal confounder color (annotation, not color-alone).
    from matplotlib.patches import Patch

    ax.legend(
        handles=[
            Patch(color="#b2182b", label="malignant (signal)"),
            Patch(color="#e08214", label="CAF / stromal (confounder)"),
            Patch(color="#4393c3", label="other microenvironment"),
        ],
        fontsize=6.5,
        loc="upper right",
        frameon=False,
    )
    fig.tight_layout()
    fig.subplots_adjust(bottom=0.30)
    fig.text(0.02, 0.02, "bar labels = median abundance (log1p CP10K)", fontsize=6, color="#888888")
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
