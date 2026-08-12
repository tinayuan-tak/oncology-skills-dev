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
  python validate_cards.py target-contracts/cards/tumor-rna-vs-adjacent.card.yaml

  # As a library (compose-dashboard's pre-invocation lint):
  from validate_cards import validate_card_file, ValidationReport
  report = validate_card_file('target-contracts/cards/foo.card.yaml')
  if not report.ok:
      for err in report.errors:
          print(err)
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

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
    'tcga-gtex-expression-distribution',  # methods/tcga_gtex_expression_distribution: read_tumor_expression_subtype_landscape
                                          # recomputes the per-sample distribution WITHIN each stratum member-set
                                          # (UUID→barcode→stratum bridge), NOT an emit-time aggregate — AM #82.
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
_SKILLS_REPO = Path(os.environ.get(
    "CLAUDE_ONCOLOGY_SKILLS_ROOT",
    "/home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills"))
_FIGURE_EMITTERS_PATH = (_SKILLS_REPO / "skills" / "compose-dashboard" / "scripts"
                         / "_figure_emitters.py")

# Measurement-type check (DATA_TO_SKILL_CONTRACT.md, 2026-07-21). A card's identity is
# (measurement_type × entity_grain) — Rule 1. During migration the field is OPTIONAL (existing
# cards are un-migrated), so a card WITHOUT measurement_type gets a WARNING (tracked migration debt),
# not an error. A card WITH one must name a type registered in vocabularies/measurement_types.yaml
# (else ERROR — a typo'd/unregistered type is a real defect). This is the machine-check that makes
# the pull-routing registry honest: every declared type resolves to a governed vocabulary entry.
_MEASUREMENT_TYPES_PATH = (Path(__file__).resolve().parent.parent / 'vocabularies'
                           / 'measurement_types.yaml')
_RULES_DIR = Path(__file__).resolve().parent.parent / 'interpretation-rules'
# The 5 modality lenses a rule's signals{} dict can carry (matches card.schema.json modality_relevance
# enum + the per-rule signal keys in interpretation-rules/*.rules.yaml).
_MODALITY_SIGNAL_KEYS = frozenset({'small_molecule', 'degrader', 'adc', 'bite_tce', 'antibody'})


@functools.lru_cache(maxsize=1)
def _card_modality_signals() -> Optional[dict[str, set[str]]]:
    """Build {card_id -> set of modality lenses its rules emit a signal for} across ALL
    interpretation-rules/*.rules.yaml. A rule contributes to its `when.card_id` the modality keys
    present in its `signals:` dict (small_molecule/degrader/adc/bite_tce/antibody). Cards with NO
    rule are absent from the map (distinguished from cards-with-rules-but-no-modality-signal).

    Returns None if the rules dir is absent (graceful-skip). This is the substrate for the
    'declared-relevant-but-mute' governance check: a card that declares a modality lens in
    `modality_relevance` but whose rules never emit that lens's signal cannot actually route evidence
    to that modality gate (the P4 bug class — the real router is the per-rule signals{} dict, not the
    declaration)."""
    if not _RULES_DIR.exists():
        return None
    out: dict[str, set[str]] = {}
    for rules_file in sorted(_RULES_DIR.glob('*.rules.yaml')):
        try:
            with rules_file.open() as f:
                doc = yaml.safe_load(f) or {}
        except yaml.YAMLError:
            continue
        for rule in (doc.get('rules') or []):
            if not isinstance(rule, dict):
                continue
            when = rule.get('when') or {}
            card_id = when.get('card_id') if isinstance(when, dict) else None
            if not card_id:
                continue
            signals = rule.get('signals') or {}
            emitted = {k for k in signals if k in _MODALITY_SIGNAL_KEYS} if isinstance(signals, dict) else set()
            out.setdefault(card_id, set()).update(emitted)
    return out


@functools.lru_cache(maxsize=1)
def _registered_measurement_types() -> Optional[set[str]]:
    """The set of measurement_type keys declared in vocabularies/measurement_types.yaml. Returns
    None if the vocab file is absent (→ the check graceful-skips; the vocab is net-new and a repo
    checkout mid-migration may not have it yet)."""
    if not _MEASUREMENT_TYPES_PATH.exists():
        return None
    try:
        with _MEASUREMENT_TYPES_PATH.open() as f:
            doc = yaml.safe_load(f) or {}
    except yaml.YAMLError:
        return None
    types = doc.get('measurement_types')
    if not isinstance(types, dict):
        return None
    return set(types.keys())


