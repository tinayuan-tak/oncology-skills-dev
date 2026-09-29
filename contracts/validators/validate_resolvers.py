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
  (5) POST-RESOLVER CLAMP ARMS — every `post_resolver_clamp.precedence[].when_fired`
      rule_id exists (the dead-arm analogue of (2), which the clamp block previously
      escaped entirely), and every arm verdict is listed in `clamp_verdicts`.
  (6) MODALITY LENS SOUNDNESS — for an optional `modality_conditional` block: its
      verdict sets are declared clamp verdicts, are disjoint, and CLASSIFY every arm
      verdict (so "may a lens waive this?" is never left open); `insufficient` is
      rejected as a suppressing signal (a coverage token is not a safety judgement);
      and at least one suppressible arm actually declares a suppressing signal for
      some modality — otherwise the whole lens is unreachable and would pass review
      while changing nothing.

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


def _rule_signals(rules_dir: Path) -> dict[str, dict]:
    """rule_id -> its declared per-modality `signals:` mapping (absent -> {})."""
    out: dict[str, dict] = {}
    for rp in sorted(rules_dir.glob("*.rules.yaml")):
        data = yaml.safe_load(rp.read_text()) or {}
        for r in data.get("rules", []):
            rid = r.get("rule_id")
            if rid:
                out[rid] = r.get("signals") or {}
    return out


def _rung_rule_ids(rung: dict) -> list[str]:
    if "when_fired" in rung:
        return [rung["when_fired"]]
    if "when_any_fired" in rung:
        return list(rung["when_any_fired"])
    if "when_all_fired" in rung:
        return list(rung["when_all_fired"])
    return []


def _validate_post_resolver_clamp(
    spec: dict,
    report: ResolverReport,
    known_rule_ids: set[str],
    rule_signals: dict[str, dict] | None,
) -> None:
    """Checks (5)-(6): the post-resolver clamp declaration and its modality lens.

    The clamp block exists so Python-side decision logic is PR-reviewable in the
    contract; that only holds if the declaration is CHECKED, otherwise it drifts
    into decoration. A clamp arm naming a renamed rule_id is exactly the dead-arm
    class check (2) catches for rungs — and a `modality_conditional` block whose
    arms declare no signals at all can never suppress anything, so it would pass
    green by construction while claiming a behaviour the executor cannot deliver.
    """
    clamp = spec.get("post_resolver_clamp")
    if not isinstance(clamp, dict):
        return
    declared_clamp_verdicts = set(spec.get("clamp_verdicts", []) or [])

    arm_verdict: dict[str, str] = {}
    for i, arm in enumerate(clamp.get("precedence", []) or []):
        rid, verdict = arm.get("when_fired"), arm.get("verdict")
        if rid:
            arm_verdict[rid] = verdict
            if rid not in known_rule_ids:
                report.add_error(
                    f"DANGLING_CLAMP_ARM [post_resolver_clamp.precedence[{i}] "
                    f"verdict={verdict!r}]: rule_id `{rid}` is not declared in any "
                    f"interpretation-rules file — a clamp arm that can never fire."
                )
        if verdict and verdict not in declared_clamp_verdicts:
            report.add_error(
                f"UNDECLARED_CLAMP_VERDICT [post_resolver_clamp.precedence[{i}]]: "
                f"verdict `{verdict}` is not listed in `clamp_verdicts`, so the "
                f"emitted-verdict enum for this gate is incomplete."
            )

    mc = clamp.get("modality_conditional")
    if not isinstance(mc, dict):
        return

    suppressible = set(mc.get("suppressible_verdicts", []) or [])
    never = set(mc.get("never_suppressed_verdicts", []) or [])
    for label, group in (("suppressible_verdicts", suppressible), ("never_suppressed_verdicts", never)):
        unknown = sorted(group - declared_clamp_verdicts)
        if unknown:
            report.add_error(
                f"UNDECLARED_CLAMP_VERDICT [post_resolver_clamp.modality_conditional.{label}]: "
                f"{unknown} not listed in `clamp_verdicts`."
            )
    both = sorted(suppressible & never)
    if both:
        report.add_error(
            "CONTRADICTORY_SUPPRESSION [post_resolver_clamp.modality_conditional]: "
            f"{both} declared BOTH suppressible and never-suppressed."
        )
    unclassified = sorted(v for v in arm_verdict.values() if v and v not in suppressible and v not in never)
    if unclassified:
        report.add_error(
            "UNCLASSIFIED_CLAMP_VERDICT [post_resolver_clamp.modality_conditional]: "
            f"{unclassified} is minted by a precedence arm but appears in neither "
            "`suppressible_verdicts` nor `never_suppressed_verdicts` — whether a "
            "modality lens may waive it is left undeclared."
        )
    if "insufficient" in (mc.get("suppressing_signals") or []):
        report.add_error(
            "COVERAGE_TOKEN_AS_WAIVER [post_resolver_clamp.modality_conditional."
            "suppressing_signals]: `insufficient` declares a coverage gap, not a "
            "safety judgement, and a veto arm only fires when the measurement "
            "exists — admitting it would waive KILLs on missing data."
        )

    # An arm can be inert BY DESIGN: `selective_but_broadly_normal` is minted by two arms with
    # opposite lens behaviour, so suppressibility is declared per-VERDICT and evaluated per-ARM,
    # and the no-therapeutic-window / stromal-confound arms are `opposing` for every modality
    # deliberately. Those two warnings were therefore permanent, and a warning that always fires
    # is indistinguishable from one nobody has read — it sat in the atlas gap feed as
    # `dangling_rung` forever. So the expectation becomes DECLARABLE, with the declaration itself
    # checked in both directions: an undeclared inert arm still warns, and a declaration that has
    # gone stale (the arm became waivable) is an ERROR, because it now documents the opposite of
    # the safety behaviour. `expected_inert_arms` can silence a NAMED arm; it can never silence the
    # whole-block VACUOUS_MODALITY_LENS check below, which is computed from `reachable` alone.
    expected_inert: dict[str, str] = {}
    for i, entry in enumerate(mc.get("expected_inert_arms") or []):
        rid = (entry or {}).get("rule_id")
        if not rid:
            continue
        if rid in expected_inert:
            report.add_error(
                f"DUPLICATE_EXPECTED_INERT_ARM [post_resolver_clamp.modality_conditional."
                f"expected_inert_arms[{i}]]: `{rid}` declared twice."
            )
        expected_inert[rid] = (entry or {}).get("reason") or ""
        if rid not in arm_verdict:
            report.add_error(
                f"DANGLING_EXPECTED_INERT_ARM [post_resolver_clamp.modality_conditional."
                f"expected_inert_arms[{i}]]: `{rid}` is not a clamp precedence arm, so the "
                f"declaration waives a warning that could never have been emitted."
            )
        elif arm_verdict[rid] not in suppressible:
            report.add_error(
                f"MISDECLARED_EXPECTED_INERT_ARM [post_resolver_clamp.modality_conditional."
                f"expected_inert_arms[{i}]]: `{rid}` mints `{arm_verdict[rid]}`, which is not "
                f"in `suppressible_verdicts` — an arm no lens may waive in the first place "
                f"cannot be 'expectedly inert'."
            )

    if rule_signals is None:
        return
    # VACUITY: a lens that no arm can actually trigger is a claim the executor cannot honour.
    suppressing = set(mc.get("suppressing_signals") or [])
    reachable = []
    for rid, verdict in sorted(arm_verdict.items()):
        if verdict not in suppressible:
            continue
        declared = rule_signals.get(rid) or {}
        hits = sorted(m for m, s in declared.items() if s in suppressing)
        if hits:
            reachable.append(f"{rid}({','.join(hits)})")
            if rid in expected_inert:
                report.add_error(
                    f"STALE_EXPECTED_INERT_ARM [{rid}]: declared in `expected_inert_arms` as "
                    f"never waivable, but the rule now declares a {sorted(suppressing)} signal "
                    f"for {hits} — a modality lens CAN waive this arm, so the declared reason "
                    f"({expected_inert[rid] or '(none given)'}) no longer describes the "
                    f"behaviour. Remove the entry, or make the arm opposing again."
                )
        elif rid in rule_signals and rid not in expected_inert:
            report.add_warning(
                f"MODALITY_LENS_INERT_ARM [{rid}]: verdict `{verdict}` is declared "
                f"suppressible but the rule declares no {sorted(suppressing)} signal "
                f"for any modality, so no lens can ever waive this arm. If that is BY "
                f"DESIGN, declare it in `expected_inert_arms` with a reason."
            )
    if not reachable:
        report.add_error(
            "VACUOUS_MODALITY_LENS [post_resolver_clamp.modality_conditional]: NO "
            "suppressible arm declares a suppressing signal for any modality, so the "
            "whole block is unreachable — it would pass review while changing nothing."
        )


