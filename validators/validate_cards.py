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

# Grain-check (subgroup-panorama layer, 2026-07-16). A card that enumerates a
# target's evidence ACROSS molecular subgroups (declares per_subgroup_metrics or
# subgroup_stratification.status == "live") must bind a PER-SAMPLE stratified
# reader — one that can honestly recompute the metric within each stratum's
# member-set. A method whose values are baked at emit time (an aggregate) cannot;
# binding one is the "subgroup-stratified-expression trap" this check exists to
# forbid. The allowlist is the set of method `call:` names whose analysis-methods
# module ships a @subgroup_iterable read_stratified_* reader + build_*_panorama.
# When a new per-sample stratified reader lands, add its `call` here.
PER_SAMPLE_STRATIFIABLE_CALLS = {
    'gdc-somatic-hotspot',   # methods/gdc_somatic_hotspot: read_stratified_mutation_frequency + build_mutation_frequency_panorama
    'depmap-chronos',        # methods/depmap_chronos: read_stratified_dependency + build_dependency_panorama
}

# The list-typed summary field names that signal a card emits a per-subgroup
# panorama. Both spellings are in use: `per_subgroup_metrics` (molecular-subgroup
# cards) and `per_stratum_metrics` (the RWD line-of-therapy card). Either implies
# a per-sample stratified reader is required.
PANORAMA_RECORD_FIELDS = {'per_subgroup_metrics', 'per_stratum_metrics'}

# Figure-emission check (viz-coverage, 2026-07-20; re-pointed at the live registry).
# A card that DECLARES a `figure:`/`figures:` must have a live-path FIGURE EMITTER —
# an entry in claude-oncology-skills compose-dashboard `_figure_emitters.py`
# `CARD_FIGURE_EMITTERS` (card_id → emit fn that draws from the card summary). The
# render-evidence-package skill only embeds a pre-existing figure PATH; the emitter
# registry is what actually produces that path in the live compose path. A card
# promising a figure with no registered emitter is a DECLARED-NOT-EMITTED gap: the
# rendered evidence package shows a broken/absent figure reference.
#
# The authoritative source is the registry itself — we PARSE its card_id keys from
# the skills repo (graceful-skip if the sibling repo is absent, e.g. isolated CI).
# This replaces an earlier method-`call:`-keyed heuristic: the live producer is the
# registry, not the analysis-methods emit_* (which serve the batch/precompute path).
_SKILLS_REPO = Path(
    "/home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills")
_FIGURE_EMITTERS_PATH = (_SKILLS_REPO / "skills" / "compose-dashboard" / "scripts"
                         / "_figure_emitters.py")


def _registered_figure_emitters() -> Optional[set[str]]:
    """Parse the card_id keys registered in CARD_FIGURE_EMITTERS. Returns None if the
    skills repo / registry file is unreachable (→ the check graceful-skips, never a
    false failure in an isolated checkout)."""
    try:
        txt = _FIGURE_EMITTERS_PATH.read_text()
    except OSError:
        return None
    # registry entries are  "card-id": _emit_fn,
    return set(re.findall(r'"([a-z0-9-]+)"\s*:\s*_emit', txt))


# KNOWN figure debt (viz-coverage audit 2026-07-20): cards that declare a figure but
# have NO emitter registered in CARD_FIGURE_EMITTERS yet. Enumerated so the build
# stays green while the debt is worked down — but a NEW card cannot silently join
# this list (it would fail the check), and each entry is REMOVED as its emitter is
# added to the registry. The shrinking, build-enforced viz-debt queue. Keyed by
# card_id. (Cards whose backing method is a stub / composed / not-yet-built are
# ALSO here — they can't emit until their data lands, but they still declare a
# figure, so they're tracked debt not silent gaps.)
KNOWN_FIGURE_DEBT = {
    # SAFETY tier — CLEARED 2026-07-20: gnomad-lof-constraint + normal-tissue-liability
    # emitters registered in CARD_FIGURE_EMITTERS (they now pass the check, not waived).
    # expression / protein:
    'protein-abundance-celline', 'protein-presence-cptac',
    # driver / differentiation / mechanism:
    'mutation-hotspot-frequency', 'co-mutation-and-mutual-exclusivity',
    'signaling-network-mechanism',
    # dependency-hardening + subgroup panels:
    'paralog-buffering', 'subgroup-stratified-mutation-frequency',
    'subgroup-stratified-dependency', 'subgroup-stratified-expression',
    # surface tier + shed:
    'shed-ectodomain-liability', 'surface-topology-and-ptm',
    'surfaceome-family-classification', 'surfaceome-cohort-ranking',
    'structure-features-static',
    # data-blocked (no runnable method yet, but the card declares a figure):
    'antigen-prevalence', 'clinical-precedent', 'lineage-restriction-evidence',
    'protein-surface-evidence', 'surface-abundance-density', 'adc-tce-modality-fit',
    'fusion-rearrangement-landscape', 'rwd-stratified-expression',
    'target-identity-summary',
}


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


def _method_calls(spec: dict) -> list[str]:
    """The `call:` names declared in the card's methods: block."""
    return [m.get('call') for m in spec.get('methods', []) if isinstance(m, dict) and m.get('call')]


