"""driver_pathway_position.cli — thin CLI over the library entry (read.py).

No build step: this method composes already-materialized derived products (Sanchez-Vega per-gene
membership, per-indication alteration frequency, SIGNOR per-gene edges) at read time, so the CLI is a
convenience wrapper that prints the card summary for a (target, indication) pair.
"""

from __future__ import annotations

import argparse
import json
import sys

from .read import METHOD_VERSION, read_driver_pathway_position


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="driver-pathway-position positional read (verdict-inert).")
    p.add_argument("--target", required=True, help="HGNC gene symbol, e.g. KRAS")
    p.add_argument("--indication", required=True, help="Indication code, e.g. COADREAD")
    p.add_argument(
        "--membership-path", default=None, help="Local parquet override for the F1 membership product (tests)."
    )
    args = p.parse_args(argv)
    summary = read_driver_pathway_position(
        target=args.target, indication=args.indication, membership_path=args.membership_path
    )
    json.dump(summary, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["METHOD_VERSION", "read_driver_pathway_position", "main"]
