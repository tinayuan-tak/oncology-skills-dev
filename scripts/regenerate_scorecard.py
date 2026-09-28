#!/usr/bin/env python
"""Regenerate the component scorecard — THE single aggregate entrypoint (#1987, A0a).

Aggregates the per-skill shards (``scorecard/<skill>.json``) and renders the shared
``scorecard/SCORECARD.md`` deterministically. Adapters write their own shard and nothing else; this
script is the only writer of the shared render.

Usage (from the repo root, home checkout):

    pixi run python scripts/regenerate_scorecard.py                 # aggregate + render
    pixi run python scripts/regenerate_scorecard.py --init-missing  # also create baseline shards
                                                                    # (all-NULL) for roster skills
                                                                    # that have none; never overwrites
    pixi run python scripts/regenerate_scorecard.py --check         # write nothing; exit 1 on any
                                                                    # drift (missing/extra shard,
                                                                    # stale committed render)

Exit status: 0 = clean; 1 = problems (each printed on its own ``PROBLEM:`` line).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "skills"))

from _skills_common import component_scorecard as cs  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--init-missing",
        action="store_true",
        help="create a baseline (all-NULL) shard for every roster skill without one (never overwrites)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify committed state matches a fresh regeneration; write nothing; exit 1 on drift",
    )
    args = parser.parse_args(argv)
    if args.check and args.init_missing:
        parser.error("--check writes nothing; it cannot be combined with --init-missing")

    problems = cs.regenerate(REPO_ROOT, init_missing=args.init_missing, check=args.check)
    for problem in problems:
        print(f"PROBLEM: {problem}")
    if problems:
        return 1
    print(f"OK: {cs.SCORECARD_DIRNAME}/{cs.RENDER_FILENAME} {'is current' if args.check else 'regenerated'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
