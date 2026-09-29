"""CLI + emitter for subtype_survival_association (Q2-subtype — OS across molecular subtypes)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from methods.roots import contracts_root

from . import read as _read

METHOD_VERSION = "0.1.0"
# Portable sibling default; `or` so an empty env value falls back too (Path("") is the CWD).
DEFAULT_TARGET_CONTRACTS = os.environ.get("TARGET_CONTRACTS_ROOT") or str(contracts_root())

_CLASS_COLORS = {
    "subtype_stratifies_survival": ("#7a4fa3", "#573876"),  # subtype is prognostic
    "no_subtype_survival_association": ("#4a7c9e", "#2f5670"),
    "insufficient_survival_data": ("#bbbbbb", "#8f8f8f"),
    "data_unavailable": ("#d9dbdd", "#a9adb1"),
}


def build_summary(indication: str, subgroup_assignments_manifest: str) -> dict:
    summary = _read.read_subtype_survival_association(indication, subgroup_assignments_manifest)
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


def emit_svg(indication: str, summary: dict, out_dir: Path, contracts_dir=DEFAULT_TARGET_CONTRACTS):
    """Tier-3 SVG: subtype-survival association card (class + omnibus log-rank). None if no test."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _load_style(contracts_dir)
    cls = summary.get("subtype_survival_association_class")
    if cls in (None, "data_unavailable", "insufficient_survival_data") or summary.get("logrank_p") is None:
        return None
    out_path = Path(out_dir) / "figure_subtype_survival_association.svg"
    fill, line = _CLASS_COLORS.get(cls, _CLASS_COLORS["data_unavailable"])
    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    ax.set_axis_off()
    ax.add_patch(
        plt.Rectangle(
            (0.02, 0.62), 0.96, 0.34, facecolor=fill, edgecolor=line, alpha=0.5, linewidth=1.2, transform=ax.transAxes
        )
    )
    ax.text(
        0.5,
        0.82,
        f"{indication} — OS across molecular subtypes",
        ha="center",
        va="center",
        fontsize=10.5,
        weight="bold",
        transform=ax.transAxes,
    )
    ax.text(
        0.5,
        0.70,
        cls.replace("_", " ").upper(),
        ha="center",
        va="center",
        fontsize=10.5,
        weight="bold",
        color=line,
        transform=ax.transAxes,
    )
    lines = [
        f"driving axis '{summary.get('driving_axis', 'n/a')}' log-rank p = {summary.get('logrank_p', 'n/a')}  "
        f"(chi2={summary.get('logrank_chi2', 'n/a')}, df={summary.get('logrank_df', 'n/a')})"
    ]
    for a in summary.get("per_axis_association", [])[:5]:
        lines.append(
            f"  [{a['axis']}] {'+'.join(a['strata'])}: p={a['logrank_p']} (n={a['n_patients']}, events={a['n_events']})"
        )
    lines.append("per-axis univariate omnibus over disjoint arms, unadjusted (exploratory)")
    for i, t in enumerate(lines):
        ax.text(0.06, 0.54 - i * 0.09, t, ha="left", va="center", fontsize=8.0, transform=ax.transAxes)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description="subtype_survival_association (Q2-subtype) — OS across molecular subtypes")
    ap.add_argument("--indication", required=True)
    ap.add_argument("--subgroup-assignments-manifest", required=True)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    summary = build_summary(args.indication, args.subgroup_assignments_manifest)
    text = json.dumps(summary, indent=2, default=str)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
        print(f"wrote {args.out}")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
