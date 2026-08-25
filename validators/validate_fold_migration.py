"""validate_fold_migration.py — M3 completion guard (VERDICT_REPRESENTATION_FOLD.md).

The Fold migration is COMPLETE: every resolver evaluates `match_all_reduce`, so the interpreter's
legacy `first_match` path is used by NO production spec — it is retired to a test oracle (the
equivalence guard). This validator LOCKS that end-state and the priority-integrity it depends on, so a
new or hand-edited resolver cannot silently regress it:

  1. every resolvers/*.resolver.yaml declares `evaluation: match_all_reduce` (no first_match in prod);
  2. every match_all_reduce resolver gives EVERY rung an explicit integer `priority`, and those
     priorities are UNIQUE within the resolver (match-all-then-reduce needs a total order to pick a
     unique min — a missing/duplicate priority reintroduces the positional ambiguity the Fold removed).

CLI: python validators/validate_fold_migration.py --resolvers resolvers/
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import yaml


def validate(resolvers_dir: Path) -> tuple[bool, list[str]]:
    errs: list[str] = []
    files = sorted(glob.glob(str(resolvers_dir / "*.resolver.yaml")))
    if not files:
        return False, [f"NO_RESOLVERS under {resolvers_dir}"]
    for p in files:
        name = Path(p).name
        spec = yaml.safe_load(Path(p).read_text()) or {}
        if spec.get("evaluation") != "match_all_reduce":
            errs.append(f"{name}: evaluation={spec.get('evaluation')!r} — the Fold is complete; every "
                        f"resolver must be 'match_all_reduce' (first_match is retired to a test oracle).")
            continue
        rungs = spec.get("resolve") or []
        priorities = []
        for i, rung in enumerate(rungs):
            pr = rung.get("priority")
            if not isinstance(pr, int):
                errs.append(f"{name}: rung #{i} (verdict={rung.get('verdict')!r}) has no integer "
                            f"`priority` — match_all_reduce needs one on every rung.")
            else:
                priorities.append(pr)
        dupes = {x for x in priorities if priorities.count(x) > 1}
        if dupes:
            errs.append(f"{name}: duplicate priorities {sorted(dupes)} — priorities must be UNIQUE so "
                        f"match-all-then-reduce picks a single min (no positional ambiguity).")
    return (not errs), errs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--resolvers", type=Path, default=Path("resolvers/"))
    args = ap.parse_args(argv)
    ok, errs = validate(args.resolvers)
    print("validate_fold_migration.py (M3 completion guard):")
    for e in errs:
        print(f"  [ERROR] {e}")
    print("  OK — all resolvers folded (match_all_reduce, unique priorities)" if ok else "  FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
