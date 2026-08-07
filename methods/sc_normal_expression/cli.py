"""sc_normal_expression — build_summary entry point for the compose-dashboard live-reader.

`build_summary(target, indication) -> dict` is the single entry point the skills dispatcher
invokes. Mirrors the sc_tumor_expression_celltype/cli.py contract: deterministic
(target, indication) → summary dict with a primary `sc_normal_expression_class` categorical
and a data_unavailable-safe branch.
"""
from __future__ import annotations

import argparse
import json
import sys

from . import read as _read

METHOD_VERSION = "0.1.0"


def build_summary(target: str, indication: str) -> dict:
    """sc-normal-celltype-expression Tier-1 summary for a (target, indication).

    Returns the normal-tissue liability class, max-detection cell type, safety-essential
    flags, and breadth indicator. data_unavailable-safe for missing products or genes."""
    summary = _read.read_target_summary(target, indication)
    summary["method_version"] = METHOD_VERSION
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="sc normal-tissue cell-type expression summary.")
    ap.add_argument("--target", required=True, help="HGNC gene symbol")
    ap.add_argument("--indication", required=True, help="OncoTree indication code (e.g. COADREAD, NSCLC)")
    args = ap.parse_args(argv)
    print(json.dumps(build_summary(args.target, args.indication), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
