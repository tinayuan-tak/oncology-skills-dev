"""CLI + emitter for the alteration_role overlay (genomic-alteration plan step 1)."""
from __future__ import annotations
import os

import json
from pathlib import Path

from . import read as _read

METHOD_VERSION = "0.1.0"
DEFAULT_TARGET_CONTRACTS = os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")

_ROLE_COLORS = {
    "direct_driver_gof":    ("#c0603a", "#8f3f22"),   # activating driver — warm
    "direct_driver_lof":    ("#4a7fa5", "#2f5670"),   # loss-of-function — cool
    "predictive_biomarker": ("#7b5ea7", "#553f7a"),   # marker / ambiguous — accent
    "passenger":            ("#b8bcc0", "#7d8288"),   # no driver evidence — neutral
    "data_unavailable":     ("#d9dbdd", "#a9adb1"),
}


def build_summary(target: str, indication: str) -> dict:
    """alteration_role summary for a (target, indication)."""
    summary = _read.read_alteration_role(target, indication)
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
             contracts_dir=DEFAULT_TARGET_CONTRACTS):
    """Tier-3 SVG: a compact driver-role evidence card — the role call + the OncoKB/IntOGen
    evidence it rests on (gene-type, mode-of-action, indication scope, q-value). None if data_unavailable."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    _load_style(contracts_dir)
    out_path = Path(out_dir) / "figure_alteration_role.svg"
    role = summary.get("alteration_role")
    if role in (None, "data_unavailable"):
        return None
    fill, line = _ROLE_COLORS.get(role, _ROLE_COLORS["data_unavailable"])
    fig, ax = plt.subplots(figsize=(6.4, 3.4)); ax.set_axis_off()
    ax.add_patch(plt.Rectangle((0.02, 0.60), 0.96, 0.34, facecolor=fill, edgecolor=line,
                               alpha=0.5, linewidth=1.2, transform=ax.transAxes))
    ax.text(0.5, 0.77, f"{target} in {indication}", ha="center", va="center",
            fontsize=11, weight="bold", transform=ax.transAxes)
    ax.text(0.5, 0.67, role.replace("_", " ").upper() + f"  ({summary.get('functional_direction','?')})",
            ha="center", va="center", fontsize=12, color=line, weight="bold", transform=ax.transAxes)
    lines = [
        f"OncoKB gene-role: {summary.get('oncokb_gene_type', 'n/a')}",
        f"IntOGen mode-of-action: {summary.get('intogen_role', 'n/a')} "
        f"({summary.get('intogen_scope', 'n/a')} scope)",
        f"IntOGen min q-value: {summary.get('intogen_min_qvalue', 'n/a')}",
        f"IntOGen max % samples: {summary.get('intogen_max_pct_samples', 'n/a')}",
        f"sources: {', '.join(summary.get('sources') or []) or 'none'}",
    ]
    for i, t in enumerate(lines):
        ax.text(0.06, 0.48 - i * 0.09, t, ha="left", va="center", fontsize=8.5, transform=ax.transAxes)
    fig.savefig(out_path); plt.close(fig)
    return out_path


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--target-contracts", default=DEFAULT_TARGET_CONTRACTS)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    summary = build_summary(args.target, args.indication)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    emit_svg(args.target, args.indication, summary, args.out, args.target_contracts)
    (args.out / "manifest.json").write_text(json.dumps(
        {"method": "driver_role_overlay", "method_version": METHOD_VERSION,
         "target": args.target, "indication": args.indication,
         "alteration_role": summary.get("alteration_role"),
         "artifacts": {"summary": "summary.json", "svg": "figure_alteration_role.svg"}},
        indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
