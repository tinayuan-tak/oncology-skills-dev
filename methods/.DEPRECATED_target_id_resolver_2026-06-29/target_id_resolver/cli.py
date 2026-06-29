"""Thin CLI wrapper around resolve() — exposed as `resolve-target-id`."""

from __future__ import annotations

import argparse
import json
import sys

from .core import DEFAULT_RESOLVER_RELEASE, resolve
from .errors import AmbiguousInputError, NotFoundError, ResolverError


def main() -> int:
    p = argparse.ArgumentParser(
        prog="resolve-target-id",
        description="Resolve a gene/protein identifier to a canonical Target object.",
    )
    p.add_argument(
        "--input",
        required=True,
        help="Identifier to resolve. May be HGNC symbol (TP53), HGNC ID (HGNC:11998), "
             "Ensembl gene ID (ENSG00000141510 or ENSG00000141510.18), UniProt accession "
             "(P04637), or NCBI Entrez ID (7157).",
    )
    p.add_argument(
        "--release",
        default=DEFAULT_RESOLVER_RELEASE,
        help=f"Resolver release pin (default: {DEFAULT_RESOLVER_RELEASE}).",
    )
    p.add_argument(
        "--out",
        default="-",
        help="Output JSON path (default: stdout).",
    )
    args = p.parse_args()

    try:
        target = resolve(args.input, resolver_release=args.release)
    except NotFoundError as e:
        print(f"resolve-target-id: NotFound: {e}", file=sys.stderr)
        return 3
    except AmbiguousInputError as e:
        print(f"resolve-target-id: Ambiguous: {e}", file=sys.stderr)
        return 4
    except ResolverError as e:
        print(f"resolve-target-id: ResolverError: {e}", file=sys.stderr)
        return 5

    body = json.dumps(target.model_dump(mode="json", exclude_none=True), indent=2)
    if args.out == "-":
        print(body)
    else:
        from pathlib import Path
        Path(args.out).write_text(body)
        print(f"Wrote Target to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
