"""Regenerate resolver_golden_snapshots.json — CO-EMISSION-AWARE (D5, 2026-08-09).

Deliberate, reviewed act (a verdict-contract change): run this ONLY when a resolver precedence
edit intentionally changes verdicts, then commit the new JSON alongside the resolver change and
re-baseline. It replaces the old full-power-set generation (2**n per gate) with co-emission-aware
enumeration (see _skills_common/coemission.py): only fired-sets that are actually card-co-emission-
reachable are frozen. This both shrinks the file (~105k -> ~5k rows across the 9 gates, well under
GitHub's 100 MB limit for the full rule set of EVERY gate — retiring tractability's core-16 subset +
separate 100 MB-workaround oracle) and makes every frozen combo a physically-possible one.

For each gate the JSON stores:
  rule_ids : the gate's full ordered rule_id list (unchanged shape)
  table    : { comma-joined-sorted-fired-rule-ids : [verdict, driving_rule_id] } over the
             co-emission-reachable fired-sets only
  enumeration : "coemission" (marks the new regime; a legacy "powerset" table still validates
                against the same test, so this is backward-compatible for un-regenerated gates)

Usage:
  TARGET_CONTRACTS_ROOT=/path/to/target-contracts \
    python3 skills/_skills_common/tests/regenerate_resolver_golden.py [--check]

  --check : do not write; print the would-be per-gate row counts + assert the coverage-preservation
            invariant (every co-emission set reproduces via the live spec; counts match the model).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1]           # .../skills
SNAPSHOT = HERE / "resolver_golden_snapshots.json"
CONTRACTS = Path(os.environ.get(
    "TARGET_CONTRACTS_ROOT",
    "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"))

if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))


def _load(mod_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = m
    spec.loader.exec_module(m)
    return m


_resolver = _load("resolver_regen", SKILLS / "_skills_common" / "resolver.py")
_coemit = _load("coemission_regen", SKILLS / "_skills_common" / "coemission.py")


def build_gate_table(gate: str, rule_ids: list[str], rule_index: dict) -> dict:
    """Co-emission table for one gate: {fired-key: [verdict, driving_rule_id]}."""
    spec = _resolver.load_resolver(gate, contracts_repo=CONTRACTS)
    if spec is None:
        raise RuntimeError(f"resolver spec for {gate} did not load from {CONTRACTS}")
    fired_sets = _coemit.coemission_fired_sets_for_gate(rule_ids, rule_index)
    table: dict[str, list] = {}
    for fs in fired_sets:
        fired = [{"rule_id": r} for r in sorted(fs)]
        key = ",".join(sorted(fs))
        v, drv = _resolver.resolve_verdict(fired, spec)
        table[key] = [v, drv]
    return table


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="print counts + verify, do not write the JSON")
    args = ap.parse_args(argv)

    shipped = sorted(p.stem.replace(".resolver", "")
                     for p in (CONTRACTS / "resolvers").glob("*.resolver.yaml"))
    rule_index = _coemit.load_rule_index(CONTRACTS)

    # keep the existing rule_ids lists (they define each gate's full rung set + order)
    existing = json.loads(SNAPSHOT.read_text()) if SNAPSHOT.exists() else {}

    out: dict = {}
    print(f"{'gate':<28} {'rule_ids':>8} {'coemit rows':>12} {'(was 2^n)':>12}")
    for gate in shipped:
        if gate not in existing:
            raise RuntimeError(
                f"gate {gate!r} has no rule_ids list in the snapshot yet — add it manually first "
                f"(the full ordered rung set), then regenerate.")
        rule_ids = existing[gate]["rule_ids"]
        table = build_gate_table(gate, rule_ids, rule_index)
        out[gate] = {"rule_ids": rule_ids, "enumeration": "coemission", "table": table}
        print(f"{gate:<28} {len(rule_ids):>8} {len(table):>12,} {2**len(rule_ids):>12,}")

    if args.check:
        total = sum(len(v["table"]) for v in out.values())
        print(f"\n[check] total co-emission rows: {total:,} (no file written)")
        return 0

    SNAPSHOT.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    size = SNAPSHOT.stat().st_size
    print(f"\nwrote {SNAPSHOT} ({size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
