#!/usr/bin/env python3
"""
validate_interpretation_rules.py — Tier-2 rule validator.

Checks that every rule in an interpretation-rules file is REACHABLE from the cards
that declare its evidence — i.e. that the `when.{card_id, field, value}` triple can
actually be produced by an emitting card. Catches rule rot when card_specs evolve.

Three checks per rule:
  (1) Structural — rules file validates against schemas/interpretation_rules.schema.json.
  (2) card_id reachability — the rule's `when.card_id` must reference an existing
      card_spec in cards/.
  (3) field+value reachability — the (field, value) triple must be producible:
      - The card_spec's outputs.summary_fields list must include `field`.
      - OR (legacy/transition) the card_spec's interpretation_hints[].call values
        must include `value` when field == "interpretation_call".
      - ENFORCED (2026-08-15): if a rule COMPARES a field against a scalar operand
        (equals/in), the emitting card MUST declare outputs.summary_fields_vocabulary
        for that field — otherwise it is a hard ERROR (an enum/type drift would
        silently turn the rule into a dead branch). Bool operands (`equals: 'true'`)
        are matched against string vocab ('true'/'false') via _values_equal, which
        mirrors the runtime engine's bool<->string coercion. Rules with no equality/
        membership operand (threshold/exists predicates) still only WARN.

Killer-message hygiene check:
  (4) Any rule emitting a `killer` signal must carry a non-empty `killer_message`
      (already enforced by the schema, double-checked here for clarity).

Usage:
  # CLI: validate one rules file against a cards directory
  python validate_interpretation_rules.py \\
      --rules target-contracts/interpretation-rules/intracellular-intrinsic.rules.yaml \\
      --cards target-contracts/cards/

  # As a library (compose-dashboard's pre-invocation lint OR CI check):
  from validate_interpretation_rules import validate_rules_file, ValidationReport
  report = validate_rules_file(rules_path, cards_dir)
  if not report.ok:
      for err in report.errors:
          print(err)

Exit codes:
  0 = clean (no errors; warnings ok)
  1 = errors (rule rot, schema violations, missing cards)
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Optional

import yaml
from jsonschema import Draft202012Validator
import json


SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "interpretation_rules.schema.json"


@dataclass
class ValidationReport:
    """Result of validating one rules file. errors block CI; warnings are advisory."""
    rules_file: Path
    errors: list[str] = dc_field(default_factory=list)
    warnings: list[str] = dc_field(default_factory=list)
    rules_checked: int = 0

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


def _load_yaml(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f)


def _build_card_index(cards_dir: Path) -> dict[str, dict]:
    """Load every *.card.yaml in cards_dir, index by card_id. Reused across rules."""
    idx = {}
    for card_path in sorted(cards_dir.rglob("*.card.yaml")):   # recursive — parity with validate_cards.py (C2)
        try:
            spec = _load_yaml(card_path)
        except Exception as e:
            # Caller surfaces this — return the loadable subset, skip the broken one.
            continue
        card_id = spec.get("card_id")
        if card_id:
            idx[card_id] = spec
    return idx


def _values_equal(producible, operand) -> bool:
    """Does a card-producible vocabulary value satisfy a rule's equals/in operand?

    Mirrors the runtime engine's skills/_skills_common._rule_values_equal EXACTLY,
    so the validator's reachability check matches what actually fires: tolerant ONLY
    of the bool-vs-string mismatch between a reader's native value and the rule YAML's
    string operand (`equals: 'true'`). `producible` is a declared vocab entry (schema
    forces these to be strings); `operand` is the rule's equals/in value (a YAML string
    OR a bare bool). Everything else stays STRICT — string-vs-string is CASE-SENSITIVE.
    """
    if producible == operand:
        return True

    def _bool_as_str(b: bool) -> str:
        return "true" if b else "false"

    if isinstance(producible, bool) and isinstance(operand, str):
        return _bool_as_str(producible) == operand.strip().lower()
    if isinstance(operand, bool) and isinstance(producible, str):
        return producible.strip().lower() == _bool_as_str(operand)
    return False


def _producible_values_for_field(card_spec: dict, field_name: str) -> Optional[set[str]]:
    """Return the set of values a card can emit for `field_name`, or None if the
    field's value vocabulary isn't declared in the card_spec.

    Sources (in order of preference):
      1. outputs.summary_fields_vocabulary[field_name] — future strict declaration
         (not in today's schema; reserved for post-refactor).
      2. interpretation_hints[].call (legacy) — only meaningful when field is
         "interpretation_call"; reads the call strings the card emits.
      3. None — the field's value vocab isn't declared anywhere validatable.

    Returns None means "can't check value reachability" → WARNING, not ERROR.
    """
    # Future: explicit value vocabulary
    vocab = (card_spec.get("outputs", {}) or {}).get("summary_fields_vocabulary", {})
    if isinstance(vocab, dict) and field_name in vocab:
        return set(vocab[field_name])

    # Legacy: interpretation_hints[].call only meaningful for interpretation_call lookups
    if field_name == "interpretation_call":
        hints = card_spec.get("interpretation_hints", []) or []
        calls = {h.get("call") for h in hints if isinstance(h, dict) and h.get("call")}
        if calls:
            return calls

    return None


def _summary_field_names(card_spec: dict) -> set[str]:
    """Extract field name strings from summary_fields, tolerating both the
    legacy bare-string form and the arch-A2 object form
    ({name, lens_conditional_on?, description?}). W3d fix (2026-07-09):
    parallel to _summary_field_names in validate_cards.py — needed here so
    rules targeting lens-conditional object-form fields (e.g., adc_grade
    declared as `- name: adc_grade`) validate correctly.
    """
    raw = (card_spec.get("outputs", {}) or {}).get("summary_fields", [])
    names: set[str] = set()
    for entry in raw:
        if isinstance(entry, str):
            names.add(entry)
        elif isinstance(entry, dict) and "name" in entry:
            names.add(entry["name"])
    return names


def _check_field_declared(card_spec: dict, field_name: str) -> bool:
    """Is `field_name` in the card's outputs.summary_fields? Also accept the legacy
    pseudo-field "interpretation_call" which doesn't appear in summary_fields but
    is emitted by the orchestrator alongside the card output."""
    if field_name == "interpretation_call":
        # Legacy field; always reachable from any card that emits interpretation_hints
        hints = card_spec.get("interpretation_hints", []) or []
        return len(hints) > 0
    return field_name in _summary_field_names(card_spec)


def validate_rules_file(rules_path: Path, cards_dir: Path) -> ValidationReport:
    """Validate a single rules file against a directory of card_specs.

    Returns ValidationReport with errors (rule rot / schema violations) and
    advisory warnings (unverifiable value vocabularies during transition).
    """
    report = ValidationReport(rules_file=rules_path)

    # === Check 1: structural validation against the rules schema ===
    try:
        schema = json.loads(SCHEMA_PATH.read_text())
    except Exception as e:
        report.errors.append(f"could not load rules schema at {SCHEMA_PATH}: {e}")
        return report

    try:
        rules_doc = _load_yaml(rules_path)
    except Exception as e:
        report.errors.append(f"could not parse {rules_path}: {e}")
        return report

    validator = Draft202012Validator(schema)
    for schema_err in sorted(validator.iter_errors(rules_doc), key=lambda e: list(e.absolute_path)):
        path = "/".join(str(p) for p in schema_err.absolute_path) or "<root>"
        report.errors.append(f"[schema] {path}: {schema_err.message}")
    if report.errors:
        return report

    # === Check 2+3: per-rule reachability against the card index ===
    card_idx = _build_card_index(cards_dir)
    rules = rules_doc.get("rules", []) or []
    report.rules_checked = len(rules)

    for rule in rules:
        rule_id = rule.get("rule_id", "<no-id>")
        when = rule.get("when", {}) or {}
        card_id = when.get("card_id")
        field_name = when.get("field")
        equals = when.get("equals")
        in_list = when.get("in") or []
        in_record = when.get("in_record")
        values = [equals] if equals is not None else list(in_list)
        tier = rule.get("tier")

        if not card_id:
            report.errors.append(f"[{rule_id}] when.card_id missing")
            continue

        # Subtype-tier discipline (2026-07-17): a rule tagged tier: subtype MUST
        # declare subgroup_metadata_declared (schema promises validator
        # enforcement; this is that enforcement). Its when: must use in_record —
        # a subtype rule matches per-subgroup records, not a scalar field — and
        # that in_record MUST pin subgroup_n_floor_met: true so an underpowered
        # stratum is INADMISSIBLE by construction (the F4/admissibility guard).
        if tier == "subtype":
            if not rule.get("subgroup_metadata_declared"):
                report.errors.append(
                    f"[{rule_id}] tier: subtype but no subgroup_metadata_declared "
                    f"block (required for subtype-tier rules)."
                )
            if in_record is None:
                report.errors.append(
                    f"[{rule_id}] tier: subtype must match per-subgroup records via "
                    f"when.in_record (got equals/in on a scalar field instead)."
                )
            elif in_record.get("subgroup_n_floor_met") is not True:
                report.errors.append(
                    f"[{rule_id}] tier: subtype in_record must pin "
                    f"subgroup_n_floor_met: true — otherwise an underpowered stratum "
                    f"could fire a verdict-affecting rule (admissibility violation)."
                )

        # Check 2: card_id reachable?
        if card_id not in card_idx:
            report.errors.append(
                f"[{rule_id}] references card_id={card_id!r} but no card_spec at "
                f"{cards_dir}/{card_id}.card.yaml"
            )
            continue

        card_spec = card_idx[card_id]

        # Check 3a: field declared in summary_fields (or legacy interpretation_call)?
        if not _check_field_declared(card_spec, field_name):
            report.errors.append(
                f"[{rule_id}] references field={field_name!r} on card={card_id!r} "
                f"but card's outputs.summary_fields does not include it. "
                f"Card emits: {(card_spec.get('outputs',{}) or {}).get('summary_fields',[])}"
            )
            continue

        # Check 3b: each value producible from the card?
        # in_record rules match RECORDS in a list-typed field (per_subgroup_metrics),
        # not a scalar value vocabulary — the reachability check (flat
        # summary_fields_vocabulary) doesn't apply. Verify the matched keys exist
        # in the field's summary_fields_record_schemas instead.
        if in_record is not None:
            record_schemas = (card_spec.get("outputs", {}) or {}).get(
                "summary_fields_record_schemas", {}) or {}
            rec_schema = record_schemas.get(field_name)
            if rec_schema is None:
                report.errors.append(
                    f"[{rule_id}] in_record on field={field_name!r} but card={card_id!r} "
                    f"declares no summary_fields_record_schemas.{field_name} record shape."
                )
            else:
                for key in in_record:
                    if key not in rec_schema:
                        report.errors.append(
                            f"[{rule_id}] in_record key={key!r} not in card's "
                            f"{field_name} record schema. Declared keys: {sorted(rec_schema)}"
                        )
        else:
            producible = _producible_values_for_field(card_spec, field_name)
            if producible is None:
                if values:
                    # HARDENING (2026-08-15): a rule that COMPARES a field against a
                    # scalar operand (equals/in) REQUIRES the emitting card to declare
                    # outputs.summary_fields_vocabulary.<field> — otherwise an enum/type
                    # drift (e.g. surface_confirmation_class renamed under the rule, or a
                    # bool field whose spelling drifts) silently turns the rule into a dead
                    # branch. Previously a warning; now a hard error so the card↔rule
                    # contract is CI-ENFORCED, not merely advisory. To resolve, declare the
                    # field's value vocabulary on the card (strings; bool fields as
                    # 'true'/'false' — the engine + _values_equal coerce native bools).
                    report.errors.append(
                        f"[{rule_id}] compares field={field_name!r} on card={card_id!r} "
                        f"against {values!r} (equals/in) but the card declares no "
                        f"outputs.summary_fields_vocabulary.{field_name} — value reachability "
                        f"cannot be verified. Declare the field's value vocabulary so enum/type "
                        f"drift fails CI."
                    )
                else:
                    # No equality/membership operand to check (e.g. a threshold/exists
                    # predicate); vocab is not required — keep advisory.
                    report.warnings.append(
                        f"[{rule_id}] cannot verify value reachability for field={field_name!r} "
                        f"on card={card_id!r} — card_spec declares no value vocabulary. "
                        f"After card refactors land, add outputs.summary_fields_vocabulary to enforce."
                    )
            else:
                for v in values:
                    if not any(_values_equal(p, v) for p in producible):
                        report.errors.append(
                            f"[{rule_id}] value={v!r} for field={field_name!r} on "
                            f"card={card_id!r} is NOT producible. "
                            f"Producible values: {sorted(producible)}"
                        )

        # Check 4: killer messages required for killer signals
        signals = rule.get("signals", {}) or {}
        emits_killer = any(s == "killer" for s in signals.values())
        if emits_killer and not rule.get("killer_message"):
            report.errors.append(
                f"[{rule_id}] emits a killer signal but has no killer_message. "
                f"Required by schema; double-checked here."
            )

    return report


def _print_report(report: ValidationReport, verbose: bool = False) -> None:
    status = "✓" if report.ok else "✗"
    print(f"{status} {report.rules_file.name}: {report.rules_checked} rules, "
          f"{len(report.errors)} errors, {len(report.warnings)} warnings")
    for err in report.errors:
        print(f"  ERROR: {err}")
    if verbose or report.errors:
        for warn in report.warnings:
            print(f"  WARN:  {warn}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Tier-2 interpretation-rules files.")
    parser.add_argument("--rules", required=True, type=Path,
                         help="Path to a *.rules.yaml file OR a directory of rules files.")
    parser.add_argument("--cards", required=True, type=Path,
                         help="Path to target-contracts/cards/ (directory of *.card.yaml).")
    parser.add_argument("-v", "--verbose", action="store_true",
                         help="Show warnings even when no errors.")
    args = parser.parse_args(argv)

    rules_path = args.rules
    cards_dir = args.cards

    if not cards_dir.is_dir():
        print(f"ERROR: --cards must be a directory, got {cards_dir}", file=sys.stderr)
        return 1

    if rules_path.is_dir():
        rules_files = sorted(rules_path.glob("*.rules.yaml"))
    else:
        rules_files = [rules_path]

    if not rules_files:
        print(f"ERROR: no *.rules.yaml found at {rules_path}", file=sys.stderr)
        return 1

    any_errors = False
    for rf in rules_files:
        report = validate_rules_file(rf, cards_dir)
        _print_report(report, verbose=args.verbose)
        if not report.ok:
            any_errors = True

    return 1 if any_errors else 0


if __name__ == "__main__":
    sys.exit(main())
