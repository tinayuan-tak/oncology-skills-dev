"""build_rule_role_partition.py — M5 of the factored-record migration (VERDICT_REPRESENTATION move #5).

Make the verdict-INERT rules an EXPLICIT display channel instead of silently-dead `signals:`. Every
interpretation rule is classified by ROLE:

  * gating   — its rule_id is referenced by at least one resolver rung (when_fired / when_any_fired /
               when_all_fired), so it can move a verdict.
  * display  — referenced by NO resolver: it is annotation-only (a claim-vector / key-signal / figure
               input), NOT a verdict driver. This is the ~69% the audit flagged as inert; naming them
               `display` turns "dead emitter" into "deliberately non-gating," so the scorecard's I1
               (signal-sink coverage) and I3 (per-coordinate VOI) are measured only against gating rules.

The partition is emitted as a committed snapshot (coverage/rule_role_partition.yaml) with a
`--self-check` mode (mirrors build_eval_ledger): a rule gaining/losing resolver consumption fails CI
until the snapshot is consciously regenerated. Low-churn — no per-rule schema edits.

  python validators/build_rule_role_partition.py               # regenerate the snapshot
  python validators/build_rule_role_partition.py --self-check  # CI: fail if the committed snapshot drifted
"""

from __future__ import annotations

import argparse
import glob
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RESOLVERS = ROOT / "resolvers"
RULES = ROOT / "interpretation-rules"
PARTITION_PATH = ROOT / "coverage" / "rule_role_partition.yaml"


def _resolver_referenced_rule_ids() -> set[str]:
    """Every rule_id any resolver rung keys on (the union of when_fired / when_any_fired /
    when_all_fired across all resolvers) — the GATING set."""
    refs: set[str] = set()
    for p in sorted(glob.glob(str(RESOLVERS / "*.resolver.yaml"))):
        spec = yaml.safe_load(Path(p).read_text()) or {}
        for rung in spec.get("resolve", []) or []:
            if "when_fired" in rung:
                refs.add(rung["when_fired"])
            refs.update(rung.get("when_any_fired", []) or [])
            refs.update(rung.get("when_all_fired", []) or [])
    return refs


def _all_rules() -> dict[str, str]:
    """rule_id -> source rules file basename, for every defined interpretation rule."""
    out: dict[str, str] = {}
    for p in sorted(glob.glob(str(RULES / "*.rules.yaml"))):
        base = os.path.basename(p)
        for r in (yaml.safe_load(Path(p).read_text()) or {}).get("rules") or []:
            rid = r.get("rule_id")
            if rid:
                out[rid] = base
    return out


def compute_partition() -> dict:
    gating_refs = _resolver_referenced_rule_ids()
    rules = _all_rules()
    gating = sorted(r for r in rules if r in gating_refs)
    display = sorted(r for r in rules if r not in gating_refs)
    return {
        "_doc": (
            "M5 rule-role partition (VERDICT_REPRESENTATION move #5). gating = referenced by a "
            "resolver rung (verdict-driving); display = referenced by NO resolver (annotation-only: "
            "claim-vector / key-signal / figure input). Regenerate with "
            "build_rule_role_partition.py; --self-check gates drift."
        ),
        "counts": {"total": len(rules), "gating": len(gating), "display": len(display)},
        "gating": gating,
        "display": display,
    }


def _emit_yaml(partition: dict) -> str:
    return yaml.safe_dump(partition, sort_keys=False, width=100)


def self_check() -> tuple[bool, list[str]]:
    if not PARTITION_PATH.exists():
        return False, [f"missing {PARTITION_PATH.name} — run without --self-check to generate it"]
    committed = yaml.safe_load(PARTITION_PATH.read_text()) or {}
    fresh = compute_partition()
    errs: list[str] = []
    for key in ("gating", "display"):
        cset, fset = set(committed.get(key) or []), set(fresh[key])
        if cset != fset:
            added, removed = sorted(fset - cset), sorted(cset - fset)
            errs.append(
                f"{key} drift: +{added or '[]'} -{removed or '[]'} "
                f"(a rule changed resolver-consumption; regenerate the snapshot consciously)"
            )
    return (not errs), errs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--self-check",
        action="store_true",
        help="CI-safe: fail if the committed partition drifted from the live contracts",
    )
    args = ap.parse_args(argv)

    if args.self_check:
        ok, errs = self_check()
        print("build_rule_role_partition.py --self-check:")
        for e in errs:
            print(f"  [DRIFT] {e}")
        print("  OK" if ok else "  FAILED")
        return 0 if ok else 1

    partition = compute_partition()
    PARTITION_PATH.parent.mkdir(parents=True, exist_ok=True)
    PARTITION_PATH.write_text(_emit_yaml(partition))
    c = partition["counts"]
    print(
        f"wrote {PARTITION_PATH.relative_to(ROOT)} — {c['gating']} gating / {c['display']} display "
        f"({100 * c['display'] // c['total']}% annotation-only) of {c['total']} rules."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
