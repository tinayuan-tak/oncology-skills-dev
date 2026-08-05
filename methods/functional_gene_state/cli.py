"""CLI + emitter for functional_gene_state (M6, genetic-only Phase 1).

Emits the harmonized two-hit / biallelic-inactivation summary for a (target, indication):
patient (TCGA) + model (DepMap) state distributions + a target-level headline class.
"""
from __future__ import annotations
import os

import argparse
import json
import sys
from pathlib import Path

from . import read as _read

METHOD_VERSION = "0.1.0"

# state → (light, dark) hex for the card figure. biallelic = strongest (loss-of-function complete).
_STATE_COLORS = {
    "biallelic-genetic": ("#8f3f22", "#5a1e1e"),   # completed two-hit — deep warm
    "monoallelic":       ("#c0803a", "#8f5f22"),   # single hit — ochre
    "wt":                ("#b8bcc0", "#7d8288"),   # wild-type — neutral
    "uncertain":         ("#d9dbdd", "#a9adb1"),   # undeterminable — light gray
}


DEFAULT_TARGET_CONTRACTS = os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")

# per-sample-state → fill for the stacked composition bar (biallelic = deepest / strongest LoF).
_STATE_FILL = {
    "biallelic-genetic": "#8f3f22",   # completed two-hit — deep warm
    "monoallelic":       "#c0803a",   # single hit — ochre
    "wt":                "#b8bcc0",   # wild-type — neutral gray
    "uncertain":         "#dfe1e3",   # undeterminable — light gray
}
_STATE_ORDER = ["biallelic-genetic", "monoallelic", "wt", "uncertain"]


def build_summary(target: str, indication: str) -> dict:
    """functional_gene_state summary for a (target, indication)."""
    summary = _read.read_functional_gene_state(target, indication)
    summary["method_version"] = METHOD_VERSION
    return summary


def _load_style(contracts_dir):
    import matplotlib.pyplot as plt
    from pathlib import Path as _P
    style = _P(contracts_dir) / "figure-style" / "matplotlibrc"
    if style.exists():
        try:
            plt.style.use(str(style))
        except Exception:  # noqa: BLE001
            pass


def emit_svg(target: str, indication: str, summary: dict, out_dir: Path,
             contracts_dir=DEFAULT_TARGET_CONTRACTS):
    """Tier-3 SVG: per-arm STACKED composition of functional gene states (patient vs model) —
    the share of samples that are wt / monoallelic / biallelic-genetic / uncertain. None if
    neither arm has a state distribution (data_unavailable)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    _load_style(contracts_dir)

    arms = []  # (label, state_counts, fraction_biallelic)
    for key, label in (("patient", "Patient (TCGA)"), ("model", "Model (DepMap)")):
        arm = summary.get(key) or {}
        counts = arm.get("state_counts")
        if counts and arm.get("n_samples"):
            arms.append((label, counts, arm.get("fraction_biallelic")))
    if not arms:
        return None

    out_path = Path(out_dir) / "figure_functional_gene_state.svg"
    fig, ax = plt.subplots(figsize=(6.8, 3.2))
    y_positions = list(range(len(arms)))
    for yi, (label, counts, fb) in zip(y_positions, arms):
        total = sum(counts.get(s, 0) for s in _STATE_ORDER) or 1
        left = 0.0
        for s in _STATE_ORDER:
            frac = counts.get(s, 0) / total
            if frac <= 0:
                continue
            ax.barh(yi, frac, left=left, height=0.55, color=_STATE_FILL[s],
                    edgecolor="white", linewidth=0.8,
                    label=s if yi == 0 else None)
            if frac >= 0.08:  # direct-label only segments wide enough to read
                ax.text(left + frac / 2, yi, f"{frac*100:.0f}%", ha="center", va="center",
                        fontsize=8, color="white", weight="bold")
            left += frac
    ax.set_yticks(y_positions)
    ax.set_yticklabels([f"{lbl}\n(biallelic {fb*100:.0f}%)" if fb is not None else lbl
                        for lbl, _, fb in arms], fontsize=9)
    ax.set_xlim(0, 1); ax.set_xlabel("fraction of samples", fontsize=9)
    ax.set_title(f"{target} in {indication} — functional gene state (genetic-only)",
                 fontsize=10, weight="bold")
    # legend once, deduplicated, below the plot
    handles, labels = ax.get_legend_handles_labels()
    seen = dict(zip(labels, handles))
    ax.legend(seen.values(), [l.replace("-", " ") for l in seen.keys()],
              loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=4, fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight"); plt.close(fig)
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description="functional_gene_state (M6) — biallelic two-hit profile")
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--out", type=Path, default=None,
                    help="optional path to write the JSON summary")
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