@functools.lru_cache(maxsize=1)
def _modality_relevant_types() -> Optional[set[str]]:
    """The set of measurement_type keys whose vocab entry declares a `modality_relevance:` key —
    i.e. the types that ROUTE to a modality-fit gate (P4). Returns None if the vocab is absent
    (graceful-skip). Anchoring the 'modality-relevant' definition to the vocab (not a hardcoded list)
    makes the check self-maintaining: stamping modality_relevance on a type in the vocab automatically
    begins requiring the field on that type's cards."""
    if not _MEASUREMENT_TYPES_PATH.exists():
        return None
    try:
        with _MEASUREMENT_TYPES_PATH.open() as f:
            doc = yaml.safe_load(f) or {}
    except yaml.YAMLError:
        return None
    types = doc.get('measurement_types')
    if not isinstance(types, dict):
        return None
    return {name for name, entry in types.items()
            if isinstance(entry, dict) and entry.get('modality_relevance')}


@functools.lru_cache(maxsize=1)
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
    # expression / protein: BOTH CLEARED 2026-07-21 (Slice 7) — emitters registered in
    # CARD_FIGURE_EMITTERS, now pass the check (not waived).
    #   cellline-protein-abundance: Gygi density + lineage-strip + plotly.
    #   tumor-protein-abundance-cptac: per-cohort tumor-vs-normal DISTRIBUTION boxplot (upgraded 2026-07-22
    #     from the median dumbbell — the per-sample product cptac-protein-tumor-vs-normal-per-sample-v1
    #     now persists the per-aliquot log-ratios, so read.py's per_cohort_distribution_stats backs a
    #     true boxplot + recomputed Welch/MWU significance; emitter registered, not waived).
    # expression-extraction plan (Q1): tumor-rna-distribution CLEARED 2026-07-22 —
    # _emit_tumor_expression_distribution is registered in compose-dashboard
    # CARD_FIGURE_EMITTERS (SK #144), so the pooled card now passes the check (not waived).
    # subtyping revisit: tumor-rna-distribution-by-subtype CLEARED 2026-07-22 —
    # _emit_tumor_expression_distribution_subtype is registered in compose-dashboard
    # CARD_FIGURE_EMITTERS (SK #145, backed by AM #84's emit_subtype_svg/plotly), so the
    # subtype card now passes the check (not waived).
    # expression Q2/Q3 CLEARED 2026-07-22 — _emit_tumor_vs_normal_percentile_crossing +
    # _emit_normal_tissue_liability_gtex are registered in compose-dashboard CARD_FIGURE_EMITTERS
    # (SK #146, backed by AM #85), so both cards now pass the figure check (not waived).
    # expression Q4 CLEARED 2026-07-22 — _emit_recommended_models is registered in compose-dashboard
    # CARD_FIGURE_EMITTERS (SK #148, backed by AM #86), so the card passes the figure check (not waived).
    # expression Q5 CLEARED 2026-07-22 — _emit_rna_protein_concordance is registered in
    # compose-dashboard CARD_FIGURE_EMITTERS (SK #150, backed by AM #87), so the card passes the
    # figure check on its own (not waived).
    # expression Q5 TUMOR arm CLEARED 2026-07-22 — _emit_rna_protein_concordance_tumor is registered
    # in compose-dashboard CARD_FIGURE_EMITTERS (SK #151, backed by AM #89), so the card passes the
    # figure check on its own (not waived).
    # driver / differentiation / mechanism:
    'mutation-hotspot-frequency', 'co-mutation-and-mutual-exclusivity',
    'signaling-network-mechanism',
    # genomic alteration-class CLEARED 2026-07-22 — _emit_alteration_role is registered in
    # compose-dashboard CARD_FIGURE_EMITTERS (SK #152, backed by AM #90), so the card passes the
    # figure check on its own (not waived).
    # dependency-hardening + subgroup panels:
    'paralog-buffering', 'subgroup-stratified-mutation-frequency',
    'synthetic-lethal-partners',   # figure backfill deferred (viz-debt queue)
    'subgroup-stratified-dependency', 'subgroup-stratified-expression',
    'copy-number-stratified-dependency',   # A1a (2026-08-06) — amp-vs-neutral strip emitter deferred (viz-debt queue)
    'fusion-stratified-dependency',   # A1-fusion (2026-08-06) — fusion-vs-negative strip emitter deferred (viz-debt queue)
    'amp-expr-stratified-dependency',   # A1 amp-expr (2026-08-06) — conjoint amp+overexpr strip emitter deferred (viz-debt queue)
    'oncogenic-pathway-alteration',   # Sanchez-Vega (2026-08-10) — pathway-alteration bar emitter deferred (viz-debt queue)
    'stemness-context',   # Malta 2018 (2026-08-10) — stemness distribution emitter deferred (viz-debt queue)
    'target-development-level',   # Pharos/IDG (2026-08-10) — TDL tier bar emitter deferred (viz-debt queue)
    'cross-consortium-dependency',   # Project Score (2026-08-10) — Broad-vs-Sanger concordance emitter deferred (viz-debt queue)
    'partner-conditional-dependency',   # Track PC (2026-08-09) — partner-deficient-vs-neutral strip emitter deferred (viz-debt queue)
    'ddr-deficiency-context',   # Track PI (2026-08-09) — HRD-context strip/bar emitter deferred (viz-debt queue)
    'pathway-activity-context',   # Track PROGENy (2026-08-10) — pathway-activity bar/heatmap emitter deferred (viz-debt queue)
    'precog-prognostic-association',   # PRECOG (2026-08-10) — meta-Z prognostic strip/forest emitter deferred (viz-debt queue)
    # surface tier + shed:
    'shed-ectodomain-liability', 'surface-topology-and-ptm',
    'surfaceome-family-classification', 'surfaceome-cohort-ranking',
    'structure-features-static',
    # data-blocked (no runnable method yet, but the card declares a figure):
    'antigen-prevalence', 'clinical-precedent', 'lineage-restriction-evidence',
    'protein-surface-evidence', 'surface-abundance-density', 'adc-tce-modality-fit',
    'fusion-rearrangement-landscape', 'rwd-stratified-expression',
    'target-identity-summary',
    'modality-therapeutic-window',   # figure modality_window_tumor_vs_essential_normal declared at card
                                     # creation (2026-08-06) but emitter never registered — pre-existing
                                     # viz-debt (was failing on main before this edit); waived on the
                                     # convention here. Emitter backfill deferred to the viz-debt queue.
    # tumor-elevation-breadth CLEARED 2026-07-22: the pan-cancer by-tissue TPM distribution
    # emitter (_emit_tumor_elevation_breadth, drawing from tcga-gtex-tpm-tissue-quantiles-v1)
    # is now registered in CARD_FIGURE_EMITTERS — passes the check, not waived.
    # combo axes + immune/pMHC (added 2026-08-08): declare a figure but their emitter is not yet
    # registered in compose-dashboard _figure_emitters.py CARD_FIGURE_EMITTERS. Tracked viz-debt.
    'combo-crispr-screen',            # figure emitter not yet registered in compose-dashboard _figure_emitters.py
    'combinatorial-dependency',       # figure emitter not yet registered in compose-dashboard _figure_emitters.py
    'immune-context',                 # figure emitter not yet registered in compose-dashboard _figure_emitters.py (pre-existing)
    'pmhc-presentation',              # figure emitter not yet registered in compose-dashboard _figure_emitters.py (pre-existing)
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


