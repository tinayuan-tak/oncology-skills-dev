"""rename_card_id.py — word-boundary-safe card_id rename across the framework repos.

A card_id is the highest-fan-out identifier in the framework (~26-90 live refs each across
target-contracts cards+rules, claude-oncology-skills CARDS/SUB_SKILL_CARDS/dispatcher/tests,
analysis-methods). A naive `sed s/old/new/g` is WRONG because several ids are substrings of others
(expression-distribution ⊂ tumor-expression-distribution ⊂ tumor-expression-distribution-subtype) —
it would corrupt the superset ids. This does a WORD-BOUNDARY-anchored replace: the id must be bounded
by a non-id character (not [-a-z]) on both sides, so a preceding '-' blocks the match.

FORWARD-RENAME ONLY. It rewrites the LIVE vocabulary (cards/rules/skills/methods). It does NOT touch
stored data-products evidence packages — those are immutable directory-keyed history; the vocabulary's
card_id_aliases map (old→new) lets tooling resolve historical names. Pass --repos to scope.

Usage:
  # dry-run (default): report every file+line that WOULD change, no writes
  python scripts/rename_card_id.py --old expression-distribution --new cellline-rna-distribution
  # apply:
  python scripts/rename_card_id.py --old expression-distribution --new cellline-rna-distribution --apply
  # also rename the card YAML file + a card dir if named after the id:
  python scripts/rename_card_id.py --old ... --new ... --apply --rename-files
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DEFAULT_REPOS = [
    "rnd-computational-biology-oncology-target-contracts",
    "rnd-computational-biology-oncology-claude-oncology-skills",
    "rnd-computational-biology-oncology-analysis-methods",
]
_EXTS = {".py", ".yaml", ".yml", ".md", ".json"}
# skip generated / vendored / history dirs
_SKIP_DIRS = {".git", "__pycache__", ".cache", "node_modules", "health"}


def _boundary_re(card_id: str) -> re.Pattern:
    """Match card_id ONLY when not part of a longer id — i.e. not preceded/followed by [-a-z0-9].
    Uses lookarounds so replacement leaves the boundary chars intact."""
    return re.compile(rf"(?<![-a-z0-9]){re.escape(card_id)}(?![-a-z0-9])")


def _iter_files(home: Path, repos: list[str]):
    for repo in repos:
        root = home / repo
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if p.is_file() and p.suffix in _EXTS and not any(d in p.parts for d in _SKIP_DIRS):
                yield p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Word-boundary-safe card_id rename.")
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    ap.add_argument("--rename-files", action="store_true",
                    help="also rename a <old>.card.yaml file + any dir named exactly <old>")
    ap.add_argument("--home", default=str(Path.home()))
    ap.add_argument("--repos", nargs="*", default=DEFAULT_REPOS)
    args = ap.parse_args(argv)

    pat = _boundary_re(args.old)
    home = Path(args.home)
    total_hits = total_files = 0
    for p in _iter_files(home, args.repos):
        try:
            text = p.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        hits = len(pat.findall(text))
        if not hits:
            continue
        total_hits += hits
        total_files += 1
        rel = p.relative_to(home)
        print(f"  {rel}: {hits} occurrence(s)")
        if args.apply:
            p.write_text(pat.sub(args.new, text))

    print(f"\n{'APPLIED' if args.apply else 'DRY-RUN'}: {total_hits} occurrence(s) across "
          f"{total_files} file(s) for {args.old!r} -> {args.new!r}")
    if args.rename_files and args.apply:
        for repo in args.repos:
            root = home / repo
            cardf = root / "cards" / f"{args.old}.card.yaml"
            if cardf.exists():
                dest = root / "cards" / f"{args.new}.card.yaml"
                cardf.rename(dest)
                print(f"  renamed card file: {cardf.relative_to(home)} -> {dest.name}")
    if not args.apply:
        print("(re-run with --apply to write; --rename-files to move the card YAML too)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
