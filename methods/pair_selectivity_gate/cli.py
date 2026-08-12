"""CLI + dispatcher entrypoint for the surface same-cell AVIDITY (co-localization) card."""
from __future__ import annotations

import json
from pathlib import Path

from . import samecell as _samecell

METHOD_VERSION = "0.1.0"


def build_summary(target: str, indication: str = None) -> dict:
    """Dispatcher entrypoint (CARD_DISPATCHERS contract). Target-centric same-cell avidity: scans the
    indication's same-cell coexpr cube for every pair involving the target and returns the best-partner
    avidity call. Indication-scoped (the cube is per-indication)."""
    summary = _samecell.read_target_samecell_avidity(target, indication)
    summary["method_version"] = METHOD_VERSION
    return summary


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    summary = build_summary(args.target, args.indication)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    (args.out / "manifest.json").write_text(json.dumps(
        {"method": "pair_selectivity_gate", "method_version": METHOD_VERSION, "target": args.target,
         "samecell_avidity_class": summary.get("samecell_avidity_class"),
         "artifacts": {"summary": "summary.json"}, "plotly_figures": []}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