def _measurement_type_check(spec: dict, report: ValidationReport) -> None:
    """DATA_TO_SKILL_CONTRACT.md Rule 1 (2026-07-21) — a card's identity is
    (measurement_type × entity_grain).

    MIGRATION-SAFE by design (the doc's 'do NOT big-bang' guardrail):
      - No measurement_type on the card → WARNING (tracked migration debt). The ~40 pre-existing
        cards are un-migrated; the field is REQUIRED only for NEW cards (the frozen identity rule),
        and social/PR review — not this validator — enforces "new card must declare it" until the
        migration completes and the field can be made hard-required.
      - measurement_type present but NOT registered in vocabularies/measurement_types.yaml → ERROR.
        A declared-but-unregistered type is a real defect (typo, or a type someone forgot to add to
        the governed vocab) — the pull resolver would never match it.
      - entity_grains present: each grain must parse as a grain token (schema already enforces the
        pattern; here we additionally forbid the empty string slipping through as a lone value).
    """
    mtype = spec.get('measurement_type')
    card_id = spec.get('card_id', '<unknown>')
    if mtype is None:
        report.add_warning(
            f'MEASUREMENT_TYPE_MISSING: card `{card_id}` does not declare a `measurement_type` '
            f'(DATA_TO_SKILL_CONTRACT Rule 1). Tracked migration debt — pre-existing cards are '
            f'un-migrated; NEW cards must declare their measurement_type + register it in '
            f'vocabularies/measurement_types.yaml.'
        )
        return
    registered = _registered_measurement_types()
    if registered is None:
        return  # vocab file absent (net-new / mid-migration checkout) — graceful skip, never false-fail
    if mtype not in registered:
        report.add_error(
            f'MEASUREMENT_TYPE_UNREGISTERED: card `{card_id}` declares measurement_type '
            f'`{mtype}` which is NOT a key in vocabularies/measurement_types.yaml. Register the '
            f'type (per the concordance test, Rule 2) or fix the name — the pull resolver matches '
            f'gates to providers by this key, so an unregistered type is invisible to every gate.'
        )