def _grain_and_tier_check(spec: dict, report: ValidationReport) -> None:
    """Layer 2e (subgroup-panorama layer, 2026-07-16) — GRAIN + TIER enforcement.

    Two invariants that keep the descriptive subgroup panorama honest:

    GRAIN. A card that enumerates a target across molecular subgroups — i.e. it
      declares `per_subgroup_metrics` (in summary_fields OR
      summary_fields_record_schemas) OR sets subgroup_stratification.status ==
      "live" — MUST bind a per-sample stratified reader (a `call:` in
      PER_SAMPLE_STRATIFIABLE_CALLS). Binding an aggregate-substrate method whose
      values are baked at emit time is the trap this check forbids: the card
      would CLAIM per-stratum recomputation its substrate cannot honestly do.

    TIER. A `tier: target` card is scope-invariant (its evidence is a property of
      the gene/protein, identical across every patient subpopulation). It may NOT
      carry a subgroup_stratification block or declare per_subgroup_metrics —
      stratifying it is noise (filter 1 of the two-filter card-selection rule).
    """
    tier = spec.get('tier')
    strat = spec.get('subgroup_stratification') or {}
    strat_status = strat.get('status')
    summary_names = _summary_field_names(spec)
    record_schemas = spec.get('outputs', {}).get('summary_fields_record_schemas', {}) or {}
    panorama_fields = (summary_names | set(record_schemas)) & PANORAMA_RECORD_FIELDS
    declares_panorama = bool(panorama_fields)
    calls = _method_calls(spec)
    has_per_sample_reader = any(c in PER_SAMPLE_STRATIFIABLE_CALLS for c in calls)

    # TIER invariant: target-tier cards never stratify.
    if tier == 'target':
        if strat:
            report.add_error(
                'GRAIN_TIER [subgroup_stratification]: card is `tier: target` '
                '(scope-invariant target evidence) but declares a '
                'subgroup_stratification block. Target-tier cards never stratify '
                '(two-filter rule, filter 1). Remove the block or change the tier.'
            )
        if declares_panorama:
            report.add_error(
                f'GRAIN_TIER [outputs]: card is `tier: target` but declares '
                f'{sorted(panorama_fields)}. Target-tier evidence does not vary by '
                f'subgroup; per-subgroup enumeration is noise on a target-tier card.'
            )

    # GRAIN invariant: a live/panorama card must bind a per-sample stratified reader.
    claims_live = (strat_status == 'live') or declares_panorama
    if claims_live and not has_per_sample_reader:
        report.add_error(
            f'GRAIN [methods]: card declares a subgroup panorama '
            f'(status={strat_status!r}, panorama field(s)={sorted(panorama_fields)}) '
            f'but its method call(s) {calls} are NOT per-sample stratifiable. A '
            f'panorama must recompute the metric WITHIN each stratum member-set; '
            f'an emit-time aggregate cannot. Bind one of '
            f'{sorted(PER_SAMPLE_STRATIFIABLE_CALLS)}, or set '
            f'subgroup_stratification.status: blocked_needs_per_sample_reader and '
            f'drop the panorama field until a per-sample reader ships.'
        )

    # A blocked card must NOT still be declaring the panorama field (the trap).
    if strat_status == 'blocked_needs_per_sample_reader' and declares_panorama:
        report.add_error(
            f'GRAIN [outputs]: card is tagged '
            f'subgroup_stratification.status: blocked_needs_per_sample_reader but '
            f'still declares {sorted(panorama_fields)}. A blocked card cannot emit '
            f'per-subgroup records — drop the field until a per-sample reader is bound.'
        )


def _figure_emission_check(spec: dict, report: ValidationReport) -> None:
    """Viz-coverage (2026-07-20): a card declaring a figure must be backed by a
    method that emits it. render-evidence-package only embeds a pre-existing figure
    path — it does not generate figures from plot_data — so a declared figure whose
    method emits none renders as a broken/absent reference.

    ERROR when: the card declares `figure:`/`figures:` AND its method `call:` is a
    real (non-exempt) runnable method that is NOT a known figure-emitter AND the
    card is NOT already on the KNOWN_FIGURE_DEBT waiver. This blocks a NEW card from
    silently joining the declared-not-emitted class while letting the enumerated
    debt be worked down. WARNING (not error) for cards ON the waiver — surfaced as
    tracked debt on every run.
    """
    outputs = spec.get('outputs') or {}
    declares_figure = bool(outputs.get('figure') or outputs.get('figures'))
    if not declares_figure:
        return
    card_id = spec.get('card_id', '<unknown>')
    emitters = _registered_figure_emitters()
    if emitters is None:
        return  # skills repo unreachable — graceful skip, never a false failure
    # a card with a registered live-path emitter is complete.
    if card_id in emitters:
        return
    if card_id in KNOWN_FIGURE_DEBT:
        report.add_warning(
            f'FIGURE_DEBT: card `{card_id}` declares a figure but has NO emitter in '
            f'compose-dashboard CARD_FIGURE_EMITTERS (tracked viz-debt, audit 2026-07-20). '
            f'Add a `_emit_{card_id.replace("-", "_")}` to _figure_emitters.py + register it '
            f'to clear (then drop from KNOWN_FIGURE_DEBT).'
        )
        return
    report.add_error(
        f'FIGURE_DECLARED_NOT_EMITTED: card `{card_id}` declares a figure but has no '
        f'emitter registered in compose-dashboard CARD_FIGURE_EMITTERS and is not on the '
        f'KNOWN_FIGURE_DEBT waiver. Register a figure emitter for it, or add it to '
        f'KNOWN_FIGURE_DEBT with a tracked-debt rationale. New cards must not silently '
        f'declare a figure nothing produces.'
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
        _grain_and_tier_check(spec, report)
        _figure_emission_check(spec, report)
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
