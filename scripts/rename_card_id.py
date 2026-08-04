"""rename_card_id.py — word-boundary-safe card_id rename across the framework repos.

A card_id is the highest-fan-out identifier in the framework (~26-90 live refs each across
target-contracts cards+rules, claude-oncology-skills CARDS/SUB_SKILL_CARDS/dispatcher/tests,
analysis-methods). A naive `sed s/old/new/g` is WRONG because several ids are substrings of others
(e.g. expression-distribution ⊂ tumor-expression-distribution ⊂ ...-subtype — the pre-rename ids) —
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
    ap.add_argument("--commit", action="store_true",
                    help="git-stage EXACTLY the files this tool edited/renamed (per repo) + commit. "
                         "Requires --apply. Never stages a file the tool did not touch (fixes the "
                         "too-broad/too-narrow `git add` error class) and never pushes (run guards + "
                         "push by hand). Uses --message or a standard default.")
    ap.add_argument("--message", default=None, help="commit message (with --commit)")
    ap.add_argument("--home", default=str(Path.home()))
    ap.add_argument("--repos", nargs="*", default=DEFAULT_REPOS)
    args = ap.parse_args(argv)
    if args.commit and not args.apply:
        ap.error("--commit requires --apply")

    pat = _boundary_re(args.old)
    home = Path(args.home)
    total_hits = total_files = 0
    edited_by_repo: dict[str, list[Path]] = {r: [] for r in args.repos}
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
            repo = rel.parts[0]
            edited_by_repo.setdefault(repo, []).append(p)

    print(f"\n{'APPLIED' if args.apply else 'DRY-RUN'}: {total_hits} occurrence(s) across "
          f"{total_files} file(s) for {args.old!r} -> {args.new!r}")

    # File renames (card YAML + design doc) — tracked so --commit stages the rename too.
    renamed_by_repo: dict[str, list[tuple[Path, Path]]] = {r: [] for r in args.repos}
    if args.rename_files and args.apply:
        for repo in args.repos:
            root = home / repo
            for rel_dir in ("cards", "docs/design/cards"):
                src = root / rel_dir / f"{args.old}.card.yaml"
                if not src.exists():
                    src = root / rel_dir / f"{args.old}.md"
                dest = src.with_name(src.name.replace(args.old, args.new))
                if src.exists():
                    src.rename(dest)
                    renamed_by_repo.setdefault(repo, []).append((src, dest))
                    print(f"  renamed file: {src.relative_to(home)} -> {dest.name}")

    if args.commit and args.apply:
        import subprocess
        for repo in args.repos:
            root = home / repo
            paths = [str(p.relative_to(root)) for p in edited_by_repo.get(repo, [])]
            for src, dest in renamed_by_repo.get(repo, []):
                paths += [str(src.relative_to(root)), str(dest.relative_to(root))]
            if not paths:
                continue
            msg = args.message or (f"rename card_id {args.old} -> {args.new} "
                                   f"(word-boundary-safe; {repo.split('-')[-1]} slice)")
            # stage EXACTLY the tool's files (git add -A <paths> handles the deletions from renames)
            subprocess.run(["git", "-C", str(root), "add", "-A", "--", *paths], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", msg,
                            "-m", "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"],
                           check=True)
            print(f"  [{repo}] committed {len(paths)} path(s) — NOT pushed (run guards + push by hand)")

    if not args.apply:
        print("(re-run with --apply to write; --rename-files to move files; --commit to stage+commit)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
