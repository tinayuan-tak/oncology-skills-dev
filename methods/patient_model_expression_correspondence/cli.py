"""CLI + emitters for Q4 recommended_models (patient↔model expression correspondence)."""
from __future__ import annotations
import os

import json
from pathlib import Path
from typing import Optional

from . import read as _read

METHOD_VERSION = "0.1.0"
DEFAULT_TARGET_CONTRACTS = os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")

# screen-role → (fill, line) for the scatter.
_ROLE_COLORS = {
    "positive_model":   ("#c0603a", "#8f3f22"),   # expressed + dependent — the on-target model
    "resistance_model": ("#7b5ea7", "#553f7a"),   # expressed + not-dependent
    "negative_control": ("#b8bcc0", "#7d8288"),   # not expressed
    "indeterminate":    ("#d9dbdd", "#a9adb1"),
}


def build_summary(target: str, indication: str, release_pin: str = "26q1",
                  plot_data_out=None) -> dict:
    """Q4 summary — the recommended_models table + rollup scalars. plot_data_out (figure offline seam):
    forwarded to the read fn so plot_data_recommended_models.parquet persists during resolution."""
    summary = _read.read_recommended_models(target, indication, release_pin=release_pin,
                                            plot_data_out=plot_data_out)
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


def emit_svg(target: str, indication: str, summary: dict, out_dir: Path,
             contracts_dir=DEFAULT_TARGET_CONTRACTS, *, presampled=None) -> Optional[Path]:
    """Tier-3 SVG: target TPM (x) vs Chronos (y) scatter over DepMap models, colored by screen role,
    lineage-matched models emphasized, the patient tumor IQR band shaded. None if data_unavailable.

    presampled (figure Stage 6): OPT-IN full models list from persisted plot_data → draw OFFLINE with
    no live re-read. None = read live (legacy)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    _load_style(contracts_dir)
    out_path = Path(out_dir) / "figure_recommended_models.svg"
    if summary.get("correspondence_class") == "data_unavailable":
        return None
    if presampled is not None:
        models = presampled
    else:
        # the scatter wants ALL models (not just the top-N table); re-read with a high cap.
        full = _read.read_recommended_models(target, indication, top_n=100000)
        models = full.get("recommended_models") or []
    if not models:
        return None
    fig, ax = plt.subplots(figsize=(7.0, 4.6))
    for r in models:
        if r.get("chronos") is None:
            continue
        fill, line = _ROLE_COLORS.get(r["screen_role"], _ROLE_COLORS["indeterminate"])
        ax.scatter(r["target_log2tpm"], r["chronos"], s=(46 if r["lineage_match"] else 18),
                   facecolor=fill, edgecolor=line,
                   linewidth=(1.2 if r["lineage_match"] else 0.5),
                   alpha=(0.9 if r["lineage_match"] else 0.5), zorder=3)
    iqr = summary.get("patient_iqr")
    if iqr:
        ax.axvspan(iqr[0], iqr[1], color="#1f4e79", alpha=0.10, zorder=0)
        ax.text(sum(iqr) / 2, ax.get_ylim()[1], "patient tumor IQR", ha="center", va="top",
                fontsize=7, color="#1f4e79")
    ax.axhline(_read.DEPENDENT_CHRONOS, color="#cf2828", linewidth=0.9, linestyle="--", zorder=1)
    ax.set_xlabel("model target log2(TPM+1) — DepMap")
    ax.set_ylabel("target Chronos (dependency; lower = more dependent)")
    ax.set_title(f"{target} in {indication} — patient↔model correspondence "
                 f"({summary.get('correspondence_class','')})")
    ax.grid(alpha=0.25, linewidth=0.4)
    fig.tight_layout(); fig.savefig(out_path); plt.close(fig)
    return out_path


def emit_plotly_specs(target: str, indication: str, out_dir: Path,
                      contracts_dir=DEFAULT_TARGET_CONTRACTS, *, summary=None) -> list:
    """Interactive twin — same model points (hover = cell line + role). Best-effort.
    summary (Stage 6): OPT-IN pass the resolved summary to avoid a build_summary re-read (offline)."""
    try:
        import plotly.graph_objects as go
    except Exception:  # noqa: BLE001
        return []
    if summary is None:
        summary = build_summary(target, indication)
    models = [r for r in (summary.get("recommended_models") or []) if r.get("chronos") is not None]
    if summary.get("correspondence_class") == "data_unavailable" or not models:
        return []
    fig = go.Figure()
    for role in ("positive_model", "resistance_model", "negative_control", "indeterminate"):
        pts = [r for r in models if r["screen_role"] == role]
        if not pts:
            continue
        fill, _line = _ROLE_COLORS[role]
        fig.add_trace(go.Scatter(
            x=[r["target_log2tpm"] for r in pts], y=[r["chronos"] for r in pts], mode="markers",
            name=role, marker=dict(color=fill, size=[12 if r["lineage_match"] else 7 for r in pts]),
            text=[f"{r['cell_line']} ({r['lineage']})" for r in pts]))
    iqr = summary.get("patient_iqr")
    if iqr:
        fig.add_vrect(x0=iqr[0], x1=iqr[1], fillcolor="#1f4e79", opacity=0.10, line_width=0)
    fig.add_hline(y=_read.DEPENDENT_CHRONOS, line_dash="dash", line_color="#cf2828")
    fig.update_layout(title=f"{target} in {indication} — patient↔model correspondence",
                      xaxis_title="model target log2(TPM+1)", yaxis_title="target Chronos",
                      template="plotly_white", margin=dict(l=60, r=40, t=50, b=50))
    (Path(out_dir) / "figure_recommended_models.plotly.json").write_text(fig.to_json())
    return [{"id": "recommended_models_scatter",
             "path": "figure_recommended_models.plotly.json", "type": "plotly"}]


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--release-pin", default="26q1")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--target-contracts", default=DEFAULT_TARGET_CONTRACTS)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    summary = build_summary(args.target, args.indication, release_pin=args.release_pin)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    emit_svg(args.target, args.indication, summary, args.out, args.target_contracts)
    specs = emit_plotly_specs(args.target, args.indication, args.out, args.target_contracts)
    manifest = {"method": "patient_model_expression_correspondence", "method_version": METHOD_VERSION,
                "target": args.target, "indication": args.indication,
                "correspondence_class": summary.get("correspondence_class"),
                "artifacts": {"summary": "summary.json", "svg": "figure_recommended_models.svg"},
                "plotly_figures": specs or []}
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
