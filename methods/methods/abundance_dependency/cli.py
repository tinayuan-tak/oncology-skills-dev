"""CLI + emitter for abundance_dependency (Q7 — protein abundance → dependency)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import read as _read

METHOD_VERSION = "0.1.0"
# Portable sibling default; `or` so an empty env value falls back too (Path("") is the CWD).
DEFAULT_TARGET_CONTRACTS = os.environ.get("TARGET_CONTRACTS_ROOT") or str(
    Path(__file__).resolve().parents[2].parent / "rnd-computational-biology-oncology-target-contracts"
)

_CLASS_COLORS = {
    "protein_predicts_dependency": ("#0a2540", "#061829"),
    "weak_protein_dependency_link": ("#4a7c9e", "#2f5670"),
    "no_protein_dependency_link": ("#c07a20", "#8f5810"),
    "insufficient_paired_models": ("#bbbbbb", "#8f8f8f"),
    "data_unavailable": ("#d9dbdd", "#a9adb1"),
}


def build_summary(target: str, indication: str) -> dict:
    summary = _read.read_abundance_dependency(target, indication)
    summary["method_version"] = METHOD_VERSION
    return summary


def _load_style(contracts_dir):
    import matplotlib.pyplot as plt

    style = Path(contracts_dir) / "figure-style" / "matplotlibrc"
    if style.exists():
        try:
            plt.style.use(str(style))
        except Exception:  # noqa: BLE001
            pass


def emit_svg(target: str, indication: str, summary: dict, out_dir: Path, contracts_dir=DEFAULT_TARGET_CONTRACTS):
    """Tier-3 SVG: protein-abundance→dependency evidence card (class + correlation stats). None if
    no correlation was computed."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _load_style(contracts_dir)
    cls = summary.get("abundance_dependency_class")
    r = summary.get("protein_dependency_pearson_r")
    if cls in (None, "data_unavailable", "insufficient_paired_models") or r is None:
        return None
    out_path = Path(out_dir) / "figure_abundance_dependency.svg"
    fill, line = _CLASS_COLORS.get(cls, _CLASS_COLORS["data_unavailable"])
    fig, ax = plt.subplots(figsize=(6.4, 3.0))
    ax.set_axis_off()
    ax.add_patch(
        plt.Rectangle(
            (0.02, 0.58), 0.96, 0.38, facecolor=fill, edgecolor=line, alpha=0.5, linewidth=1.2, transform=ax.transAxes
        )
    )
    ax.text(
        0.5,
        0.80,
        f"{target} — protein abundance → dependency",
        ha="center",
        va="center",
        fontsize=10.5,
        weight="bold",
        transform=ax.transAxes,
    )
    ax.text(
        0.5,
        0.66,
        cls.replace("_", " ").upper(),
        ha="center",
        va="center",
        fontsize=11,
        weight="bold",
        color=line,
        transform=ax.transAxes,
    )
    lines = [
        f"Pearson r (protein vs Chronos): {r}",
        f"Spearman r: {summary.get('protein_dependency_spearman_r', 'n/a')}",
        f"paired models: {summary.get('n_paired_models', 'n/a')}  |  dependent: {summary.get('n_dependent_models', 'n/a')}",
        f"protein detected in: {summary.get('n_protein_detected_models', 'n/a')}/{summary.get('protein_panel_size', 'n/a')} lines",
    ]
    for i, t in enumerate(lines):
        ax.text(0.06, 0.46 - i * 0.11, t, ha="left", va="center", fontsize=8.5, transform=ax.transAxes)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description="abundance_dependency (Q7) — protein abundance vs dependency")
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", default="")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    summary = build_summary(args.target, args.indication)
    text = json.dumps(summary, indent=2, default=str)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
        print(f"wrote {args.out}")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
