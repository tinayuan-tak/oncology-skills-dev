"""CLI + dispatcher entrypoint for normal-immune surface-protein safety."""

from __future__ import annotations

import json
from pathlib import Path

from . import read as _read

METHOD_VERSION = "0.1.0"


def build_summary(target: str, indication: str = None) -> dict:
    """Dispatcher entrypoint. indication accepted for the contract but NOT consumed — the immune
    surface substrate (PBMC) is indication-independent."""
    summary = _read.read_sc_surface_normal_safety(target, indication=indication)
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
                "method": "sc_surface_normal_safety",
                "method_version": METHOD_VERSION,
                "target": args.target,
                "sc_surface_normal_class": summary.get("sc_surface_normal_class"),
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
