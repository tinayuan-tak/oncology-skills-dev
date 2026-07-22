"""CLI + emitter for expression_purity_confound (Q9 — purity confound flag)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import read as _read

METHOD_VERSION = "0.1.0"
DEFAULT_TARGET_CONTRACTS = "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"

_CLASS_COLORS = {
    "tumor_intrinsic":             ("#0a2540", "#061829"),   # reassuring — cancer-cell signal
    "purity_independent":          ("#4a7c9e", "#2f5670"),
    "microenvironment_confounded": ("#a63d2e", "#7a2c20"),   # caution — stromal/immune signal
    "insufficient_paired_samples": ("#bbbbbb", "#8f8f8f"),
    "data_unavailable":            ("#d9dbdd", "#a9adb1"),
}


def build_summary(target: str, indication: str) -> dict:
    summary = _read.read_expression_purity_confound(target, indication)
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
    """Tier-3 SVG: purity-confound evidence card (class + expression↔purity correlation). None if
    no correlation computed."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    _load_style(contracts_dir)
    cls = summary.get("purity_confound_class")
    r = summary.get("expression_purity_pearson_r")
    if cls in (None, "data_unavailable", "insufficient_paired_samples") or r is None:
        return None
    out_path = Path(out_dir) / "figure_expression_purity_confound.svg"
    fill, line = _CLASS_COLORS.get(cls, _CLASS_COLORS["data_unavailable"])
    fig, ax = plt.subplots(figsize=(6.4, 3.0)); ax.set_axis_off()
    ax.add_patch(plt.Rectangle((0.02, 0.58), 0.96, 0.38, facecolor=fill, edgecolor=line,
                               alpha=0.5, linewidth=1.2, transform=ax.transAxes))
    ax.text(0.5, 0.80, f"{target} in {indication} — purity confound", ha="center", va="center",
            fontsize=10.5, weight="bold", transform=ax.transAxes)
    ax.text(0.5, 0.66, cls.replace("_", " ").upper(), ha="center", va="center",
            fontsize=11, weight="bold", color=line, transform=ax.transAxes)
    lines = [
        f"expression vs tumor purity: Pearson r = {r}",
        f"Spearman r: {summary.get('expression_purity_spearman_r', 'n/a')}  (p={summary.get('expression_purity_pearson_p','n/a')})",
        f"paired tumors: {summary.get('n_paired_samples', 'n/a')}  |  median purity: {summary.get('median_purity','n/a')}",
        "cellular source unresolved from bulk (flag, not proof)",
    ]
    for i, t in enumerate(lines):
        ax.text(0.06, 0.46 - i * 0.11, t, ha="left", va="center", fontsize=8.5, transform=ax.transAxes)
    fig.savefig(out_path, bbox_inches="tight"); plt.close(fig)
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description="expression_purity_confound (Q9) — purity confound flag")
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