def validate_resolver_file(
    path: Path,
    known_rule_ids: set[str],
    schema: dict | None = None,
    rule_signals: dict[str, dict] | None = None,
) -> ResolverReport:
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
                    f"a dead rung that can never fire (typo / renamed rule?)."
                )
        dr = rung.get("driving_rule")
        if dr is not None and dr not in rung_ids:
            report.add_error(
                f"BAD_DRIVING_RULE [resolve[{i}] verdict={rung.get('verdict')!r}]: "
                f"driving_rule `{dr}` is not one of this rung's own rule_ids {rung_ids}."
            )

    # (5)-(6) post-resolver clamp arms + the optional modality lens
    _validate_post_resolver_clamp(spec, report, known_rule_ids, rule_signals)

    # (4) explicit default (schema already requires it; explicit message)
    if not spec.get("default"):
        report.add_error(
            "MISSING_DEFAULT: a resolver must declare an explicit `default` "
            "verdict (this is what proves there is no silent fall-through)."
        )
    return report


def validate_dir(resolvers_dir: Path, rules_dir: Path) -> list[ResolverReport]:
    known = _all_rule_ids(rules_dir)
    signals = _rule_signals(rules_dir)
    schema = json.loads(SCHEMA_PATH.read_text())
    return [validate_resolver_file(p, known, schema, signals) for p in sorted(resolvers_dir.glob("*.resolver.yaml"))]


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
            print(f"    [ERROR]   {e}")
            ok = False
        for w in r.warnings:
            print(f"    [WARNING] {w}")
    n = len(reports)
    print(
        f"\nSummary: {n} resolver(s); "
        f"{sum(1 for r in reports if r.ok and not r.warnings)} clean, "
        f"{sum(1 for r in reports if not r.ok)} with errors."
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_main())
