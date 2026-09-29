"""CLI + emitter for alteration_clinical_association (Q11-alteration — OS by target mutation status)."""

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
    "alteration_mutated_worse_survival": ("#a63d2e", "#7a2c20"),  # poor-prognosis alteration
    "alteration_mutated_better_survival": ("#c07a20", "#8f5810"),  # caution — marks indolent disease
    "no_survival_association": ("#4a7c9e", "#2f5670"),
    "insufficient_survival_data": ("#bbbbbb", "#8f8f8f"),
    "data_unavailable": ("#d9dbdd", "#a9adb1"),
}


def build_summary(target: str, indication: str) -> dict:
    summary = _read.read_alteration_clinical_association(target, indication)
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
    """Tier-3 SVG: alteration-survival association card (class + log-rank stats). None if no test."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _load_style(contracts_dir)
    cls = summary.get("alteration_survival_association_class")
    if cls in (None, "data_unavailable", "insufficient_survival_data") or summary.get("logrank_p") is None:
        return None
    out_path = Path(out_dir) / "figure_alteration_clinical_association.svg"
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
        f"{target} in {indication} — OS by mutation status",
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
        fontsize=10.5,
        weight="bold",
        color=line,
        transform=ax.transAxes,
    )
    lines = [
        f"log-rank p = {summary.get('logrank_p', 'n/a')}  (chi2={summary.get('logrank_chi2', 'n/a')})",
        f"mutated n={summary.get('n_mutated', 'n/a')}  WT n={summary.get('n_wildtype', 'n/a')}  events={summary.get('n_events', 'n/a')}",
        f"median OS days — mutated: {summary.get('median_ostime_mutated_days', 'n/a')}  WT: {summary.get('median_ostime_wildtype_days', 'n/a')}",
        "univariate mutation-status split, unadjusted (exploratory)",
    ]
    for i, t in enumerate(lines):
        ax.text(0.06, 0.46 - i * 0.11, t, ha="left", va="center", fontsize=8.5, transform=ax.transAxes)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(
        description="alteration_clinical_association (Q11-alteration) — OS by target mutation status"
    )
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