# sample_context (2026-07-21) is ORTHOGONAL to measurement, but must be CONSISTENT with the card's
# measurement_type prefix — the type already encodes cell-line-vs-tumor (cell_line_* / tumor_*), so a
# card claiming e.g. measurement_type: cell_line_rna_expression but sample_context: tumor is a
# contradiction. This maps each measurement_type prefix to its required sample_context.
_MEASUREMENT_TYPE_CONTEXT_PREFIX = {
    "cell_line_": "cell_line",
    "tumor_": "tumor",
    "normal_tissue_": "normal",
}


def _sample_context_check(spec: dict, report: ValidationReport) -> None:
    """sample_context (when present) must agree with the card's measurement_type prefix.

    The two axes are orthogonal in GENERAL, but for a given card the measurement_type already fixes
    the sample context (cell_line_rna_expression is cell-line; tumor_vs_adjacent_expression is tumor).
    A card that declares BOTH and disagrees is a real defect (the skill's per-modality grouping would
    bucket it wrong). No sample_context → nothing to check (optional field). No measurement_type, or a
    prefix not in the map → skip (can't infer the expected context)."""
    ctx = spec.get('sample_context')
    if ctx is None:
        return
    card_id = spec.get('card_id', '<unknown>')
    mtype = spec.get('measurement_type')
    if not mtype:
        return
    for prefix, expected in _MEASUREMENT_TYPE_CONTEXT_PREFIX.items():
        if mtype.startswith(prefix):
            if ctx != expected:
                report.add_error(
                    f'SAMPLE_CONTEXT_MISMATCH: card `{card_id}` declares sample_context `{ctx}` but '
                    f'its measurement_type `{mtype}` implies `{expected}` (prefix `{prefix}`). The two '
                    f'axes are orthogonal in general, but the type already fixes the sample context — '
                    f'a disagreement would mis-bucket the per-modality sub-verdict. Fix one.')
            return


