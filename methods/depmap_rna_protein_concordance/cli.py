"""CLI + emitters for Q5 RNA↔protein concordance (cell-line)."""

from __future__ import annotations
import os

import json
from pathlib import Path

from . import read as _read

METHOD_VERSION = "0.1.0"
DEFAULT_TARGET_CONTRACTS = os.environ.get(
    "TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"
)
_FILL, _LINE = "#1f4e79", "#0a2540"


def build_summary(target: str, indication: str = None, release_pin: str = "26q1", plot_data_out=None) -> dict:
    """Q5 summary. indication accepted for the CARD_DISPATCHERS contract but NOT consumed
    (RNA↔protein concordance is a per-ModelID target property, indication-independent).
    plot_data_out (figure offline seam): forwarded so plot_data_rna_protein.parquet persists."""
    summary = _read.read_rna_protein_concordance(target, release_pin=release_pin, plot_data_out=plot_data_out)
    summary["method_version"] = METHOD_VERSION
    return summary


def build_tumor_summary(target: str, indication: str, plot_data_out=None) -> dict:
    """Q5 TUMOR arm — CPTAC matched tumor RNA↔protein concordance for target in the indication's
    CPTAC cohort. Indication-scoped (cohort-specific). Distinct from the cell-line arm.
    plot_data_out (figure offline seam): forwarded so plot_data_rna_protein_tumor.parquet persists."""
    summary = _read.read_tumor_rna_protein_concordance(target, indication, plot_data_out=plot_data_out)
    summary["method_version"] = METHOD_VERSION
    return summary


def _load_style(contracts_dir):
    try:
        import matplotlib.pyplot as plt

        style = Path(contracts_dir) / "plot_styles" / "takeda_oncology.mplstyle"
        if style.exists():
            plt.style.use(str(style))
    except Exception:  # noqa: BLE001
        pass


def _pal(contracts_dir):
    """Load the mplstyle + return the takeda_palette module (figure_frame / colors). None if absent."""
    _load_style(contracts_dir)
    try:
        import sys as _sys

        p = str(Path(contracts_dir) / "plot_styles")
        if p not in _sys.path:
            _sys.path.insert(0, p)
        import takeda_palette  # type: ignore

        return takeda_palette
    except Exception:  # noqa: BLE001
        return None


def _proxy_takeaway(target, r, cls):
    """rna_as_biomarker class → one-line finding (r rounded)."""
    rr = f"{float(r):.2f}" if r is not None else "n/a"
    return {
        "adequate_proxy": f"RNA is an adequate proxy for {target} protein (r={rr}).",
        "partial_proxy": f"RNA is only a partial proxy for {target} protein (r={rr}).",
        "poor_proxy": f"RNA is a poor proxy for {target} protein (r={rr}).",
        "discordant": f"RNA and {target} protein are discordant (r={rr}).",
    }.get(cls)


def emit_svg(
    target: str, indication, summary: dict, out_dir: Path, contracts_dir=DEFAULT_TARGET_CONTRACTS, *, presampled=None
):
    """Tier-3 SVG: per-model RNA (x) vs protein (y) scatter with the fitted trend + r annotation.
    None if data_unavailable / underpowered.

    presampled (figure Stage 6): OPT-IN per-model points list ([{rna, protein}]) → draw OFFLINE with
    no live re-read. None = read live (legacy)."""
    import matplotlib

    matplotlib.use("Agg")
    import numpy as np

    pal = _pal(contracts_dir)
    out_path = Path(out_dir) / "figure_rna_protein_concordance.svg"
    if presampled is not None:
        pts = presampled
    else:
        scatter = _read.read_rna_protein_scatter(target)
        pts = scatter.get("points") or []
        if not scatter.get("available"):
            return None
    if len(pts) < _read.MIN_PAIRED_MODELS or pal is None:
        return _emit_scatter_fallback(out_path, pts, target) if pal is None else None
    x = np.array([p["rna"] for p in pts])
    y = np.array([p["protein"] for p in pts])
    r = summary.get("rna_protein_r")
    cls = summary.get("rna_as_biomarker", "")
    with pal.figure_frame(
        target,
        None,
        "cell-line RNA vs. protein",
        out_path=out_path,
        kind="scatter",
        provenance=f"DepMap 26Q1 RNA  ·  Gygi TMT MS protein  ·  n={summary.get('n_paired_models')} paired cell lines",
        takeaway=_proxy_takeaway(target, r, cls),
    ) as F:
        ax = F.ax
        ax.scatter(x, y, s=16, color=pal.TUMOR_FILL, edgecolor=pal.TUMOR_LINE, linewidth=0.4, alpha=0.5, zorder=3)
        if len(pts) >= 2 and np.ptp(x) > 0:
            m, b = np.polyfit(x, y, 1)
            xs = np.array([x.min(), x.max()])
            ax.plot(xs, m * xs + b, color="#33383D", linewidth=1.6, zorder=4)
        if r is not None:
            ax.text(
                0.98,
                0.03,
                f"Pearson r = {r}",
                transform=ax.transAxes,
                fontsize=8,
                color="#33383D",
                va="bottom",
                ha="right",
            )  # bottom-RIGHT (empty corner; clears the points)
        ax.grid(alpha=0.25, linewidth=0.4)
        F.axis_label("x", "RNA Expression", "log2(TPM + 1), DepMap")
        F.axis_label("y", "Protein Expression", "log2 abundance, Gygi MS")
    return out_path


