"""CLI + emitters for Q5 RNA↔protein concordance (cell-line)."""
from __future__ import annotations

import json
from pathlib import Path

from . import read as _read

METHOD_VERSION = "0.1.0"
DEFAULT_TARGET_CONTRACTS = "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"
_FILL, _LINE = "#1f4e79", "#0a2540"


def build_summary(target: str, indication: str = None, release_pin: str = "26q1") -> dict:
    """Q5 summary. indication accepted for the CARD_DISPATCHERS contract but NOT consumed
    (RNA↔protein concordance is a per-ModelID target property, indication-independent)."""
    summary = _read.read_rna_protein_concordance(target, release_pin=release_pin)
    summary["method_version"] = METHOD_VERSION
    return summary


def build_tumor_summary(target: str, indication: str) -> dict:
    """Q5 TUMOR arm — CPTAC matched tumor RNA↔protein concordance for target in the indication's
    CPTAC cohort. Indication-scoped (cohort-specific). Distinct from the cell-line arm."""
    summary = _read.read_tumor_rna_protein_concordance(target, indication)
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


def emit_svg(target: str, indication, summary: dict, out_dir: Path,
             contracts_dir=DEFAULT_TARGET_CONTRACTS):
    """Tier-3 SVG: per-model RNA (x) vs protein (y) scatter with the fitted trend + r annotation.
    None if data_unavailable / underpowered."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    _load_style(contracts_dir)
    out_path = Path(out_dir) / "figure_rna_protein_concordance.svg"
    scatter = _read.read_rna_protein_scatter(target)
    pts = scatter.get("points") or []
    if not scatter.get("available") or len(pts) < _read.MIN_PAIRED_MODELS:
        return None
    x = np.array([p["rna"] for p in pts]); y = np.array([p["protein"] for p in pts])
    fig, ax = plt.subplots(figsize=(5.6, 4.8))
    ax.scatter(x, y, s=14, color=_FILL, edgecolor=_LINE, linewidth=0.4, alpha=0.55, zorder=3)
    # least-squares trend
    if len(pts) >= 2 and np.ptp(x) > 0:
        m, b = np.polyfit(x, y, 1)
        xs = np.linspace(float(x.min()), float(x.max()), 50)
        ax.plot(xs, m * xs + b, color="#cf2828", linewidth=1.2, zorder=4)
    r = summary.get("rna_protein_r")
    cls = summary.get("rna_as_biomarker", "")
    ax.set_xlabel(f"{target} RNA — log2(TPM+1), DepMap")
    ax.set_ylabel(f"{target} protein — log2-abundance, Gygi MS")
    ax.set_title(f"{target} — cell-line RNA↔protein concordance\n"
                 f"Pearson r={r} ({cls}); n={summary.get('n_paired_models')}")
    ax.grid(alpha=0.25, linewidth=0.4)
    fig.tight_layout(); fig.savefig(out_path); plt.close(fig)
    return out_path


def emit_plotly_specs(target: str, indication, out_dir: Path, contracts_dir=DEFAULT_TARGET_CONTRACTS):
    """Interactive twin — same per-model points (hover = ModelID). Best-effort."""
    try:
        import plotly.graph_objects as go
    except Exception:  # noqa: BLE001
        return []
    scatter = _read.read_rna_protein_scatter(target)
    pts = scatter.get("points") or []
    if not scatter.get("available") or len(pts) < _read.MIN_PAIRED_MODELS:
        return []
    summary = _read.read_rna_protein_concordance(target)
    fig = go.Figure(go.Scatter(
        x=[p["rna"] for p in pts], y=[p["protein"] for p in pts], mode="markers",
        marker=dict(color=_FILL, size=6, opacity=0.6),
        text=[p["model_id"] for p in pts]))
    fig.update_layout(
        title=f"{target} — cell-line RNA↔protein concordance "
              f"(r={summary.get('rna_protein_r')}, {summary.get('rna_as_biomarker')})",
        xaxis_title=f"{target} RNA log2(TPM+1)", yaxis_title=f"{target} protein log2-abundance",
        template="plotly_white", margin=dict(l=60, r=40, t=50, b=50))
    (Path(out_dir) / "figure_rna_protein_concordance.plotly.json").write_text(fig.to_json())
    return [{"id": "rna_protein_concordance_scatter",
             "path": "figure_rna_protein_concordance.plotly.json", "type": "plotly"}]


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
    (args.out / "manifest.json").write_text(json.dumps(
        {"method": "depmap_rna_protein_concordance", "method_version": METHOD_VERSION,
         "target": args.target, "rna_as_biomarker": summary.get("rna_as_biomarker"),
         "artifacts": {"summary": "summary.json", "svg": "figure_rna_protein_concordance.svg"},
         "plotly_figures": specs or []}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
