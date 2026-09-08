"""CLI + emitter for expression_purity_confound (Q9 — purity confound flag)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import read as _read

METHOD_VERSION = "0.1.0"
DEFAULT_TARGET_CONTRACTS = os.environ.get(
    "TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"
)

# purity_confound_class -> (title phrase, fallback signal for the badge).
_CLASS_PHRASE = {
    "tumor_intrinsic": ("expression tracks tumor content (tumor-intrinsic)", "supportive"),
    "purity_independent": ("expression is independent of tumor purity", "supportive"),
    "microenvironment_confounded": ("expression rises in low-purity tumors (microenvironment confound)", "opposing"),
    "insufficient_paired_samples": ("too few paired tumors to test a purity confound", "insufficient"),
    "data_unavailable": ("purity confound — data unavailable", "insufficient"),
}


def build_summary(target: str, indication: str) -> dict:
    summary = _read.read_expression_purity_confound(target, indication)
    summary["method_version"] = METHOD_VERSION
    return summary


def _pal(contracts_dir):
    """Load the mplstyle + return the takeda_palette module (badge/takeaway/colors). None if absent."""
    try:
        import sys as _sys

        import matplotlib.pyplot as plt

        style = Path(contracts_dir) / "plot_styles" / "takeda_oncology.mplstyle"
        if style.exists():
            plt.style.use(str(style))
        p = str(Path(contracts_dir) / "plot_styles")
        if p not in _sys.path:
            _sys.path.insert(0, p)
        import takeda_palette  # type: ignore

        return takeda_palette
    except Exception:  # noqa: BLE001
        return None


def emit_svg(
    target: str,
    indication: str,
    summary: dict,
    out_dir: Path,
    contracts_dir=DEFAULT_TARGET_CONTRACTS,
    *,
    presampled=None,
    status=None,
):
    """Tier-3 SVG: expression↔purity SCATTER (per paired tumor) with fitted trend, Pearson r/p,
    median-purity marker, reserved verdict BADGE + one-line takeaway. Replaces the old text-card.
    None if no correlation was computed.

    presampled: OPT-IN (expr_values, purity_values) parallel arrays → draw the real scatter OFFLINE.
                When None the summary carries only the aggregate stats, so the scatter cannot be drawn
                and we return None (the card still renders its text; a figure needs the points).
    status: OPT-IN status dict (from takeda_palette.status_for_card); falls back to the class signal."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    cls = summary.get("purity_confound_class")
    r = summary.get("expression_purity_pearson_r")
    if cls in (None, "data_unavailable", "insufficient_paired_samples") or r is None:
        return None
    if presampled is None:
        presampled = _read.read_purity_points(target, indication)  # refetch points (no offline seam yet)
    if presampled is None:
        return None  # no per-sample points → cannot honestly draw a scatter
    expr, purity = (list(presampled[0]), list(presampled[1]))
    if len(expr) < 2 or len(expr) != len(purity):
        return None

    pal = _pal(contracts_dir)
    out_path = Path(out_dir) / "figure_expression_purity_confound.svg"
    e = np.asarray(expr, dtype=float)
    p = np.asarray(purity, dtype=float)

    if pal is None:  # palette/frame unavailable → minimal honest fallback
        fig, ax = plt.subplots(figsize=(7.0, 3.5))
        ax.scatter(p, e, s=16, alpha=0.45)
        ax.set_xlabel("Tumor purity")
        ax.set_ylabel("Expression")
        fig.savefig(out_path)
        plt.close(fig)
        return out_path

    med = summary.get("median_purity")
    pear_p = summary.get("expression_purity_pearson_p")
    rr = f"{float(r):.2f}"
    take = {
        "purity_independent": f"{target} expression is independent of tumor purity (r={rr}) — not a stromal/immune artifact.",
        "tumor_intrinsic": f"{target} expression rises with tumor content (r={rr}) — a cancer-cell-intrinsic signal.",
        "microenvironment_confounded": f"{target} expression is higher in low-purity tumors (r={rr}) — may arise from stroma/immune.",
    }.get(cls)

    with pal.figure_frame(
        target,
        indication,
        "expression vs. tumor purity",
        out_path=out_path,
        kind="scatter",
        provenance=f"tumor RNA recount3  ·  purity PanCanAtlas ABSOLUTE  ·  "
        f"n={summary.get('n_paired_samples', len(e))} paired tumors",
        takeaway=take,
    ) as F:
        ax = F.ax
        ax.scatter(p, e, s=16, color=pal.TUMOR_FILL, alpha=0.45, edgecolor=pal.TUMOR_LINE, linewidth=0.3, zorder=3)
        if np.ptp(p) > 0:
            b, a = np.polyfit(p, e, 1)
            xs = np.array([p.min(), p.max()])
            ax.plot(xs, a + b * xs, color="#33383D", linewidth=1.6, zorder=4)
        if med is not None:
            ax.axvline(float(med), zorder=1, **pal.REFLINE_NEUTRAL)
            ax.annotate(
                f"median purity {med:.2f}",
                xy=(float(med), 1.0),
                xycoords=("data", "axes fraction"),
                fontsize=7,
                color="#666666",
                ha="left",
                va="top",
                xytext=(3, -3),
                textcoords="offset points",
            )
        ax.text(
            0.02,
            0.03,
            f"Pearson r = {r}"
            + (f"  (p = {pear_p})" if pear_p is not None else "")
            + f"\nSpearman r = {summary.get('expression_purity_spearman_r', 'n/a')}",
            transform=ax.transAxes,
            fontsize=8,
            color="#33383D",
            va="bottom",
            ha="left",
        )
        ax.grid(alpha=0.25, linewidth=0.4)
        F.axis_label("x", "Tumor purity", "ABSOLUTE — fraction tumor cells")
        F.axis_label("y", "Expression", "log2(TPM + 1)")
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