def _emit_scatter_fallback(out_path, pts, target):
    """Minimal honest fallback when the palette/frame is unavailable."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(5.6, 4.8))
    ax.scatter([p["rna"] for p in pts], [p["protein"] for p in pts], s=14, alpha=0.55)
    ax.set_xlabel("RNA")
    ax.set_ylabel("Protein")
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def emit_plotly_specs(
    target: str, indication, out_dir: Path, contracts_dir=DEFAULT_TARGET_CONTRACTS, *, presampled=None, summary=None
):
    """Interactive twin — same per-model points (hover = ModelID). Best-effort.
    presampled (Stage 6): OPT-IN points + summary → no live re-read."""
    try:
        import plotly.graph_objects as go
    except Exception:  # noqa: BLE001
        return []
    if presampled is not None:
        pts = presampled
    else:
        scatter = _read.read_rna_protein_scatter(target)
        pts = scatter.get("points") or []
        if not scatter.get("available"):
            return []
    if len(pts) < _read.MIN_PAIRED_MODELS:
        return []
    if summary is None:
        summary = _read.read_rna_protein_concordance(target)
    fig = go.Figure(
        go.Scatter(
            x=[p["rna"] for p in pts],
            y=[p["protein"] for p in pts],
            mode="markers",
            marker=dict(color=_FILL, size=6, opacity=0.6),
            text=[p["model_id"] for p in pts],
        )
    )
    fig.update_layout(
        title=f"{target} — cell-line RNA↔protein concordance "
        f"(r={summary.get('rna_protein_r')}, {summary.get('rna_as_biomarker')})",
        xaxis_title=f"{target} RNA log2(TPM+1)",
        yaxis_title=f"{target} protein log2-abundance",
        template="plotly_white",
        margin=dict(l=60, r=40, t=50, b=50),
    )
    (Path(out_dir) / "figure_rna_protein_concordance.plotly.json").write_text(fig.to_json())
    return [
        {
            "id": "rna_protein_concordance_scatter",
            "path": "figure_rna_protein_concordance.plotly.json",
            "type": "plotly",
        }
    ]


def emit_tumor_svg(
    target: str, indication, out_dir: Path, contracts_dir=DEFAULT_TARGET_CONTRACTS, *, presampled=None, summary=None
):
    """Tier-3 SVG for the TUMOR arm: per-tumor RNA (x) vs protein (y) scatter + fitted trend + r.
    None if data_unavailable / underpowered / no CPTAC cohort.

    presampled (figure Stage 6): OPT-IN per-tumor points ([{rna, protein}]) + summary → OFFLINE."""
    import matplotlib

    matplotlib.use("Agg")
    import numpy as np

    pal = _pal(contracts_dir)
    out_path = Path(out_dir) / "figure_rna_protein_concordance_tumor.svg"
    if presampled is not None:
        pts = presampled
    else:
        scatter = _read.read_tumor_rna_protein_scatter(target, indication)
        pts = scatter.get("points") or []
        if not scatter.get("available"):
            return None
    if len(pts) < _read.MIN_PAIRED_TUMORS or pal is None:
        return _emit_scatter_fallback(out_path, pts, target) if pal is None else None
    x = np.array([p["rna"] for p in pts])
    y = np.array([p["protein"] for p in pts])
    if summary is None:
        summary = _read.read_tumor_rna_protein_concordance(target, indication)
    r = summary.get("rna_protein_r")
    cls = summary.get("rna_as_biomarker", "")
    with pal.figure_frame(
        target,
        indication,
        "tumor RNA vs. protein",
        out_path=out_path,
        kind="scatter",
        provenance=f"CPTAC {summary.get('cptac_cohort', '')} tumor (RNA + TMT MS)  ·  "
        f"n={summary.get('n_paired_tumors')} paired tumors",
        takeaway=_proxy_takeaway(target, r, cls),
    ) as F:
        ax = F.ax
        ax.scatter(x, y, s=18, color=pal.TUMOR_FILL, edgecolor=pal.TUMOR_LINE, linewidth=0.4, alpha=0.5, zorder=3)
        if len(pts) >= 2 and np.ptp(x) > 0:
            m, b = np.polyfit(x, y, 1)
            xs = np.array([x.min(), x.max()])
            ax.plot(xs, m * xs + b, color="#33383D", linewidth=1.6, zorder=4)
        if r is not None:
            ax.text(
                0.98,
                0.03,
                f"Pearson r = {r}",
                transform=ax.transAxes,
                fontsize=8,
                color="#33383D",
                va="bottom",
                ha="right",
            )  # bottom-RIGHT (empty corner; clears the points)
        ax.grid(alpha=0.25, linewidth=0.4)
        F.axis_label("x", "RNA Expression", "log2(TPM + 1), CPTAC")
        F.axis_label("y", "Protein Expression", "log2 abundance, CPTAC")
    return out_path


def emit_tumor_plotly_specs(
    target: str, indication, out_dir: Path, contracts_dir=DEFAULT_TARGET_CONTRACTS, *, presampled=None, summary=None
):
    """Interactive twin of the tumor scatter (hover = Patient_ID). Best-effort.
    presampled (Stage 6): OPT-IN points + summary → no live re-read."""
    try:
        import plotly.graph_objects as go
    except Exception:  # noqa: BLE001
        return []
    if presampled is not None:
        pts = presampled
    else:
        scatter = _read.read_tumor_rna_protein_scatter(target, indication)
        pts = scatter.get("points") or []
        if not scatter.get("available"):
            return []
    if len(pts) < _read.MIN_PAIRED_TUMORS:
        return []
    if summary is None:
        summary = _read.read_tumor_rna_protein_concordance(target, indication)
    fig = go.Figure(
        go.Scatter(
            x=[p["rna"] for p in pts],
            y=[p["protein"] for p in pts],
            mode="markers",
            marker=dict(color="#7b4a8f", size=7, opacity=0.65),
            text=[p["patient_id"] for p in pts],
        )
    )
    fig.update_layout(
        title=f"{target} in {indication} — TUMOR RNA↔protein concordance "
        f"(r={summary.get('rna_protein_r')}, {summary.get('rna_as_biomarker')})",
        xaxis_title=f"{target} RNA log2(TPM+1)",
        yaxis_title=f"{target} protein log2-abundance",
        template="plotly_white",
        margin=dict(l=60, r=40, t=50, b=50),
    )
    (Path(out_dir) / "figure_rna_protein_concordance_tumor.plotly.json").write_text(fig.to_json())
    return [
        {
            "id": "rna_protein_concordance_tumor_scatter",
            "path": "figure_rna_protein_concordance_tumor.plotly.json",
            "type": "plotly",
        }
    ]


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", default=None)
    ap.add_argument("--release-pin", default="26q1")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--target-contracts", default=DEFAULT_TARGET_CONTRACTS)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    summary = build_summary(args.target, args.indication, release_pin=args.release_pin)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    emit_svg(args.target, args.indication, summary, args.out, args.target_contracts)
    specs = emit_plotly_specs(args.target, args.indication, args.out, args.target_contracts)
    (args.out / "manifest.json").write_text(
        json.dumps(
            {
                "method": "depmap_rna_protein_concordance",
                "method_version": METHOD_VERSION,
                "target": args.target,
                "rna_as_biomarker": summary.get("rna_as_biomarker"),
                "artifacts": {"summary": "summary.json", "svg": "figure_rna_protein_concordance.svg"},
                "plotly_figures": specs or [],
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
