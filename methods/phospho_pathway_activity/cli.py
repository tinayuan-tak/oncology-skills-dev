"""CLI + emitter for phospho_pathway_activity (Q8 — CPTAC phospho pathway-activity)."""
from __future__ import annotations
import os

import argparse
import json
import sys
from pathlib import Path

from . import read as _read

METHOD_VERSION = "0.1.0"
DEFAULT_TARGET_CONTRACTS = os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")

_CLASS_COLORS = {
    "phospho_active":     ("#0a2540", "#061829"),   # active signaling
    "phospho_present":    ("#4a7c9e", "#2f5670"),
    "phospho_low":        ("#c07a20", "#8f5810"),
    "not_phosphoprotein": ("#bbbbbb", "#8f8f8f"),   # axis doesn't apply
    "data_unavailable":   ("#d9dbdd", "#a9adb1"),
}


def build_summary(target: str, indication: str) -> dict:
    summary = _read.read_phospho_pathway_activity(target, indication)
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


def emit_svg(target: str, indication: str, summary: dict, out_dir: Path,
             contracts_dir=DEFAULT_TARGET_CONTRACTS):
    """Tier-3 SVG: phospho-activity evidence card (class + top phosphosites by detection). None if
    not a phosphoprotein / data_unavailable."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    _load_style(contracts_dir)
    cls = summary.get("phospho_activity_class")
    if cls in (None, "data_unavailable", "not_phosphoprotein"):
        return None
    out_path = Path(out_dir) / "figure_phospho_pathway_activity.svg"
    fill, line = _CLASS_COLORS.get(cls, _CLASS_COLORS["data_unavailable"])
    fig, ax = plt.subplots(figsize=(6.4, 3.2)); ax.set_axis_off()
    ax.add_patch(plt.Rectangle((0.02, 0.62), 0.96, 0.34, facecolor=fill, edgecolor=line,
                               alpha=0.5, linewidth=1.2, transform=ax.transAxes))
    ax.text(0.5, 0.82, f"{target} in {indication} — phospho pathway activity", ha="center", va="center",
            fontsize=10.5, weight="bold", transform=ax.transAxes)
    ax.text(0.5, 0.69, cls.replace("_", " ").upper(), ha="center", va="center",
            fontsize=11, weight="bold", color=line, transform=ax.transAxes)
    lines = [
        f"phosphosites: {summary.get('n_phosphosites','n/a')}  (frequent: {summary.get('n_phosphosites_frequent','n/a')})",
        f"max site detection: {summary.get('max_site_detection_fraction','n/a')}  |  n tumors: {summary.get('n_tumors','n/a')}",
        f"phospho exceeds abundance: {summary.get('phospho_exceeds_abundance','n/a')}  (dz={summary.get('phospho_minus_protein_z','n/a')})",
    ]
    for i, t in enumerate(lines):
        ax.text(0.06, 0.52 - i * 0.10, t, ha="left", va="center", fontsize=8.5, transform=ax.transAxes)
    top = summary.get("top_phosphosites") or []
    if top:
        ax.text(0.06, 0.20, "top sites: " + ", ".join(
            f"{s.get('site')}({s.get('detection_fraction')})" for s in top[:5]),
            ha="left", va="center", fontsize=7.5, family="monospace", color="#222", transform=ax.transAxes)
    fig.savefig(out_path, bbox_inches="tight"); plt.close(fig)
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description="phospho_pathway_activity (Q8) — CPTAC phospho pathway activity")
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
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