def _modality_relevance_check(spec: dict, report: ValidationReport) -> None:
    """P4 (2026-07-23) — `modality_relevance` is an ADVISORY annotation of which modality-fit gates a
    card's evidence is intended to inform.

    DEMOTED TO ADVISORY (2026-08-09, modality-fit review): the original design intended this field to
    ROUTE evidence to gates (a declarative PULL), and this check ERRORed on its absence. But that pull
    mechanism was never built — `modality_relevance` has ZERO behavioral readers; the ACTUAL router is
    the per-rule `signals{}` dict (+ modality_axis_compatibility.yaml for module loading). Enforcing a
    field that changes nothing advertised a capability that does not exist. So a MISSING declaration is
    now a WARNING (documentation lint), not an ERROR — and the message no longer claims evidence is
    "stranded" (it isn't; routing works via rule signals regardless).

    'Modality-relevant' is defined by the VOCAB, not a hardcoded list: a measurement_type is
    modality-relevant iff its entry in vocabularies/measurement_types.yaml declares `modality_relevance`.
      - card's type is modality-relevant AND card omits top-level modality_relevance → WARNING (advisory).
      - card declares modality_relevance but its VALUES aren't a subset of the type's declared set →
        WARNING (the card claims a lens the type's routing doesn't list — likely drift).
    Migration-safe: no measurement_type on the card, or vocab absent → graceful skip (the
    measurement_type check already warns on the missing-type case)."""
    card_id = spec.get('card_id', '<unknown>')
    mtype = spec.get('measurement_type')
    if not mtype:
        return
    relevant = _modality_relevant_types()
    if relevant is None:
        return  # vocab absent — graceful skip
    card_mr = spec.get('modality_relevance')
    if mtype in relevant and not card_mr:
        report.add_warning(
            f'MODALITY_RELEVANCE_MISSING: card `{card_id}` has measurement_type `{mtype}`, which is '
            f'declared modality-relevant in vocabularies/measurement_types.yaml. Consider adding an '
            f'ADVISORY `modality_relevance: [...]` annotation naming the modality-fit gate(s) this '
            f'card informs. NOTE: this is documentation only — evidence routing is driven by the '
            f'per-rule signals{{}} dict, not this field, so omitting it does NOT strand the card.')
        return
    # optional consistency: card's declared lenses should be within the type's routing set
    if mtype in relevant and card_mr:
        try:
            with _MEASUREMENT_TYPES_PATH.open() as f:
                type_mr = set((yaml.safe_load(f) or {}).get('measurement_types', {})
                              .get(mtype, {}).get('modality_relevance') or [])
        except (OSError, yaml.YAMLError):
            type_mr = set()
        extra = set(card_mr) - type_mr if type_mr else set()
        if extra:
            report.add_warning(
                f'MODALITY_RELEVANCE_DRIFT: card `{card_id}` declares modality_relevance lens(es) '
                f'{sorted(extra)} not in its measurement_type `{mtype}` routing set {sorted(type_mr)}. '
                f'The card claims a modality gate the type does not route to — align the card + the '
                f'vocab entry.')

    # DECLARED-RELEVANT-BUT-MUTE (2026-08-06 — the P4-deferred governance cross-check). The field
    # modality_relevance is DECLARATION metadata; the ACTUAL router is the per-rule signals{} dict.
    # A card can therefore declare a modality lens yet have NO rule emitting that lens's signal — it
    # LOOKS wired to the modality gate but its evidence can never reach it (exactly the bug P4 fixed by
    # ADDING a rule, cf. TC#102/#103). This warns on that inconsistency. Discipline:
    #   - Only fires when the card HAS ≥1 rule (a pure-data facet with NO rules reaches gates via
    #     reports_into, not signals — flagging it would be a false positive; it is skipped).
    #   - WARNING, not ERROR: an un-ruled modality is a roadmap gap, not a contract violation. It makes
    #     the "declared but unrealised" set VISIBLE (the loop P4 left open) without touching any verdict.
    if mtype in relevant and card_mr:
        sig_map = _card_modality_signals()
        if sig_map is not None and card_id in sig_map:
            emitted = sig_map[card_id]                       # modalities this card's rules actually emit
            mute = [m for m in card_mr if m not in emitted]  # declared lenses with no signal-carrying rule
            if mute:
                report.add_warning(
                    f'MODALITY_RELEVANCE_MUTE: card `{card_id}` declares modality_relevance {sorted(card_mr)} '
                    f'but its interpretation rules emit signals only for {sorted(emitted) or "no modality"}; '
                    f'lens(es) {sorted(mute)} are DECLARED-RELEVANT-BUT-MUTE — no rule carries that '
                    f'modality\'s signal, so the card\'s evidence cannot route to that modality gate '
                    f'(the real router is the per-rule signals{{}} dict, not the declaration). Add a rule '
                    f'emitting the {sorted(mute)} signal, or drop the lens from modality_relevance.')


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
        _measurement_type_check(spec, report)
        _sample_context_check(spec, report)
        _modality_relevance_check(spec, report)
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


