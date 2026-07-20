"""validate_resolvers.py — verdict-resolver spec validator (gap #5, 2026-07-20).

Checks each resolvers/<gate>.resolver.yaml:
  (1) STRUCTURAL — validates against schemas/resolver.schema.json.
  (2) NO DANGLING RUNGS — every rule_id referenced in a rung (when_fired /
      when_any_fired / when_all_fired) EXISTS in the interpretation-rules files. A
      typo'd or renamed rule_id in a rung is a DEAD rung that can never fire — the
      silent-drift failure this validator exists to catch (the rename-bug class, now
      statically checkable, which an if-chain never could be).
  (3) DRIVING_RULE VALIDITY — any explicit `driving_rule` is one of the rung's own rule_ids.
  (4) EXPLICIT DEFAULT — present (schema-enforced; re-checked here for a clear message).

The behavioral "every fireable card-class maps to a rung" completeness is proven per-gate
by the golden-oracle equivalence test in claude-oncology-skills
(_skills_common/tests/test_resolver_*_oracle.py) — spec output == the Python _verdict
byte-for-byte across all fired-set combinations. This validator is the STATIC companion.

CLI:
  python validators/validate_resolvers.py --resolvers resolvers/ --rules interpretation-rules/
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "resolver.schema.json"


@dataclass
class ResolverReport:
    path: str
    ok: bool = True
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def add_error(self, m: str):
        self.ok = False
        self.errors.append(m)

    def add_warning(self, m: str):
        self.warnings.append(m)


def _all_rule_ids(rules_dir: Path) -> set[str]:
    """Every rule_id declared across the interpretation-rules files."""
    ids: set[str] = set()
    for rp in sorted(rules_dir.glob("*.rules.yaml")):
        data = yaml.safe_load(rp.read_text()) or {}
        for r in data.get("rules", []):
            rid = r.get("rule_id")
            if rid:
                ids.add(rid)
    return ids


def _rung_rule_ids(rung: dict) -> list[str]:
    if "when_fired" in rung:
        return [rung["when_fired"]]
    if "when_any_fired" in rung:
        return list(rung["when_any_fired"])
    if "when_all_fired" in rung:
        return list(rung["when_all_fired"])
    return []


def validate_resolver_file(path: Path, known_rule_ids: set[str],
                           schema: dict | None = None) -> ResolverReport:
    report = ResolverReport(path=str(path))
    try:
        spec = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        report.add_error(f"YAML_PARSE: {e}")
        return report
    if not isinstance(spec, dict):
        report.add_error("YAML_SHAPE: expected a mapping at top level")
        return report

    if schema is None:
        schema = json.loads(SCHEMA_PATH.read_text())
    for err in Draft202012Validator(schema).iter_errors(spec):
        loc = ".".join(str(p) for p in err.absolute_path) or "<root>"
        report.add_error(f"STRUCTURAL [{loc}]: {err.message}")
    if not report.ok:
        return report  # structural first

    # (2) no dangling rungs + (3) driving_rule validity
    for i, rung in enumerate(spec.get("resolve", [])):
        rung_ids = _rung_rule_ids(rung)
        for rid in rung_ids:
            if rid not in known_rule_ids:
                report.add_error(
                    f"DANGLING_RUNG [resolve[{i}] verdict={rung.get('verdict')!r}]: "
                    f"rule_id `{rid}` is not declared in any interpretation-rules file — "
                    f"a dead rung that can never fire (typo / renamed rule?).")
        dr = rung.get("driving_rule")
        if dr is not None and dr not in rung_ids:
            report.add_error(
                f"BAD_DRIVING_RULE [resolve[{i}] verdict={rung.get('verdict')!r}]: "
                f"driving_rule `{dr}` is not one of this rung's own rule_ids {rung_ids}.")

    # (4) explicit default (schema already requires it; explicit message)
    if not spec.get("default"):
        report.add_error("MISSING_DEFAULT: a resolver must declare an explicit `default` "
                         "verdict (this is what proves there is no silent fall-through).")
    return report


def validate_dir(resolvers_dir: Path, rules_dir: Path) -> list[ResolverReport]:
    known = _all_rule_ids(rules_dir)
    schema = json.loads(SCHEMA_PATH.read_text())
    return [validate_resolver_file(p, known, schema)
            for p in sorted(resolvers_dir.glob("*.resolver.yaml"))]


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--resolvers", type=Path, required=True)
    ap.add_argument("--rules", type=Path, required=True)
    args = ap.parse_args(argv)
    reports = validate_dir(args.resolvers, args.rules)
    ok = True
    print("validate_resolvers.py results:")
    for r in reports:
        status = "OK" if (r.ok and not r.warnings) else ("WARN" if r.ok else "FAIL")
        print(f"  [{status}] {Path(r.path).name}")
        for e in r.errors:
            print(f"    [ERROR]   {e}"); ok = False
        for w in r.warnings:
            print(f"    [WARNING] {w}")
    n = len(reports)
    print(f"\nSummary: {n} resolver(s); "
          f"{sum(1 for r in reports if r.ok and not r.warnings)} clean, "
          f"{sum(1 for r in reports if not r.ok)} with errors.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_main())
