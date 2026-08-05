"""CLI + emitter for genomic_event_model_match (M11 — canonical P3 genomic join)."""
from __future__ import annotations
import os

import argparse
import json
import sys
from pathlib import Path

from . import read as _read

METHOD_VERSION = "0.1.0"
DEFAULT_TARGET_CONTRACTS = os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")

# event_correspondence_class → (light, dark) for the card figure.
_CLASS_COLORS = {
    "event_matched_dependent_in_lineage":  ("#0a2540", "#061829"),   # best — matched + dependent + in-lineage
    "event_matched_dependent_off_lineage": ("#4a7c9e", "#2f5670"),   # matched + dependent, off-lineage
    "event_matched_not_dependent":         ("#c07a20", "#8f5810"),   # genotype matched but resistant
    "no_event_match":                      ("#a63d2e", "#7a2c20"),   # no model carries the event
    "no_target_event":                     ("#888888", "#5f5f5f"),   # tumors rarely altered
    "data_unavailable":                    ("#bbbbbb", "#8f8f8f"),
}


def build_summary(target: str, indication: str, release_pin: str = "26q1") -> dict:
    """genomic_event_model_match summary for a (target, indication)."""
    summary = _read.read_genomic_event_model_match(target, indication, release_pin=release_pin)
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
    """Tier-3 SVG: the genotype-matched-models evidence card — the tumor event being matched, the
    correspondence class, and the top matched models (genotype × dependency × lineage). None if
    no matched models / data_unavailable."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    _load_style(contracts_dir)

    cls = summary.get("event_correspondence_class")
    matched = summary.get("matched_models") or []
    if cls in (None, "data_unavailable", "no_target_event") and not matched:
        return None

    out_path = Path(out_dir) / "figure_genomic_event_model_match.svg"
    fill, line = _CLASS_COLORS.get(cls, _CLASS_COLORS["data_unavailable"])
    fig, ax = plt.subplots(figsize=(6.8, 3.8)); ax.set_axis_off()
    ax.add_patch(plt.Rectangle((0.02, 0.80), 0.96, 0.17, facecolor=fill, edgecolor=line,
                               alpha=0.5, linewidth=1.2, transform=ax.transAxes))
    ax.text(0.5, 0.885, f"{target} in {indication} — genomic-event model match",
            ha="center", va="center", fontsize=10.5, weight="bold", transform=ax.transAxes)
    ev = summary.get("patient_event_state"); evf = summary.get("patient_event_fraction")
    ax.text(0.5, 0.83,
            f"tumor event: {ev or 'none'} ({evf*100:.0f}% of tumors)" if evf is not None
            else f"tumor event: {ev or 'none'}",
            ha="center", va="center", fontsize=9, color=line, transform=ax.transAxes)
    ax.text(0.06, 0.71, (cls or "").replace("_", " ").upper(),
            ha="left", va="center", fontsize=11, weight="bold", color=line, transform=ax.transAxes)
    ax.text(0.06, 0.63,
            f"{summary.get('n_event_matched', 0)} genotype-matched models · "
            f"{summary.get('n_matched_dependent', 0)} dependent · "
            f"{summary.get('n_matched_dependent_in_lineage', 0)} in-lineage",
            ha="left", va="center", fontsize=8.5, color="#444", transform=ax.transAxes)
    # top matched models table (up to 6)
    y = 0.52
    ax.text(0.06, y, "top matched models (cell line · lineage · Chronos · role):",
            ha="left", va="center", fontsize=8, style="italic", color="#666", transform=ax.transAxes)
    for r in matched[:6]:
        y -= 0.075
        chron = f"{r['chronos']:.2f}" if r.get("chronos") is not None else "n/a"
        lm = "✓" if r.get("lineage_match") else " "
        ax.text(0.08, y,
                f"{r.get('cell_line','?')[:22]:22s}  {r.get('lineage','?')[:14]:14s}  "
                f"{chron:>6s}  {r.get('screen_role','?')}  {lm}",
                ha="left", va="center", fontsize=7.5, family="monospace",
                color="#222", transform=ax.transAxes)
    fig.savefig(out_path, bbox_inches="tight"); plt.close(fig)
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description="genomic_event_model_match (M11) — canonical P3 genomic join")
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--release-pin", default="26q1")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    summary = build_summary(args.target, args.indication, release_pin=args.release_pin)
    text = json.dumps(summary, indent=2, default=str)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
        print(f"wrote {args.out}")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
