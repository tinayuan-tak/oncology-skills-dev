"""CLI + dispatcher entrypoint for the sc-surface RNA<->protein concordance arm."""

from __future__ import annotations

import json
from pathlib import Path

from . import read as _read

METHOD_VERSION = "0.1.0"


def build_summary(target: str, indication: str = None) -> dict:
    """Dispatcher entrypoint (CARD_DISPATCHERS contract). indication is accepted but NOT consumed —
    surface RNA<->protein concordance is a per-target property measured across cell types within the
    CITE-seq atlas, not indication-scoped."""
    summary = _read.read_sc_surface_concordance(target, indication=indication)
    summary["method_version"] = METHOD_VERSION
    return summary


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", default=None)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    summary = build_summary(args.target, args.indication)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    (args.out / "manifest.json").write_text(
        json.dumps(
            {
                "method": "sc_surface_concordance",
                "method_version": METHOD_VERSION,
                "target": args.target,
                "rna_as_biomarker": summary.get("rna_as_biomarker"),
                "artifacts": {"summary": "summary.json"},
                "plotly_figures": [],
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