def validate_dashboard_required_cards(cards_dir: Path) -> list[str]:
    """Cross-check (2026-08-12): every dashboard_spec `required_cards` entry must reference a card whose
    `status` is `wired` (or OMITTED, which defaults to wired). A non-wired card
    (placeholder_not_wired / dormant_pending_data) listed in required_cards is an ERROR — it belongs in
    `placeholder_cards`. This keeps `required` meaning 'must produce' rather than 'may be silently
    not_wired' (compose-dashboard's availability_state honestly flags such cards at runtime, but the
    contract should declare them up front). Also warns if a placeholder_cards entry is actually
    status=wired (mislabel). Reads dashboards/ as a sibling of the cards dir; no-op if absent."""
    cards_dir = Path(cards_dir)
    dashboards_dir = cards_dir.parent / 'dashboards'
    if not dashboards_dir.is_dir():
        return []
    status_by_card: dict[str, str] = {}
    for p in cards_dir.rglob('*.card.yaml'):
        try:
            doc = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError:
            continue
        cid = doc.get('card_id')
        if cid:
            status_by_card[cid] = doc.get('status', 'wired')
    problems: list[str] = []
    for dpath in sorted(dashboards_dir.glob('*.dashboard_spec.yaml')):
        try:
            dash = yaml.safe_load(dpath.read_text()) or {}
        except yaml.YAMLError:
            continue
        did = dash.get('dashboard_id', dpath.name)
        for entry in (dash.get('required_cards') or []):
            cid = (entry or {}).get('card_id')
            st = status_by_card.get(cid, 'wired')
            if st != 'wired':
                problems.append(
                    f"[ERROR] {did}: required_cards references '{cid}' whose card.status is "
                    f"'{st}' (not wired) — move it to placeholder_cards (required_cards must produce).")
        for entry in (dash.get('placeholder_cards') or []):
            cid = (entry or {}).get('card_id')
            st = status_by_card.get(cid, 'wired')
            if cid in status_by_card and st == 'wired':
                problems.append(
                    f"[WARNING] {did}: placeholder_cards lists '{cid}' but its card.status is 'wired' "
                    f"— a wired card belongs in required_cards/optional_cards.")
    return problems


def validate_modality_module_card_refs(cards_dir: Path) -> list[str]:
    """Cross-check (2026-08-12): every card_id referenced (any `card_id:` key, recursively) in a
    modality-module spec (dashboards/modality-modules/*.module.yaml) MUST resolve to a real card
    contract in cards/. A reference to a card with no contract is an ERROR — the phantom-reference
    drift class (e.g. the historical antigen-density-evidence, and functional-blockade-rationale before
    its placeholder contract was created). Module additional_cards MAY be status placeholder_not_wired /
    dormant_pending_data (the modality_module schema explicitly allows aspirational data-blocked cards),
    so status is NOT enforced here — only existence of a contract. No-op if the modules dir is absent."""
    cards_dir = Path(cards_dir)
    modules_dir = cards_dir.parent / 'dashboards' / 'modality-modules'
    if not modules_dir.is_dir():
        return []
    real: set[str] = set()
    for p in cards_dir.rglob('*.card.yaml'):
        try:
            d = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError:
            continue
        if d.get('card_id'):
            real.add(d['card_id'])

    def _card_ids(node) -> set[str]:
        out: set[str] = set()
        if isinstance(node, dict):
            cid = node.get('card_id')
            if isinstance(cid, str):
                out.add(cid)
            for v in node.values():
                out |= _card_ids(v)
        elif isinstance(node, list):
            for v in node:
                out |= _card_ids(v)
        return out

    problems: list[str] = []
    for mp in sorted(modules_dir.glob('*.module.yaml')):
        try:
            m = yaml.safe_load(mp.read_text()) or {}
        except yaml.YAMLError:
            continue
        mid = m.get('modality_module', mp.name)
        for cid in sorted(_card_ids(m)):
            if cid not in real:
                problems.append(
                    f"[ERROR] modality-module '{mid}': references card '{cid}' which has no card "
                    f"contract in cards/ (phantom reference — create a card spec or fix the id).")
    return problems


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

    # Dashboard required_cards ↔ card.status cross-check (2026-08-12): a non-wired card in required_cards
    # is an error (belongs in placeholder_cards). Runs only for a directory target (needs the card set).
    dashboard_problems = (validate_dashboard_required_cards(target)
                          + validate_modality_module_card_refs(target)) if target.is_dir() else []
    dash_errors = [p for p in dashboard_problems if p.startswith('[ERROR]')]
    dash_warnings = [p for p in dashboard_problems if p.startswith('[WARNING]')]
    if dashboard_problems:
        print()
        print('Dashboard required_cards <-> card.status cross-check:')
        for p in dashboard_problems:
            print(f'  {p}')

    if any(not r.ok for r in reports) or dash_errors:
        return 1
    if args.strict_warnings and (any(r.warnings for r in reports) or dash_warnings):
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
