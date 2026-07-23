"""surface_antigen_density_ladder.cli — audit + read the absolute-density calibration corpus.

Two subcommands:
  read   --target ERBB2 [--indication BRCA]   → the grade-resolved absolute-density summary (JSON)
  audit  [--corpus PATH]                       → validate EVERY corpus row, report admissible vs
                                                 rejected (with per-row reason). The governance tool:
                                                 when the corpus is populated, `audit` proves no
                                                 fabrication-prone / malformed row slipped in.

`audit` is how a populate-time reviewer checks a candidate table before it is committed — every row
must be admissible (or its rejection reason understood). A header-only corpus audits as 0/0.
"""
from __future__ import annotations

import argparse
import json
import sys

from . import read as _read


def _cmd_read(args) -> int:
    out = _read.read_absolute_density(args.target, indication=args.indication,
                                      corpus_path=args.corpus)
    print(json.dumps(out, indent=2, default=str))
    return 0


def _cmd_audit(args) -> int:
    rows = _read._load_corpus(args.corpus)
    admissible, rejected = [], []
    for i, row in enumerate(rows):
        ok, reason = _read.validate_row(row)
        (admissible if ok else rejected).append((i, row.get("target", "?"), reason))
    print(f"[audit] corpus rows: {len(rows)}  admissible: {len(admissible)}  rejected: {len(rejected)}")
    for i, tgt, reason in rejected:
        print(f"  REJECT row {i} ({tgt}): {reason}")
    # a populated corpus with ANY rejected row is a governance failure → nonzero exit for CI use
    return 1 if rejected else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Absolute surface-density calibration corpus.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("read", help="grade-resolved absolute-density summary for a target")
    pr.add_argument("--target", required=True)
    pr.add_argument("--indication", default=None)
    pr.add_argument("--corpus", default=None, help="override corpus TSV path (default: committed)")
    pr.set_defaults(func=_cmd_read)

    pa = sub.add_parser("audit", help="validate every corpus row; nonzero exit if any rejected")
    pa.add_argument("--corpus", default=None)
    pa.set_defaults(func=_cmd_audit)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
