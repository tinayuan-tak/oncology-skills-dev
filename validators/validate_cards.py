#!/usr/bin/env python3
"""
validate_cards.py — iter-1 card_spec validator.

Two layers of validation:
  (1) Structural — every card_spec YAML must validate against schemas/card.schema.json.
  (2) Cross-reference — checks JSON Schema can't perform:
      (a) Every THRESHOLD.<name> in applies_when / interpretation_hints.if / warning_predicates.if
          must exist in the card's thresholds: block.
      (b) Every predicate is shallow-checked for balanced parens and recognized operators.
          (Full CEL-subset grammar validation is iter-2 when the CEL library lands.)

Usage:
  # CLI: validate all card_specs in a directory
  python validate_cards.py target-contracts/cards/

  # CLI: validate a single card_spec
  python validate_cards.py target-contracts/cards/expression-tumor-vs-adjacent.card.yaml

  # As a library (compose-dashboard's pre-invocation lint):
  from validate_cards import validate_card_file, ValidationReport
  report = validate_card_file('target-contracts/cards/foo.card.yaml')
  if not report.ok:
      for err in report.errors:
          print(err)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml
from jsonschema import Draft202012Validator


SCHEMA_PATH = Path(__file__).resolve().parent.parent / 'schemas' / 'card.schema.json'

# Recognized CEL-subset operators and reserved tokens (B1 § compose-dashboard subsection 2)
RECOGNIZED_OPERATORS = {'==', '!=', '>=', '<=', '>', '<', '&&', '||', '!', 'in'}
# Predicate-allowed top-level identifiers (the context object's roots + summary fields)
RECOGNIZED_CONTEXT_ROOTS = {'target', 'indication', 'subgroup_spec', 'release_pin', 'data_mode'}


@dataclass
class ValidationReport:
    card_path: str
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.ok = False
        self.errors.append(msg)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


def _load_schema() -> dict:
    with SCHEMA_PATH.open() as f:
        return json.load(f)


def _structural_check(spec: dict, report: ValidationReport, schema: dict) -> None:
    """Layer 1: JSON Schema validation against card.schema.json."""
    validator = Draft202012Validator(schema)
    for err in validator.iter_errors(spec):
        path = '.'.join(str(p) for p in err.absolute_path) or '<root>'
        report.add_error(f'STRUCTURAL [{path}]: {err.message}')


def _threshold_ref_check(spec: dict, report: ValidationReport) -> None:
    """Layer 2a: every THRESHOLD.<name> reference must exist in thresholds: block."""
    declared = set((spec.get('thresholds') or {}).keys())
    referenced: set[str] = set()

    def scan_predicate(pred: str, where: str) -> None:
        for match in re.finditer(r'THRESHOLD\.([a-z_][a-z0-9_]*)', pred):
            name = match.group(1)
            referenced.add(name)
            if name not in declared:
                report.add_error(
                    f'THRESHOLD_REF [{where}]: predicate references undeclared threshold '
                    f'`THRESHOLD.{name}`. Declared thresholds: {sorted(declared) or "(none)"}.'
                )

    for i, pred in enumerate(spec.get('applies_when', [])):
        scan_predicate(pred, f'applies_when[{i}]')
    for i, hint in enumerate(spec.get('interpretation_hints', [])):
        scan_predicate(hint.get('if', ''), f'interpretation_hints[{i}].if')
    for i, wp in enumerate(spec.get('warning_predicates', []) or []):
        scan_predicate(wp.get('if', ''), f'warning_predicates[{i}].if')

    # Inverse check: declared thresholds that no predicate references (warning, not error)
    unused = declared - referenced
    if unused:
        report.add_warning(
            f'THRESHOLD_UNUSED: thresholds {sorted(unused)} declared but never referenced '
            f'by any predicate. Remove from thresholds: block or use them.'
        )


def _shallow_predicate_check(spec: dict, report: ValidationReport) -> None:
    """Layer 2b: predicates have balanced parens and only recognized operators.

    This is a shallow lint, not a full CEL parser. Catches obvious malformations:
      - unbalanced ( and )
      - unknown logical operators (and / or / not — common Python-isms that aren't valid CEL)
      - empty predicates (already caught by minLength but reinforced here)
    """

    def lint_predicate(pred: str, where: str) -> None:
        if not pred.strip():
            report.add_error(f'PREDICATE [{where}]: empty predicate.')
            return
        # Balanced parens
        depth = 0
        for c in pred:
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
                if depth < 0:
                    report.add_error(f'PREDICATE [{where}]: unbalanced parens (close before open).')
                    return
        if depth != 0:
            report.add_error(f'PREDICATE [{where}]: unbalanced parens (depth {depth} at end).')
        # Python-isms that aren't valid CEL operators
        for pattern, display, suggested in (
            (r'\band\b', 'and', '&&'),
            (r'\bor\b', 'or', '||'),
            (r'\bnot\s', 'not', '!'),
        ):
            if re.search(pattern, pred):
                report.add_error(
                    f'PREDICATE [{where}]: uses Python-style operator `{display}`; '
                    f'CEL-subset requires `{suggested}` instead.'
                )

    for i, pred in enumerate(spec.get('applies_when', [])):
        lint_predicate(pred, f'applies_when[{i}]')
    for i, hint in enumerate(spec.get('interpretation_hints', [])):
        lint_predicate(hint.get('if', ''), f'interpretation_hints[{i}].if')
    for i, wp in enumerate(spec.get('warning_predicates', []) or []):
        lint_predicate(wp.get('if', ''), f'warning_predicates[{i}].if')


def _summary_field_names(spec: dict) -> set[str]:
    """Extract field name strings from summary_fields, tolerating both the
    legacy bare-string form and the arch-A2 object form
    ({name, lens_conditional_on?, description?}). Introduced 2026-07-08 with
    the lens-conditional field split.
    """
    raw = spec.get('outputs', {}).get('summary_fields', [])
    names: set[str] = set()
    for entry in raw:
        if isinstance(entry, str):
            names.add(entry)
        elif isinstance(entry, dict) and 'name' in entry:
            names.add(entry['name'])
    return names


def _composed_card_semantics_check(spec: dict, report: ValidationReport) -> None:
    """Layer 2d (arch A1 enforcement, 2026-07-08): required_inputs may be
    empty ONLY when the card is COMPOSED (declares derived_from upstream
    card_ids). Leaf cards must have at least one required_inputs entry.

    W3d fix (2026-07-09): removed the reciprocal "declares BOTH
    required_inputs AND derived_from" warning. Empirically, hybrid cards
    that declare BOTH are the correct pattern for cards needing target-
    identity resolution (via derived_from: target-identity-summary) AND a
    raw product pull (via required_inputs). Examples:
      - crispr-rnai-dependency-concordance (pre-existing)
      - signaling-network-mechanism (new)
      - surface-abundance-density (new)
    The prior warning fired on all three, breaking --strict-warnings CI.
    Only the empty-neither error remains (the A1 semantic invariant).
    """
    required_inputs = spec.get('required_inputs', [])
    derived_from = spec.get('derived_from', [])
    if not required_inputs and not derived_from:
        report.add_error(
            'COMPOSED_CARD [required_inputs]: empty required_inputs is only '
            'valid when derived_from is declared (composed-card semantics). '
            'Leaf cards must reference at least one product_id.'
        )


def _interpretation_summary_field_check(spec: dict, report: ValidationReport) -> None:
    """Layer 2c (best-effort): each interpretation_hints.if SHOULD reference at least one
    declared summary_field. This catches the failure mode where an interpretation rule
    references a field the card doesn't actually emit. Best-effort because a predicate
    may reference helper functions or thresholds only.
    """
    summary_fields = _summary_field_names(spec)
    for i, hint in enumerate(spec.get('interpretation_hints', [])):
        pred = hint.get('if', '')
        referenced_idents = set(re.findall(r'\b([a-z_][a-z0-9_]*)\b', pred))
        # Exclude reserved tokens + literals + threshold-reference (THRESHOLD.foo)
        reserved = {'true', 'false', 'null', 'and', 'or', 'not', 'in', 'abs', 'THRESHOLD'}
        candidate_fields = referenced_idents - reserved
        if not (candidate_fields & summary_fields):
            # No summary field referenced — likely OK only if predicate references THRESHOLD only
            if 'THRESHOLD.' not in pred:
                report.add_warning(
                    f'INTERPRETATION [interpretation_hints[{i}].if]: references no declared '
                    f'summary_field ({sorted(summary_fields)}). Predicate: {pred!r}'
                )


def validate_card_file(path: str | Path, schema: dict | None = None) -> ValidationReport:
    """Validate a single card_spec YAML file. Returns a ValidationReport."""
    path = Path(path)
    report = ValidationReport(card_path=str(path))
    if not path.exists():
        report.add_error(f'FILE_NOT_FOUND: {path}')
        return report
    try:
        with path.open() as f:
            spec = yaml.safe_load(f)
    except yaml.YAMLError as e:
        report.add_error(f'YAML_PARSE: {e}')
        return report
    if not isinstance(spec, dict):
        report.add_error(f'YAML_SHAPE: expected mapping at top level, got {type(spec).__name__}')
        return report
    if schema is None:
        schema = _load_schema()
    _structural_check(spec, report, schema)
    if report.ok:  # only run downstream checks if structural is clean
        _threshold_ref_check(spec, report)
        _shallow_predicate_check(spec, report)
        _interpretation_summary_field_check(spec, report)
        _composed_card_semantics_check(spec, report)
    return report


def validate_directory(dir_path: str | Path) -> list[ValidationReport]:
    """Validate every *.card.yaml in a directory (recursively). Returns reports list."""
    dir_path = Path(dir_path)
    schema = _load_schema()
    reports = []
    for path in sorted(dir_path.rglob('*.card.yaml')):
        reports.append(validate_card_file(path, schema=schema))
    return reports


def _format_report(report: ValidationReport) -> str:
    lines = [f'  {report.card_path}']
    for err in report.errors:
        lines.append(f'    [ERROR]   {err}')
    for warn in report.warnings:
        lines.append(f'    [WARNING] {warn}')
    if report.ok and not report.warnings:
        lines.append(f'    [OK]')
    return '\n'.join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Validate iter-1 card_spec YAML files against card.schema.json + cross-reference rules.'
    )
    parser.add_argument(
        'path',
        help='Path to a single card_spec YAML file, or a directory containing *.card.yaml files (searched recursively).'
    )
    parser.add_argument(
        '--strict-warnings',
        action='store_true',
        help='Treat warnings as errors (CI mode).'
    )
    args = parser.parse_args(argv)
    target = Path(args.path)

    if target.is_dir():
        reports = validate_directory(target)
    else:
        reports = [validate_card_file(target)]

    print('validate_cards.py results:')
    n_ok, n_err, n_warn = 0, 0, 0
    for r in reports:
        print(_format_report(r))
        if r.ok and not r.warnings:
            n_ok += 1
        if not r.ok:
            n_err += 1
        if r.warnings:
            n_warn += 1
    print()
    print(f'Summary: {len(reports)} card_spec(s); {n_ok} clean, {n_err} with errors, {n_warn} with warnings.')

    if any(not r.ok for r in reports):
        return 1
    if args.strict_warnings and any(r.warnings for r in reports):
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
