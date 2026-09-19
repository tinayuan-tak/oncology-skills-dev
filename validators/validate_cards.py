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
import ast
import functools
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "card.schema.json"
PRODUCTS_PATH = Path(__file__).resolve().parent.parent / "vocabularies" / "products.yaml"
# Sibling data-catalog checkout, for the required_inputs[].product_id referential-integrity check.
# A product_id resolves against EITHER a data-catalog manifest id OR a registered products.yaml
# product id (the two legitimate namespaces). Located via env, defaulting to the sibling path;
# graceful-skip when absent (e.g. the checkout-only contracts-validate runner) — mirrors the
# _SKILLS_REPO figure-emission sibling pattern so the check never false-fails in isolated CI.
_DATA_CATALOG_REPO = Path(
    os.environ.get("DATA_CATALOG_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog")
)

# Recognized CEL-subset operators and reserved tokens (B1 § compose-dashboard subsection 2)
RECOGNIZED_OPERATORS = {"==", "!=", ">=", "<=", ">", "<", "&&", "||", "!", "in"}
# Predicate-allowed top-level identifiers (the context object's roots + summary fields)
RECOGNIZED_CONTEXT_ROOTS = {"target", "indication", "subgroup_spec", "release_pin", "data_mode"}

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
    "gdc-somatic-hotspot",  # methods/gdc_somatic_hotspot: read_stratified_mutation_frequency + build_mutation_frequency_panorama
    "depmap-chronos",  # methods/depmap_chronos: read_stratified_dependency + build_dependency_panorama
    "tcga-patient-cn",  # methods/tcga_patient_cn/stratified: read_stratified_copy_number + build_copy_number_panorama
    # (recomputes GISTIC amp/del fractions WITHIN each stratum member-set; patient-grain join)
    "tcga-fusion-consensus",  # methods/tcga_fusion_consensus/stratified: read_stratified_fusion + build_fusion_panorama
    # (per-stratum fusion recurrence; assayed-denominator ∩ stratum, patient-grain join)
    "tcga-gtex-expression-distribution",  # methods/tcga_gtex_expression_distribution: read_tumor_expression_subtype_landscape
    # recomputes the per-sample distribution WITHIN each stratum member-set
    # (UUID→barcode→stratum bridge), NOT an emit-time aggregate — AM #82.
    "dge-tumor-vs-normal-selectivity-by-subgroup",  # methods/dge_deseq2: read_stratified_tumor_vs_normal_selectivity
    # HONEST per-stratum recomputation, but EMIT-TIME not read-time: the
    # sensitivity-by-subgroup product ran a full DESeq2 fit WITHIN each
    # stratum's tumor set (steps/07_stratified_four_cell_driver.R). The
    # reader returns genuine per-stratum log2FC — NOT a whole-cohort
    # aggregate re-sliced — so it satisfies the honesty invariant this
    # allowlist protects. (Distinct from the three above, which recompute
    # from per-sample source data at read time.) — 2026-08-18.
    "depmap-expression-distribution",  # methods/depmap_expression_distribution: read_stratified_expression +
    # build_expression_subtype_panorama — recomputes the cell-line RNA
    # distribution WITHIN each DepMap-shard stratum member-set (ModelID-keyed,
    # no barcode bridge), reusing subgroup_common.panorama.build_panorama.
    "cptac-protein-distribution",  # methods/cptac_protein_distribution: read_stratified_protein +
    # build_protein_subtype_panorama — recomputes the CPTAC tumor-protein
    # (log2-ratio) distribution WITHIN each stratum member-set of the CPTAC
    # assignment shard (aliquot-keyed, aliquot->case bridge), reusing
    # subgroup_common.panorama.build_panorama. — 2026-08-21.
}

# The list-typed summary field names that signal a card emits a per-subgroup
# panorama. Both spellings are in use: `per_subgroup_metrics` (molecular-subgroup
# cards) and `per_stratum_metrics` (the RWD line-of-therapy card). Either implies
# a per-sample stratified reader is required.
PANORAMA_RECORD_FIELDS = {"per_subgroup_metrics", "per_stratum_metrics"}

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
    os.environ.get(
        "CLAUDE_ONCOLOGY_SKILLS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills"
    )
)
# The CARD_FIGURE_EMITTERS registry literal. As of the figure-consolidation Stage-4 split the
# monolith `_figure_emitters.py` became a package: the registry now lives in
# `_figure_emitters/_registry.py`. We try the package form first, then fall back to the legacy
# single-module file so this check works against either skills-repo checkout during the lockstep
# window (and never false-fails an isolated CI where the sibling repo is absent).
_SKILLS_SCRIPTS = _SKILLS_REPO / "skills" / "compose-dashboard" / "scripts"
_FIGURE_EMITTERS_CANDIDATES = (
    # Rehomed to _skills_common (2026-08-21) off the retiring compose-dashboard skill.
    _SKILLS_REPO / "skills" / "_skills_common" / "_figure_emitters" / "_registry.py",
    _SKILLS_SCRIPTS / "_figure_emitters" / "_registry.py",  # pre-rehome package under compose-dashboard
    _SKILLS_SCRIPTS / "_figure_emitters.py",  # legacy monolith
)

# Method-wiring check (foundation audit 2026-09-13). A card's `methods[]` block is the contract for
# HOW the card's evidence is produced. Two halves were unguarded:
#
#   (1) RESOLUTION. When an entry declares `module` + `entrypoint`, the skills live-reader layer
#       (_skills_common/_live_readers.py::_generic_dispatch) resolves it as
#       `__import__("methods." + (module or call.replace("-","_")), fromlist=["*"])` then
#       `getattr(mod, entrypoint)`. A declaration naming a symbol the module does not EXPORT raises
#       AttributeError at read time — and because the generic path is only a FALLBACK behind the
#       bespoke CARD_DISPATCHERS registry, a bespoke-routed card can carry a broken declaration
#       indefinitely with nothing failing. The audit found exactly that on 3 `wired` cards, where the
#       function existed in a SUBMODULE that the package `__init__` never re-exported. A pointer that
#       never resolves looks like a working one.
#
#   (2) ROUTABILITY. A card is readable on the live path iff it declares an `entrypoint` (generic) OR
#       a skills-side dispatcher registry names its card_id (bespoke / panorama / dual-grain). A card
#       that is NEITHER produces nothing, on every run, silently. Today that set is exactly the 9
#       KNOWN_UNROUTED_CARDS below and every one of them DECLARES a non-live status — so the
#       invariant holds and is worth ratcheting: a NEW unroutable card must be an error, not a new
#       exemption. See validate_card_method_routability().
#
# Resolution is STATIC (AST parse of the module file), not a real import: this validator runs as bare
# python in a checkout with no analysis-methods dependencies installed, so importing for real would
# fail on pandas/boto3 rather than on the wiring. Both halves graceful-skip when the sibling repo is
# absent (isolated CI), mirroring the _SKILLS_REPO figure-emission pattern above.
_ANALYSIS_METHODS_REPO = Path(
    os.environ.get("ANALYSIS_METHODS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods")
)
# The dispatcher registries live_readers exposes. Discovered BY NAME SUFFIX rather than a hardcoded
# list of three, so a fourth registry is picked up automatically instead of turning its cards into
# phantom "unroutable" findings (derive-the-check's-own-population).
_LIVE_READERS_PATH = _SKILLS_REPO / "skills" / "_skills_common" / "_live_readers.py"
_DISPATCHER_REGISTRY_SUFFIX = "DISPATCHERS"

# Measurement-type check (DATA_TO_SKILL_CONTRACT.md, 2026-07-21). A card's identity is
# (measurement_type × entity_grain) — Rule 1. During migration the field is OPTIONAL (existing
# cards are un-migrated), so a card WITHOUT measurement_type gets a WARNING (tracked migration debt),
# not an error. A card WITH one must name a type registered in vocabularies/measurement_types.yaml
# (else ERROR — a typo'd/unregistered type is a real defect). This is the machine-check that makes
# the pull-routing registry honest: every declared type resolves to a governed vocabulary entry.
_MEASUREMENT_TYPES_PATH = Path(__file__).resolve().parent.parent / "vocabularies" / "measurement_types.yaml"
_RULES_DIR = Path(__file__).resolve().parent.parent / "interpretation-rules"
# The 5 modality lenses a rule's signals{} dict can carry (matches card.schema.json modality_relevance
# enum + the per-rule signal keys in interpretation-rules/*.rules.yaml).
_MODALITY_SIGNAL_KEYS = frozenset({"small_molecule", "degrader", "adc", "bite_tce", "antibody"})
# The authored `interpretation:` values (mirrors card.schema.json). See
# _interpretation_declaration_check for what each one asserts and how it is enforced.
_INTERPRETATION_DECLARATIONS = frozenset({"rules_pending", "informational", "descriptive"})


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
    for rules_file in sorted(_RULES_DIR.glob("*.rules.yaml")):
        try:
            with rules_file.open() as f:
                doc = yaml.safe_load(f) or {}
        except yaml.YAMLError:
            continue
        for rule in doc.get("rules") or []:
            if not isinstance(rule, dict):
                continue
            when = rule.get("when") or {}
            card_id = when.get("card_id") if isinstance(when, dict) else None
            if not card_id:
                continue
            signals = rule.get("signals") or {}
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
    types = doc.get("measurement_types")
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
    types = doc.get("measurement_types")
    if not isinstance(types, dict):
        return None
    return {name for name, entry in types.items() if isinstance(entry, dict) and entry.get("modality_relevance")}


_AXES_PATH = Path(__file__).resolve().parent.parent / "vocabularies" / "target_profiling_axes.yaml"
# The `self_contained` sentinel: a consumed_by.lens value for hosts that resolve their verdict
# inline (no gate short) — see target_profiling_axes.yaml homing_rule / skill_objectives role_note.
_LENS_SENTINELS = frozenset({"self_contained"})


@functools.lru_cache(maxsize=1)
def _ontology_axis_shorts() -> Optional[set[str]]:
    """Valid `lens` / `reports_into` referents: the question `short`s + conditioner ids declared in
    vocabularies/target_profiling_axes.yaml. Returns None if the ontology is absent (→ graceful-skip;
    a checkout mid-migration may predate it)."""
    if not _AXES_PATH.exists():
        return None
    try:
        with _AXES_PATH.open() as f:
            doc = yaml.safe_load(f) or {}
    except yaml.YAMLError:
        return None
    questions = doc.get("questions")
    if not isinstance(questions, list):
        return None
    shorts = {q.get("short") for q in questions if isinstance(q, dict) and q.get("short")}
    shorts |= {c.get("id") for c in (doc.get("conditioner_axes") or []) if isinstance(c, dict) and c.get("id")}
    return shorts


def _question_shorts_only() -> Optional[set[str]]:
    """The question `short`s alone (no conditioners) — axis_edge.reports_into must name a QUESTION."""
    if not _AXES_PATH.exists():
        return None
    try:
        doc = yaml.safe_load(_AXES_PATH.read_text()) or {}
    except yaml.YAMLError:
        return None
    questions = doc.get("questions")
    if not isinstance(questions, list):
        return None
    return {q.get("short") for q in questions if isinstance(q, dict) and q.get("short")}


_CARD_ID_ALIASES_PATH = Path(__file__).resolve().parent.parent / "vocabularies" / "card_id_aliases.yaml"


@functools.lru_cache(maxsize=1)
def _card_id_aliases() -> dict[str, str]:
    """Map historical card_id -> current card_id from vocabularies/card_id_aliases.yaml
    (the forward-rename+alias convention — a card_id is a data contract, so a renamed card
    keeps an append-only alias so stored evidence packages still resolve). Returns {} when the
    file is absent/unparseable (graceful-skip — never a false failure in an isolated checkout).
    Consumed by the derived_from existence cross-check so a card that legitimately points at a
    since-renamed upstream still resolves."""
    if not _CARD_ID_ALIASES_PATH.exists():
        return {}
    try:
        with _CARD_ID_ALIASES_PATH.open() as f:
            doc = yaml.safe_load(f) or {}
    except yaml.YAMLError:
        return {}
    out: dict[str, str] = {}
    for entry in doc.get("aliases") or []:
        if isinstance(entry, dict) and entry.get("from") and entry.get("to"):
            out[entry["from"]] = entry["to"]
    return out


@functools.lru_cache(maxsize=1)
def _measurement_type_entity_grains() -> Optional[dict[str, set[str]]]:
    """{measurement_type -> set(entity_grains)} from vocabularies/measurement_types.yaml — the
    per-type CAPABILITY CEILING (Rule 5). Returns None when the vocab is absent (graceful-skip).
    Backs the entity_grains ceiling check (C5): a card must not advertise a grain its declared
    measurement_type's substrate cannot emit."""
    if not _MEASUREMENT_TYPES_PATH.exists():
        return None
    try:
        with _MEASUREMENT_TYPES_PATH.open() as f:
            doc = yaml.safe_load(f) or {}
    except yaml.YAMLError:
        return None
    types = doc.get("measurement_types")
    if not isinstance(types, dict):
        return None
    return {name: set(entry.get("entity_grains") or []) for name, entry in types.items() if isinstance(entry, dict)}


@functools.lru_cache(maxsize=1)
def _registered_figure_emitters() -> Optional[set[str]]:
    """Parse the card_id keys registered in CARD_FIGURE_EMITTERS. Returns None if the
    skills repo / registry file is unreachable (→ the check graceful-skips, never a
    false failure in an isolated checkout). Reads the first existing candidate — the
    Stage-4 package `_figure_emitters/_registry.py`, else the legacy monolith file."""
    txt = None
    for cand in _FIGURE_EMITTERS_CANDIDATES:
        try:
            txt = cand.read_text()
            break
        except OSError:
            continue
    if txt is None:
        return None
    # registry entries are  "card-id": _emit_fn,
    return set(re.findall(r'"([a-z0-9-]+)"\s*:\s*_emit', txt))


# Sentinel for a module the AST cannot see through (a star-import re-export). Distinct from
# "module not found" (a real defect) and from a known name set — an opaque module must SKIP, because
# a false ERROR on wiring that actually resolves is worse than the gap it would report.
_OPAQUE_MODULE = frozenset({"*"})


def _method_module_path(method: dict) -> str:
    """The importable methods-repo module path a `methods[]` entry resolves to. Mirrors
    _generic_dispatch exactly: explicit `module`, else the `call` slug with hyphens→underscores."""
    return str(method.get("module") or str(method.get("call") or "").replace("-", "_"))


def _top_level_bindings(body: list[ast.stmt]) -> tuple[set[str], bool]:
    """Names bound at a module's top level, plus whether a star-import makes it opaque.

    Walks INTO if/try/with bodies: a `try: from x import y / except ImportError: def y(...)` pattern
    binds the name at module level just as a bare def does, and treating it as absent would be a
    false failure. Does not walk into function/class bodies (those bind locally)."""
    names: set[str] = set()
    opaque = False
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    names.add(tgt.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    opaque = True
                else:
                    names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
            nested_bodies = [node.body, getattr(node, "orelse", []), getattr(node, "finalbody", [])]
            for handler in getattr(node, "handlers", []):
                nested_bodies.append(handler.body)
            for nested in nested_bodies:
                sub_names, sub_opaque = _top_level_bindings(nested)
                names |= sub_names
                opaque = opaque or sub_opaque
    return names, opaque


@functools.lru_cache(maxsize=1)
def _analysis_methods_available() -> bool:
    """True when the sibling analysis-methods checkout is on disk (else both wiring halves skip)."""
    return (_ANALYSIS_METHODS_REPO / "methods").is_dir()


@functools.lru_cache(maxsize=None)
def _method_module_bindings(module_path: str) -> Optional[frozenset[str]]:
    """Module-level names exported by `methods.<module_path>`, resolved statically.

    Returns None when no module FILE exists for the path (a real wiring defect), and
    _OPAQUE_MODULE when a star-import means the export set cannot be determined (→ skip)."""
    if not module_path or not _analysis_methods_available():
        return None
    base = _ANALYSIS_METHODS_REPO / "methods" / Path(*module_path.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if not candidate.is_file():
            continue
        try:
            tree = ast.parse(candidate.read_text())
        except (OSError, SyntaxError):
            return _OPAQUE_MODULE  # unparseable → cannot judge, do not false-fail
        names, opaque = _top_level_bindings(tree.body)
        return _OPAQUE_MODULE if opaque else frozenset(names)
    return None


@functools.lru_cache(maxsize=1)
def _dispatcher_routed_card_ids() -> Optional[frozenset[str]]:
    """card_ids the skills live-reader layer routes via a hand-written dispatcher — the union of every
    module-level `*DISPATCHERS` dict literal in _skills_common/_live_readers.py.

    Returns None when the skills repo is unreachable OR when no registry is found at all: an empty
    routed set would report every bespoke-routed card as unroutable, so a parse that finds nothing is
    treated as "cannot determine" rather than as evidence of absence."""
    try:
        tree = ast.parse(_LIVE_READERS_PATH.read_text())
    except (OSError, SyntaxError):
        return None
    routed: set[str] = set()
    registries = 0
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if not any(name.endswith(_DISPATCHER_REGISTRY_SUFFIX) for name in targets):
            continue
        registries += 1
        for key in node.value.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                routed.add(key.value)
    if not registries or not routed:
        return None
    return frozenset(routed)


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
    "mutation-hotspot-frequency",
    "co-mutation-and-mutual-exclusivity",
    "signaling-network-mechanism",
    # genomic alteration-class CLEARED 2026-07-22 — _emit_alteration_role is registered in
    # compose-dashboard CARD_FIGURE_EMITTERS (SK #152, backed by AM #90), so the card passes the
    # figure check on its own (not waived).
    # dependency-hardening + subgroup panels:
    "paralog-buffering",
    "subgroup-stratified-mutation-frequency",
    "synthetic-lethal-partners",  # figure backfill deferred (viz-debt queue)
    "subgroup-stratified-dependency",
    "subgroup-stratified-expression",
    "copy-number-stratified-dependency",  # A1a (2026-08-06) — amp-vs-neutral strip emitter deferred (viz-debt queue)
    "fusion-stratified-dependency",  # A1-fusion (2026-08-06) — fusion-vs-negative strip emitter deferred (viz-debt queue)
    "amp-expr-stratified-dependency",  # A1 amp-expr (2026-08-06) — conjoint amp+overexpr strip emitter deferred (viz-debt queue)
    "alteration-clinical-association",  # Q11-alteration (2026-08-20) — OS-by-mutation-status card; emit_svg in method cli, skills CARD_FIGURE_EMITTERS registration deferred (viz-debt queue)
    "subtype-survival-association",  # Q2-subtype (2026-08-20) — OS-across-subtypes card; emit_svg in method cli, skills CARD_FIGURE_EMITTERS registration deferred (viz-debt queue)
    "oncogenic-pathway-alteration",  # Sanchez-Vega (2026-08-10) — pathway-alteration bar emitter deferred (viz-debt queue)
    "stemness-context",  # Malta 2018 (2026-08-10) — stemness distribution emitter deferred (viz-debt queue)
    "target-development-level",  # Pharos/IDG (2026-08-10) — TDL tier bar emitter deferred (viz-debt queue)
    "cross-consortium-dependency",  # Project Score (2026-08-10) — Broad-vs-Sanger concordance emitter deferred (viz-debt queue)
    "partner-conditional-dependency",  # Track PC (2026-08-09) — partner-deficient-vs-neutral strip emitter deferred (viz-debt queue)
    "ddr-deficiency-context",  # Track PI (2026-08-09) — HRD-context strip/bar emitter deferred (viz-debt queue)
    "pathway-activity-context",  # Track PROGENy (2026-08-10) — pathway-activity bar/heatmap emitter deferred (viz-debt queue)
    "precog-prognostic-association",  # PRECOG (2026-08-10) — meta-Z prognostic strip/forest emitter deferred (viz-debt queue)
    "competitor-landscape",  # Open Targets competitor field (2026-08-24) — method runs (opentargets_competitor_landscape); competitor_landscape_table emitter deferred (viz-debt queue), like sibling clinical-precedent
    # surface tier + shed:
    "shed-ectodomain-liability",
    "surface-topology-and-ptm",
    "surfaceome-family-classification",
    "surfaceome-cohort-ranking",
    "structure-features-static",
    # data-blocked (no runnable method yet, but the card declares a figure):
    "antigen-prevalence",
    "clinical-precedent",
    "lineage-restriction-evidence",
    "protein-surface-evidence",
    "surface-abundance-density",
    "adc-tce-modality-fit",
    "fusion-rearrangement-landscape",
    "rwd-stratified-expression",
    # card-audit delta landing (2026-08-21): placeholder_not_wired cards that declare a figure but
    # have no product/method built yet (same data-blocked class as antigen-prevalence above).
    "temporal-setting-expression-shift",  # setting_shift_bar — no setting-annotated cohort reader landed
    "antigen-internalization",  # internalization_turnover_panel — no internalization/turnover product
    "antigen-prevalence-protein",  # protein_prevalence_curve_with_thresholds — no CPTAC protein-prevalence product
    "target-identity-summary",
    "modality-therapeutic-window",  # figure modality_window_tumor_vs_essential_normal declared at card
    # creation (2026-08-06) but emitter never registered — pre-existing
    # viz-debt (was failing on main before this edit); waived on the
    # convention here. Emitter backfill deferred to the viz-debt queue.
    # tumor-elevation-breadth CLEARED 2026-07-22: the pan-cancer by-tissue TPM distribution
    # emitter (_emit_tumor_elevation_breadth, drawing from tcga-gtex-tpm-tissue-quantiles-v1)
    # is now registered in CARD_FIGURE_EMITTERS — passes the check, not waived.
    # combo axes + immune/pMHC (added 2026-08-08): declare a figure but their emitter is not yet
    # registered in compose-dashboard _figure_emitters.py CARD_FIGURE_EMITTERS. Tracked viz-debt.
    "combo-crispr-screen",  # figure emitter not yet registered in compose-dashboard _figure_emitters.py
    "combinatorial-dependency",  # figure emitter not yet registered in compose-dashboard _figure_emitters.py
    # immune-context CLEARED 2026-09-12 (SK #1332): _emit_immune_context_leukocyte_composition is
    # registered in CARD_FIGURE_EMITTERS (_figure_emitters/_immune.py) — the card declared
    # `figure: immune_context_leukocyte_composition` from v1.0 (2026-08-08) and every run since
    # attached NOTHING — the silence this waiver is designed to track. Now passes, not waived.
    "pmhc-presentation",  # figure emitter not yet registered in compose-dashboard _figure_emitters.py (pre-existing)
}

# KNOWN unroutable cards (foundation audit 2026-09-13): cards the skills live-reader layer cannot read
# on ANY path — no `methods[].entrypoint` for the generic dispatcher AND no card_id in any
# `*DISPATCHERS` registry. All 8 declare a non-live top-level status, so the exemption is BY
# DECLARATION, not by silence — validate_card_method_routability() asserts that, asserts this set is
# exactly the unroutable set (a stale waiver on a now-routable card is also an error), and errors on
# any card that joins it. The status column is what makes the waiver reviewable.
KNOWN_UNROUTED_CARDS = {
    "antigen-internalization",  # placeholder_not_wired — no internalization/turnover product exists
    "antigen-prevalence-protein",  # placeholder_not_wired — no CPTAC protein-prevalence product
    "functional-blockade-rationale",  # placeholder_not_wired — contract created to kill a phantom ref
    "lineage-restriction-evidence",  # dormant_pending_data
    "rwd-stratified-expression",  # placeholder_not_wired — no RWD cohort held
    "sc-surface-normal-safety-solid",  # placeholder_not_wired
    "subgroup-stratified-expression",  # dormant_pending_data — per-sample subtype expression reader
    "temporal-setting-expression-shift",  # placeholder_not_wired — no setting-annotated cohort reader
}
# The statuses that make a card's unroutability a DECLARED state rather than a silent gap.
_NON_LIVE_STATUSES = frozenset({"placeholder_not_wired", "dormant_pending_data"})

# KNOWN vocabulary orphans (2026-09-14): a card declares a `summary_fields_vocabulary` for a field it
# never declares -- not in `outputs.summary_fields`, and not a key of any declared
# `summary_fields_record_schemas` record -- so the enumerated value set is attached to nothing and is
# dropped downstream. See _summary_vocabulary_declaration_check() for the mechanism and the proof.
# Measured over every card: 4 orphans out of 289 vocabulary keys across 148 cards. Enumerated so the
# build stays green while the debt is worked down; the check is TWO-SIDED, so a new orphan fails AND an
# entry that stops being an orphan fails, which is what stops this set outliving the debt.
#
# NONE of the four declares any `summary_fields_record_schemas` at all, and three of the four declare a
# collection-shaped summary field alongside the orphan vocabulary. So the likely remedy is to DECLARE
# the record schema the vocabulary belongs to -- exactly what
# tumor-vs-normal-percentile-crossing-by-subtype does correctly, which is why it is not on this list --
# rather than to delete the enum. Confirmed per card, not inferred from the pattern.
KNOWN_VOCABULARY_ORPHANS: dict[str, set[str]] = {
    # 6-value zygosity/epigenetic axis (wt .. biallelic+epigenetic). The card declares only
    # functional_state_class, patient, model, vocabulary_phase -- no per-sample record anywhere.
    # LATENT: no generated summary schema yet.
    "functional-gene-state": {"sample_state"},
    # 6-value tissue taxonomy (solid_tissue, body_fluid, ...). The card declares the collection field
    # `per_tissue_abundance` but no record schema for it, so a per-tissue key has nowhere legal to sit.
    # LATENT: no generated summary schema yet.
    "normal-tissue-protein-abundance-tphp": {"tissue_category"},
    # SHIPPED LOSS, not latent: schemas/methods/prism-compound-activity.summary.schema.json carries 7
    # properties and `metric_source` is not among them, so this 3-value enum is already absent from a
    # committed artifact. The card declares the collection fields `top_compounds` /
    # `per_lineage_activity` but no record schema.
    "prism-compound-activity": {"metric_source"},
    # 3-value per-variant resistance annotation. The card declares the collection fields
    # `resistance_variants` / `oncogenic_variants` but no record schema.
    # LATENT: no generated summary schema yet.
    "variant-level-interpretation": {"resistance_class"},
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
        path = ".".join(str(p) for p in err.absolute_path) or "<root>"
        report.add_error(f"STRUCTURAL [{path}]: {err.message}")


def _threshold_ref_check(spec: dict, report: ValidationReport) -> None:
    """Layer 2a: every THRESHOLD.<name> reference must exist in thresholds: block."""
    declared = set((spec.get("thresholds") or {}).keys())
    referenced: set[str] = set()

    def scan_predicate(pred: str, where: str) -> None:
        for match in re.finditer(r"THRESHOLD\.([a-z_][a-z0-9_]*)", pred):
            name = match.group(1)
            referenced.add(name)
            if name not in declared:
                report.add_error(
                    f"THRESHOLD_REF [{where}]: predicate references undeclared threshold "
                    f"`THRESHOLD.{name}`. Declared thresholds: {sorted(declared) or '(none)'}."
                )

    for i, pred in enumerate(spec.get("applies_when", [])):
        scan_predicate(pred, f"applies_when[{i}]")
    for i, hint in enumerate(spec.get("interpretation_hints", [])):
        scan_predicate(hint.get("if", ""), f"interpretation_hints[{i}].if")
    for i, wp in enumerate(spec.get("warning_predicates", []) or []):
        scan_predicate(wp.get("if", ""), f"warning_predicates[{i}].if")

    # Inverse check: declared thresholds that no predicate references. A cutoff applied by the
    # METHOD or the READER can never be predicate-referenced, so this warned permanently for it
    # and asked authors to delete numbers the method needs (dependency-predictability's
    # rf_n_estimators / xgb_learning_rate are hyperparameters, not interpretation cutoffs).
    # threshold_roles: declares that case per-name; the checks below keep it from becoming a
    # blanket silencer, and only genuinely orphaned thresholds still warn.
    roles = spec.get("threshold_roles") or {}
    own_calls = set(_method_calls(spec))
    for name in sorted(roles):
        entry = roles[name] or {}
        where = f"threshold_roles.{name}"
        if name not in declared:
            report.add_error(
                f"DANGLING_THRESHOLD_ROLE [{where}]: no such entry in `thresholds:`. Declared: "
                f"{sorted(declared) or '(none)'}."
            )
            continue
        if name in referenced:
            # Also the STALE ratchet: the day a predicate starts comparing against this value,
            # the declaration says the opposite of what the card does, and must fail loudly
            # rather than sit there suppressing a warning that is now wrong.
            report.add_error(
                f"MISDECLARED_THRESHOLD_ROLE [{where}]: a predicate on this card references "
                f"`THRESHOLD.{name}`, so it is NOT applied only upstream. Remove the role entry."
            )
            continue
        if entry.get("role") == "method_parameter":
            call = entry.get("consumed_by")
            if call not in own_calls:
                report.add_error(
                    f"UNKNOWN_THRESHOLD_CONSUMER [{where}]: `consumed_by: {call}` is not a "
                    f"methods[].call on this card. This card calls: {sorted(own_calls) or '(none)'}."
                )

    unused = declared - referenced - set(roles)
    if unused:
        report.add_warning(
            f"THRESHOLD_UNUSED: thresholds {sorted(unused)} declared but never referenced "
            f"by any predicate. Remove from thresholds: block, use them, or — if the cutoff is "
            f"applied by the method or the reader rather than by this card — declare it in "
            f"`threshold_roles:` with the consumer."
        )


def _class_cutpoint_check(spec: dict, report: ValidationReport) -> None:
    """Layer 2c (2026-09-18): the derivation edge — `threshold_roles.role: class_cutpoint`
    and `outputs.derivations` must round-trip against each other and against the card's
    declared `summary_fields` / `summary_fields_vocabulary`.

    A class_cutpoint says "this named threshold is a boundary that bins a numeric field
    (`of`) into a categorical class field (`bins`)"; `outputs.derivations` is the per-class
    summary of that edge (`derives_from` + `cutpoints`). Neither declaration existed before
    this date, so the hop log2_fc -> expression_call_class was recorded nowhere and the
    emitted package was not re-binnable. These checks keep the two declarations honest once
    a card adopts them. They fire ONLY on cards that use the feature, so the addition is
    forward-compatible: a card that declares neither is unaffected.
    """
    roles = spec.get("threshold_roles") or {}
    outputs = spec.get("outputs") or {}
    vocab = outputs.get("summary_fields_vocabulary") or {}
    derivations = outputs.get("derivations") or {}
    summary_fields = _summary_field_names(spec)

    # class_cutpoint entries -> forward references + derivations round-trip
    for name in sorted(roles):
        entry = roles[name] or {}
        if entry.get("role") != "class_cutpoint":
            continue
        where = f"threshold_roles.{name}"
        bins = entry.get("bins")
        of = entry.get("of")
        boundary = entry.get("boundary")
        # (1) bins must be a categorical summary_field (a summary_fields_vocabulary key)
        if bins not in vocab:
            report.add_error(
                f"CLASS_CUTPOINT_UNKNOWN_CLASS [{where}]: bins `{bins}` is not a key of "
                f"outputs.summary_fields_vocabulary (a categorical class). Declared classes: "
                f"{sorted(vocab) or '(none)'}."
            )
        # (2) of must be a declared summary_field; boundary (when present) a value of bins
        if of not in summary_fields:
            report.add_error(
                f"CLASS_CUTPOINT_UNKNOWN_FIELD [{where}]: of `{of}` is not a declared "
                f"outputs.summary_fields entry. Declared fields: {sorted(summary_fields) or '(none)'}."
            )
        if boundary is not None and boundary not in set(vocab.get(bins, [])):
            report.add_error(
                f"CLASS_CUTPOINT_UNKNOWN_BOUNDARY [{where}]: boundary `{boundary}` is not a value of "
                f"`{bins}` in summary_fields_vocabulary ({sorted(vocab.get(bins, [])) or '(none)'})."
            )
        # (3) derivations round-trip: bins entry exists, name is a cutpoint of it, of in derives_from
        deriv = derivations.get(bins)
        if deriv is None:
            report.add_error(
                f"CLASS_CUTPOINT_DERIVATION_MISMATCH [{where}]: no outputs.derivations entry for the "
                f"class `{bins}` this cutpoint bins. Every class_cutpoint must be summarised there."
            )
        else:
            if name not in (deriv.get("cutpoints") or []):
                report.add_error(
                    f"CLASS_CUTPOINT_DERIVATION_MISMATCH [{where}]: `{name}` is declared class_cutpoint "
                    f"but is absent from outputs.derivations.{bins}.cutpoints "
                    f"({sorted(deriv.get('cutpoints') or [])})."
                )
            if of is not None and of not in (deriv.get("derives_from") or []):
                report.add_error(
                    f"CLASS_CUTPOINT_DERIVATION_MISMATCH [{where}]: of `{of}` is absent from "
                    f"outputs.derivations.{bins}.derives_from "
                    f"({sorted(deriv.get('derives_from') or [])})."
                )

    # derivations entries -> reverse references (unknown class, numeric field the card does not
    # emit, or a cutpoint name with no backing class_cutpoint on this class)
    cutpoint_names_by_class: dict[str, set[str]] = {}
    for nm, e in roles.items():
        if (e or {}).get("role") == "class_cutpoint":
            cutpoint_names_by_class.setdefault((e or {}).get("bins"), set()).add(nm)
    for cls in sorted(derivations):
        deriv = derivations[cls] or {}
        where = f"outputs.derivations.{cls}"
        if cls not in vocab:
            report.add_error(
                f"DERIVATION_UNKNOWN_CLASS [{where}]: `{cls}` is not a key of "
                f"outputs.summary_fields_vocabulary. Declared classes: {sorted(vocab) or '(none)'}."
            )
        for num_field in deriv.get("derives_from") or []:
            if num_field not in summary_fields:
                report.add_error(
                    f"DERIVATION_UNKNOWN_FIELD [{where}]: derives_from `{num_field}` is not a declared "
                    f"outputs.summary_fields entry."
                )
        for cutpoint in deriv.get("cutpoints") or []:
            if cutpoint not in cutpoint_names_by_class.get(cls, set()):
                report.add_error(
                    f"DERIVATION_UNKNOWN_CUTPOINT [{where}]: cutpoint `{cutpoint}` is not a "
                    f"threshold_roles entry with role: class_cutpoint and bins: {cls}."
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
            report.add_error(f"PREDICATE [{where}]: empty predicate.")
            return
        # Balanced parens
        depth = 0
        for c in pred:
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth < 0:
                    report.add_error(f"PREDICATE [{where}]: unbalanced parens (close before open).")
                    return
        if depth != 0:
            report.add_error(f"PREDICATE [{where}]: unbalanced parens (depth {depth} at end).")
        # Python-isms that aren't valid CEL operators
        for pattern, display, suggested in (
            (r"\band\b", "and", "&&"),
            (r"\bor\b", "or", "||"),
            (r"\bnot\s", "not", "!"),
        ):
            if re.search(pattern, pred):
                report.add_error(
                    f"PREDICATE [{where}]: uses Python-style operator `{display}`; "
                    f"CEL-subset requires `{suggested}` instead."
                )

    for i, pred in enumerate(spec.get("applies_when", [])):
        lint_predicate(pred, f"applies_when[{i}]")
    for i, hint in enumerate(spec.get("interpretation_hints", [])):
        lint_predicate(hint.get("if", ""), f"interpretation_hints[{i}].if")
    for i, wp in enumerate(spec.get("warning_predicates", []) or []):
        lint_predicate(wp.get("if", ""), f"warning_predicates[{i}].if")


def _summary_field_names(spec: dict) -> set[str]:
    """Extract field name strings from summary_fields, tolerating both the
    legacy bare-string form and the arch-A2 object form
    ({name, lens_conditional_on?, description?}). Introduced 2026-07-08 with
    the lens-conditional field split.
    """
    raw = spec.get("outputs", {}).get("summary_fields", [])
    names: set[str] = set()
    for entry in raw:
        if isinstance(entry, str):
            names.add(entry)
        elif isinstance(entry, dict) and "name" in entry:
            names.add(entry["name"])
    return names


@functools.lru_cache(maxsize=1)
def _data_catalog_manifest_ids() -> Optional[set[str]]:
    """The set of manifest ids in the sibling data-catalog (source + derived). A manifest id is the
    yaml filename stem (== its `id:` field). Returns None if the sibling checkout is absent (→ the
    product_id check graceful-skips; a checkout-only CI runner has no data-catalog)."""
    manifests = _DATA_CATALOG_REPO / "manifests"
    if not manifests.is_dir():
        return None
    return {p.name[: -len(".yaml")] for p in manifests.glob("*/*.yaml")}


@functools.lru_cache(maxsize=1)
def _manifest_declared_product_ids() -> set[str]:
    """The Analysis-Product ids that data-catalog manifests declare via their own `product_id:` field.

    A third legitimate namespace, and one this check used to be blind to. A manifest id is
    version-pinned (`depmap-predictability-26q1-v3`); a handful of DERIVED manifests additionally
    declare which registered Analysis Product they are an instance of (`product_id:
    depmap-predictability`), a field data-catalog's own manifest schema permits only on derived
    manifests and cross-validates against its products registry. Cards naming one of those ids were
    reported as unresolvable typos while the manifest sitting next to them declared exactly that
    string (see `dependency-predictability` → depmap-predictability-26q1-v3.yaml).

    This is NOT the "unversioned alias" namespace — a release-pinned SOURCE manifest cannot declare
    `product_id:` at all (its schema branch forbids it), so an unversioned ref like
    `gdc-pancohort-somatic` resolves via _manifest_id_release_stems() instead.

    Read with a cheap line scan rather than a full yaml.safe_load of every manifest: 509 manifests
    is seconds of parse time in a check that runs on every card.
    """
    manifests = _DATA_CATALOG_REPO / "manifests"
    if not manifests.is_dir():
        return set()
    found: set[str] = set()
    for p in manifests.glob("*/*.yaml"):
        try:
            text = p.read_text()
        except OSError:
            continue
        for line in text.splitlines():
            if line.startswith("product_id:"):
                pid = line[len("product_id:") :].strip().strip("\"'")
                if pid:
                    found.add(pid)
    return found


# A trailing manifest-id token that encodes a version/release rather than the product's identity.
# Observed forms across the ~509 catalogued manifests: -v1, -v25-1, -26q1-v3, -dr45-0, -19-0.
_VERSION_TOKEN_RE = re.compile(r"^(v\d+[a-z]*|\d+|dr\d+|\d+q\d+)$")


@functools.lru_cache(maxsize=1)
def _manifest_id_release_stems() -> set[str]:
    """Manifest ids with their trailing version/release tokens stripped.

    The namespace an UNVERSIONED, release-pinned card ref lives in. A card that wants "whatever the
    current release of this dataset is" must name the release-free stem and supply `release_pin`
    separately — pinning both would freeze the card to one release, which is precisely what
    `mutation-hotspot-frequency` (`gdc-pancohort-somatic` + `release_pin: {release_pin}`) and
    `lineage-restriction-evidence` (`hpa-normal-tissue-expression`) are avoiding. The catalog has no
    field for this: `product_id:` means "instance of a registered Analysis Product" and is allowed
    only on derived manifests, so the stem must be derived here from the manifest ids themselves.

    Consulted ONLY for entries that carry a `release_pin` (see the caller). That restriction is what
    keeps this from degenerating into prefix matching: an id may resolve to a stem only when the card
    has explicitly said "the release is supplied elsewhere". A bare `hpa-normal-tissue-expression`
    with no release_pin still warns, because nothing then pins it to a real artifact.
    """
    manifests = _data_catalog_manifest_ids()
    if manifests is None:
        return set()
    stems: set[str] = set()
    for mid in manifests:
        parts = mid.split("-")
        while len(parts) > 1 and _VERSION_TOKEN_RE.match(parts[-1]):
            parts.pop()
        stem = "-".join(parts)
        if stem != mid:  # only ids that actually carried a version suffix contribute a stem
            stems.add(stem)
    return stems


@functools.lru_cache(maxsize=1)
def _catalog_class_input_ids() -> set[str]:
    """Non-manifest data-catalog inputs a card may legitimately require.

    `subgroup-catalog` is not a dataset and never had a manifest — it is the per-indication registry
    at `data-catalog/subgroup-catalogs/<IND>/*.yaml` that the subgroup-stratified cards join against
    to learn which strata exist. Six cards name it; all six fired in the 2026-09-11 panel. Resolved
    against the directory actually being present, so this stays a real referential check (delete the
    catalogs and the six warns come back) rather than a hardcoded allowlist.
    """
    ok: set[str] = set()
    if (_DATA_CATALOG_REPO / "subgroup-catalogs").is_dir():
        ok.add("subgroup-catalog")
    # target-identity-summary requires the target-id resolver RELEASE — a versioned artifact of the
    # data-catalog library at libs/target_id_resolver, not a dataset manifest.
    if (_DATA_CATALOG_REPO / "libs" / "target_id_resolver").is_dir():
        ok.add("target-id-resolver-release")
    return ok


@functools.lru_cache(maxsize=1)
def _registered_product_ids() -> set[str]:
    """The product ids registered in vocabularies/products.yaml (the ~25-entry dimension-product
    registry). Empty set if the file is absent/malformed."""
    if not PRODUCTS_PATH.exists():
        return set()
    try:
        with PRODUCTS_PATH.open() as f:
            doc = yaml.safe_load(f) or {}
    except yaml.YAMLError:
        return set()
    products = doc.get("products") if isinstance(doc, dict) else None
    if not isinstance(products, list):
        return set()
    return {p["id"] for p in products if isinstance(p, dict) and "id" in p}


@functools.lru_cache(maxsize=1)
def _manifest_supersession_map() -> dict[str, tuple[str, ...]]:
    """Map a SUPERSEDED manifest id -> the manifest id(s) declaring it superseded (2026-09-17).

    Why a separate map instead of another entry in `known`: supersession is orthogonal to
    resolvability. A superseded id resolves perfectly well — its manifest is still on disk — so
    PRODUCT_ID_UNRESOLVED can never see it. That blind spot is what let
    `mutation-hotspot-frequency` declare `pooled-snv-recurrence-v1` for the whole life of v2 while
    every gate stayed green (fixed by hand in #791; this map is the check that would have caught it).

    THREE CHANNELS, all read, because they were found by measuring the corpus rather than by reading
    the schema:
      a. top-level `supersedes:` — the only one data-catalog's manifest schema declares
         (`schema/manifest.schema.json`: type string, pattern `^[a-z0-9][a-z0-9-]*$`).
      b. `cohort.supersedes` — undeclared, but read by data-catalog's OWN
         `validate_catalog.py::_superseded_ids`, so it is load-bearing there.
      c. `parameters.supersedes` — read by NOBODY, yet used by two live manifests
         (`tphp-tumor-vs-normal-protein-per-cohort-v2`, `normal-tissue-protein-abundance-per-gene-v2`),
         each next to `v1_columns_unchanged: true`, i.e. genuine drop-in replacements.
    No card names a channel-(c) id today, so reading it changes nothing measurable *now*. It is read
    anyway: inert-by-corpus is not safe-by-contract, and being blind because the PRODUCER misfiled
    the field is the same fail-open posture that produced the bug this check exists to catch. Reading
    (a) as well means the check stays correct once those two are moved to their schema-declared home.

    CHEAP PREFILTER + EXACT PARSE, because both naive approaches are wrong:
      * `yaml.safe_load` of all 532 manifests costs **53s** — this is called once per run (cached),
        but 53s is not a tax a per-card validator can carry.
      * a bare line scan costs 0.2s and OVER-collects: it lifts prose out of block scalars
        (`normal-tissue-protein-abundance-per-gene-v1.yaml` contains the sentence "…(supersedes the
        primary NORMAL-tissue PROTEIN baseline…"), which would invent a superseded id and warn on
        cards that are correct — the precise false-positive mode that made 12 of this check's first
        17 warnings wrong.
    So: line-scan for the literal `supersedes:` to narrow 532 files to ~10 candidates, then
    `yaml.safe_load` only those. Exact structure, 0.2s total. Prose is dropped for free, because the
    parse simply finds no such key.

    Returns {} when the sibling data-catalog is absent — the caller graceful-skips before reaching
    this, but an empty map is also the correct no-op answer.
    """
    manifests = _DATA_CATALOG_REPO / "manifests"
    if not manifests.is_dir():
        return {}
    out: dict[str, set[str]] = {}
    for p in manifests.glob("*/*.yaml"):
        try:
            text = p.read_text()
        except OSError:
            continue
        if "supersedes:" not in text:  # prefilter: skip the ~98% that cannot contribute
            continue
        try:
            doc = yaml.safe_load(text) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(doc, dict):
            continue
        for holder in (doc, doc.get("cohort"), doc.get("parameters")):
            if not isinstance(holder, dict):
                continue
            old = holder.get("supersedes")
            if isinstance(old, str) and old and old != p.stem:
                out.setdefault(old, set()).add(p.stem)
    return {k: tuple(sorted(v)) for k, v in out.items()}


def _supersession_head(pid: str, sup: dict[str, tuple[str, ...]]) -> tuple[str, list[str]]:
    """Walk `pid` to the HEAD of its supersession chain. Returns (head, full_chain).

    Transitive on purpose: `depmap-predictability-26q1-v1 -> -v2 -> -v3` is a real 2-hop chain in the
    catalog today, so naming only the immediate successor would hand out advice that is *itself*
    superseded — a fix that still leaves the card one vintage behind.

    Cycle-guarded. A malformed catalog can express `a supersedes b` and `b supersedes a`; without the
    `seen` set this walk would hang the validator, turning a data typo into a build hang. When
    several manifests supersede the same id (never true today) the lexicographically first is
    followed, and the caller reports all of them, so the ambiguity is visible rather than resolved
    silently.
    """
    chain = [pid]
    seen = {pid}
    cur = pid
    while cur in sup:
        nxt = sup[cur][0]
        if nxt in seen:  # cycle in the catalog's own declarations — stop, report what we have
            break
        chain.append(nxt)
        seen.add(nxt)
        cur = nxt
    return cur, chain


def _required_inputs_product_id_check(spec: dict, report: ValidationReport) -> None:
    """Referential integrity for required_inputs[].product_id (2026-09-06).

    A product_id must resolve to one of FIVE legitimate namespaces:
      1. a data-catalog manifest id                    (`gdc-pancohort-somatic-dr45-0`)
      2. a manifest's declared Analysis-Product id      (`depmap-predictability`)
      3. a vocabularies/products.yaml product id        (the ~25-entry dimension-product registry)
      4. a non-manifest catalog input                   (`subgroup-catalog`, `target-id-resolver-release`)
      5. a release-stripped manifest-id stem, and ONLY when the entry supplies a `release_pin`
                                                        (`gdc-pancohort-somatic` + release_pin)
    Template placeholders (containing '{') are skipped.

    Namespaces 2, 4 and 5 were added 2026-09-11 after an audit found 12 of 17 warns were false: the
    check knew only (1) and (3), so it flagged cards whose product_id was declared verbatim by a
    manifest, every card requiring the subgroup catalog, and every card correctly naming a logical
    dataset with the release supplied separately. What remains flagged is real — un-materialized
    products with no catalog record anywhere.

    SECOND, ORTHOGONAL CHECK — PRODUCT_ID_SUPERSEDED (2026-09-17). Resolving is not the same as being
    current. A superseded id resolves against namespace 1 like any other, so the check above is blind
    to supersession BY CONSTRUCTION, not by oversight. `_manifest_supersession_map()` supplies the
    missing predicate, and it is evaluated FIRST so a superseded entry yields exactly one warning.
    Note the limitation this leaves: the map keys on the id as declared, so a card naming a
    release-stripped STEM (namespace 5) whose pinned manifest is superseded will not fire — catching
    that needs the stem→manifest direction, which is a different lookup.

    WARNING (not error): a typo'd / renamed / truncated manifest ref or a reference to an
    un-materialized product is otherwise silently undetectable in-repo.

    NOTE the consequence is provenance, not read failure. `required_inputs[].product_id` is copied
    verbatim into a run's `provenance.input_manifest_ids` by _skills_common.card_input_manifest_ids
    and is NOT used to route the read — a card can name an unresolvable id and still fire (verified:
    mutation-hotspot-frequency names `gdc-pancohort-somatic`, validation_state=pass). So the cost of
    an unresolved ref is a published audit trail that does not lead to the data, plus dropping out of
    the envelope's data-family release resolution. An earlier version of this message claimed the
    reader would return _live_read_error and degrade the verdict to insufficient; that was wrong.

    GRACEFUL-SKIP when the sibling data-catalog is absent (checkout-only CI): without the manifest
    list a valid manifest id can't be distinguished from a typo, so the check runs at preland / on a
    siblings-present runner and never false-fails in isolation."""
    manifest_ids = _data_catalog_manifest_ids()
    if manifest_ids is None:
        return  # data-catalog sibling absent → cannot resolve manifest ids; skip (never false-fail)
    known = manifest_ids | _manifest_declared_product_ids() | _registered_product_ids() | _catalog_class_input_ids()
    superseded = _manifest_supersession_map()
    for i, ri in enumerate(spec.get("required_inputs", []) or []):
        if not isinstance(ri, dict):
            continue
        pid = ri.get("product_id")
        if not isinstance(pid, str) or not pid or "{" in pid:
            continue  # missing/templated product_ids are handled by structural + compose-time checks
        if pid in superseded:
            # Checked BEFORE resolvability, and `continue`s, so an entry yields at most one warning.
            # A superseded id normally resolves (its manifest is still on disk) and would otherwise
            # fall through as clean; when it does NOT resolve, this message is still the more useful
            # of the two because it names the replacement instead of only reporting a dead end.
            head, chain = _supersession_head(pid, superseded)
            by = ", ".join(superseded[pid])
            hops = f" via {' → '.join(chain[1:-1])}" if len(chain) > 2 else ""
            report.add_warning(
                f"PRODUCT_ID_SUPERSEDED [required_inputs[{i}]]: product_id {pid!r} is superseded by "
                f"{by} — the head of that family is {head!r}{hops}. The id still resolves, so this is "
                f"invisible to PRODUCT_ID_UNRESOLVED, and the card still fires; the cost is that "
                f"card_input_manifest_ids() stamps the superseded vintage into every run's "
                f"provenance.input_manifest_ids, and the envelope's is_stale flag compares the "
                f"CATALOG head against this CONTRACT value, so a regenerated package reports "
                f"is_stale on the run rather than pointing at this line. Repoint to {head!r} once the "
                f"reader is confirmed to read it, or state here why this vintage is pinned."
            )
            continue
        if pid in known:
            continue
        # Namespace 5, gated on the entry pinning its own release (see _manifest_id_release_stems).
        if ri.get("release_pin") and pid in _manifest_id_release_stems():
            continue
        report.add_warning(
            f"PRODUCT_ID_UNRESOLVED [required_inputs[{i}]]: product_id {pid!r} matches no "
            f"data-catalog manifest id, no manifest-declared Analysis-Product id, no "
            f"vocabularies/products.yaml product id, no catalog-class input and no "
            f"release-stripped manifest stem — a typo/renamed/truncated ref or an un-materialized "
            f"product. The card can still fire, but the id is published into run provenance where "
            f"it resolves to nothing."
        )


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
    required_inputs = spec.get("required_inputs", [])
    derived_from = spec.get("derived_from", [])
    if not required_inputs and not derived_from:
        report.add_error(
            "COMPOSED_CARD [required_inputs]: empty required_inputs is only "
            "valid when derived_from is declared (composed-card semantics). "
            "Leaf cards must reference at least one product_id."
        )


def _interpretation_declaration_check(spec: dict, report: ValidationReport) -> None:
    """Layer 2k (interpretation-intent honesty, 2026-09-11) — a card that NO rule keys on must
    declare WHY.

    Every rule in interpretation-rules/*.rules.yaml keys on a `(when.card_id, when.field)` pair, so a
    card only reaches a verdict if some rule names it. 57 of 148 cards are named by no rule. Before
    this check they were ONE undifferentiated bucket: a card that deliberately emits context only was
    indistinguishable from a card that computes a categorical judgement nothing consumes. The health
    feed could not report interpretation debt because it could not see it. The measured split is 35
    rules_pending / 12 informational / 10 descriptive — i.e. 35 cards compute a class about the target
    that no axis reads, which is the real number the bucket was hiding.

    `interpretation:` is REQUIRED exactly when no rule keys on the card, and FORBIDDEN when rules
    exist (the rules are ground truth; a declaration next to them can only contradict them).

    Fail-closed in both directions:
      - `descriptive` on a card that DOES declare outputs.summary_fields_vocabulary is an error, and
        conversely `rules_pending`/`informational` on a card with NO vocabulary is an error. Both
        directions matter because the vocabulary declaration is known-incomplete: two rule-bearing
        cards (subgroup-stratified-dependency, subgroup-stratified-mutation-frequency) carry rules
        keying on fields absent from their declared vocabulary. Deriving the classification from the
        vocabulary alone would silently inherit that hole, which is exactly why this is an AUTHORED
        field and not a computed one.

    Graceful-skip when the rules dir is absent (mirrors the other cross-ref checks) — with no rules
    corpus to read, EVERY card would look rule-less and the check would fire 148 times.
    """
    declared = spec.get("interpretation")
    if declared is not None and declared not in _INTERPRETATION_DECLARATIONS:
        return  # the schema enum already errored; don't double-report
    rule_bearing = _card_modality_signals()
    if rule_bearing is None:
        return  # no interpretation-rules/ in this checkout
    card_id = spec.get("card_id")
    has_rules = card_id in rule_bearing
    has_vocabulary = bool((spec.get("outputs") or {}).get("summary_fields_vocabulary"))

    if has_rules:
        if declared is not None:
            report.add_error(
                f"INTERPRETATION_DECLARED_WITH_RULES [interpretation]: card declares "
                f"interpretation: {declared!r} but interpretation-rules/ already carries rule(s) "
                f"keying on when.card_id == {card_id!r}. The rules are ground truth — drop the "
                f"field. It is required only for cards no rule names."
            )
        return

    if declared is None:
        report.add_warning(
            f"INTERPRETATION_UNDECLARED [interpretation]: no interpretation rule keys on "
            f"when.card_id == {card_id!r}, so this card reaches no verdict, and the card does not "
            f"say whether that is intended. Declare interpretation: rules_pending (its class is a "
            f"substantive target claim an axis should consume — tracked debt), informational (the "
            f"class describes the evidence base or the indication cohort, not the target), or "
            f"descriptive (the card emits no categorical class at all)."
        )
        return

    if declared == "descriptive" and has_vocabulary:
        vocab = sorted((spec["outputs"])["summary_fields_vocabulary"])
        report.add_error(
            f"INTERPRETATION_CONTRADICTED [interpretation]: declared 'descriptive' (emits no "
            f"categorical class) but outputs.summary_fields_vocabulary declares {vocab} — a rule's "
            f"`equals:`/`in:` CAN match those. Use 'informational' if the class deliberately bears "
            f"no verdict, or 'rules_pending' if it owes one."
        )
    elif declared in {"rules_pending", "informational"} and not has_vocabulary:
        report.add_error(
            f"INTERPRETATION_CONTRADICTED [interpretation]: declared {declared!r}, which asserts the "
            f"card emits a categorical class, but outputs.summary_fields_vocabulary is absent — there "
            f"is no enumerated value for a rule to key on. Declare the vocabulary, or use "
            f"'descriptive'."
        )


def _interpretation_summary_field_check(spec: dict, report: ValidationReport) -> None:
    """Layer 2c (best-effort): each interpretation_hints.if SHOULD reference at least one
    declared summary_field. This catches the failure mode where an interpretation rule
    references a field the card doesn't actually emit. Best-effort because a predicate
    may reference helper functions or thresholds only.
    """
    summary_fields = _summary_field_names(spec)
    for i, hint in enumerate(spec.get("interpretation_hints", [])):
        pred = hint.get("if", "")
        referenced_idents = set(re.findall(r"\b([a-z_][a-z0-9_]*)\b", pred))
        # Exclude reserved tokens + literals + threshold-reference (THRESHOLD.foo)
        reserved = {"true", "false", "null", "and", "or", "not", "in", "abs", "THRESHOLD"}
        candidate_fields = referenced_idents - reserved
        if not (candidate_fields & summary_fields):
            # No summary field referenced — likely OK only if predicate references THRESHOLD only
            if "THRESHOLD." not in pred:
                report.add_warning(
                    f"INTERPRETATION [interpretation_hints[{i}].if]: references no declared "
                    f"summary_field ({sorted(summary_fields)}). Predicate: {pred!r}"
                )


def _summary_vocabulary_names(spec: dict) -> set[str]:
    """Every field a card declares in a `summary_fields_vocabulary` — anywhere in the spec (the block
    appears under `outputs` and, on lens-split cards, inside per-lens output blocks). A field here has
    an ENUMERATED value set, which is contract-grounded proof it is categorical, not numeric."""
    names: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "summary_fields_vocabulary" and isinstance(v, dict):
                    names.update(v.keys())
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(spec)
    return names


def _vocabulary_orphans(spec: dict) -> set[str]:
    """The `summary_fields_vocabulary` keys this card declares no field for.

    Legal targets are `outputs.summary_fields` (the card's own scalar surface) OR a key of a declared
    `summary_fields_record_schemas` record — a per-record class needs a vocabulary too, and every one of
    the 17 record schemas in this repo is a plain field map, so the record's keys ARE its field names.
    Kept as one named function because the layer test asserts the waiver list equals this set: two copies
    of the rule would let the check and its own test drift apart.
    """
    vocabulary = _summary_vocabulary_names(spec)
    if not vocabulary:
        return set()
    record_fields: set[str] = set()
    for schema in (spec.get("outputs", {}).get("summary_fields_record_schemas") or {}).values():
        if isinstance(schema, dict):
            record_fields |= set(schema.keys())
    return vocabulary - _summary_field_names(spec) - record_fields


def _summary_vocabulary_declaration_check(spec: dict, report: ValidationReport) -> None:
    """Layer 2i (2026-09-14) — a `summary_fields_vocabulary` key must name a field the card DECLARES.

    A vocabulary entry is the card's enumerated value set for one summary field. If the field it keys is
    declared nowhere — absent from `outputs.summary_fields` AND not a key of any declared
    `summary_fields_record_schemas` record — the enum is attached to nothing and is silently DROPPED:
    `gen_summary_schemas.py` builds `properties` from `summary_fields` unioned with observed keys, so an
    orphan key gets no property and its enum never reaches the generated schema. Nothing downstream can
    notice, because `additionalProperties: true` is mandatory in v1 by that generator's own ruling.

    PROVEN on a committed artifact, not argued: `prism-compound-activity` declares a 3-value enum for
    `metric_source`, and `schemas/methods/prism-compound-activity.summary.schema.json` has 7 properties,
    none of them `metric_source`. The other three orphans have no generated schema yet — the
    summary-schema rollout is opt-in — so their loss is armed rather than shipped.

    Errors, not warnings, for the same reason `_capsule_contract_check` errors: the degradation is
    invisible at every layer downstream of the card, so a warning would never be actioned.

    ★ The RECORD-SCHEMA arm is not a nicety — it is the difference between 4 findings and a 20%
    false-positive rate. The naive invariant (`vocabulary ⊆ summary_fields`) flags 5 cards, but
    `tumor-vs-normal-percentile-crossing-by-subtype.percentile_crossing_class` IS a declared key of that
    card's `per_subgroup_metrics` record, so a per-record class vocabulary is correct there. Validate on
    the whole panel, never on the motivating example: 289 vocabulary keys over 148 cards, 5 naive, 4 real.

    ★ It also closes a composition hole on the skills side. The live emission guard
    (`skills/_skills_common/tests/test_card_output_emission.py`) relaxes its missing-field check for a
    WHOLE card when any vocabulary field emits a data-unavailable marker, and that predicate iterates
    VOCABULARY keys rather than declared field names — so today an ORPHAN key's abstain value can switch
    off the presence check for a card's genuinely declared fields. Once every vocabulary key is a
    declared field, that path cannot be entered from an undeclared one.
    """
    card_id = spec.get("card_id") or ""
    orphans = _vocabulary_orphans(spec)
    waived = KNOWN_VOCABULARY_ORPHANS.get(card_id, set())
    if not orphans and not waived:
        return

    for name in sorted(orphans - waived):
        report.add_error(
            f"VOCABULARY_ORPHAN_FIELD [outputs.summary_fields_vocabulary.{name}]: {name!r} declares an "
            f"enumerated value set but is not a declared summary_field of this card, and is not a key of "
            f"any declared summary_fields_record_schemas record. The enum is attached to nothing — "
            f"gen_summary_schemas builds `properties` from summary_fields + observed keys, so it never "
            f"reaches the generated schema and no consumer can enforce it. Declare the field in "
            f"outputs.summary_fields, declare the record schema it belongs to, or drop the vocabulary "
            f"entry."
        )
    for name in sorted(waived - orphans):
        report.add_error(
            f"VOCABULARY_ORPHAN_FIELD [KNOWN_VOCABULARY_ORPHANS]: the waiver names {name!r} for card "
            f"{card_id!r}, but it is no longer an orphan — the field is now declared (or the vocabulary "
            f"entry is gone). Delete the waiver entry so the set keeps meaning what it says."
        )


def _capsule_contract_check(spec: dict, report: ValidationReport) -> None:
    """Layer 2h (2026-09-12) — the `capsule:` projection contract must name fields the card EMITS.

    A capsule declaration is the card telling evidence_capsule.emit_capsules which of its summary
    fields to project, overriding the emitter's heuristics (alphabetical-first `*_class` for the
    class, an `_ANCHOR_HINTS` substring scan capped at 4 for the numeric anchors). The declaration is
    therefore only as good as its field names: a typo, or a field renamed out from under it, degrades
    SILENTLY back to the heuristic — the capsule still renders, just with the wrong numbers, and no
    test notices. Errors, not warnings, because the failure is invisible downstream.

    Two checks:
      · every declared field (`primary_class`, `categorical_fields[]`, `numeric_anchors[]`) is a
        declared summary_field of THIS card;
      · no `numeric_anchors` entry is a `summary_fields_vocabulary` key. Those fields have an
        enumerated value set, so they are categorical by contract — a number-shaped anchor slot
        holding a class token reads as nonsense, and the author meant `categorical_fields`.
    """
    capsule = spec.get("capsule")
    if not isinstance(capsule, dict):
        return
    summary_fields = _summary_field_names(spec)
    vocabulary = _summary_vocabulary_names(spec)
    declared: list[tuple[str, str]] = []
    if capsule.get("primary_class"):
        declared.append(("primary_class", capsule["primary_class"]))
    for i, f in enumerate(capsule.get("categorical_fields") or []):
        declared.append((f"categorical_fields[{i}]", f))
    for i, f in enumerate(capsule.get("numeric_anchors") or []):
        declared.append((f"numeric_anchors[{i}]", f))
    for where, name in declared:
        if name not in summary_fields:
            report.add_error(
                f"CAPSULE_UNDECLARED_FIELD [capsule.{where}]: {name!r} is not a declared "
                f"summary_field of this card — the capsule would silently fall back to the heuristic"
            )
    for i, name in enumerate(capsule.get("numeric_anchors") or []):
        if name in vocabulary:
            report.add_error(
                f"CAPSULE_CATEGORICAL_AS_NUMERIC [capsule.numeric_anchors[{i}]]: {name!r} declares a "
                f"summary_fields_vocabulary, so it is categorical by contract — use categorical_fields"
            )


def _method_calls(spec: dict) -> list[str]:
    """The `call:` names declared in the card's methods: block."""
    return [m.get("call") for m in spec.get("methods", []) if isinstance(m, dict) and m.get("call")]


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
    tier = spec.get("tier")
    strat = spec.get("subgroup_stratification") or {}
    strat_status = strat.get("status")
    summary_names = _summary_field_names(spec)
    record_schemas = spec.get("outputs", {}).get("summary_fields_record_schemas", {}) or {}
    panorama_fields = (summary_names | set(record_schemas)) & PANORAMA_RECORD_FIELDS
    declares_panorama = bool(panorama_fields)
    calls = _method_calls(spec)
    has_per_sample_reader = any(c in PER_SAMPLE_STRATIFIABLE_CALLS for c in calls)

    # TIER invariant: target-tier cards never stratify.
    if tier == "target":
        if strat:
            report.add_error(
                "GRAIN_TIER [subgroup_stratification]: card is `tier: target` "
                "(scope-invariant target evidence) but declares a "
                "subgroup_stratification block. Target-tier cards never stratify "
                "(two-filter rule, filter 1). Remove the block or change the tier."
            )
        if declares_panorama:
            report.add_error(
                f"GRAIN_TIER [outputs]: card is `tier: target` but declares "
                f"{sorted(panorama_fields)}. Target-tier evidence does not vary by "
                f"subgroup; per-subgroup enumeration is noise on a target-tier card."
            )

    # GRAIN invariant: a live/panorama card must bind a per-sample stratified reader.
    claims_live = (strat_status == "live") or declares_panorama
    if claims_live and not has_per_sample_reader:
        report.add_error(
            f"GRAIN [methods]: card declares a subgroup panorama "
            f"(status={strat_status!r}, panorama field(s)={sorted(panorama_fields)}) "
            f"but its method call(s) {calls} are NOT per-sample stratifiable. A "
            f"panorama must recompute the metric WITHIN each stratum member-set; "
            f"an emit-time aggregate cannot. Bind one of "
            f"{sorted(PER_SAMPLE_STRATIFIABLE_CALLS)}, or set "
            f"subgroup_stratification.status: blocked_needs_per_sample_reader and "
            f"drop the panorama field until a per-sample reader ships."
        )

    # A blocked card must NOT still be declaring the panorama field (the trap).
    if strat_status == "blocked_needs_per_sample_reader" and declares_panorama:
        report.add_error(
            f"GRAIN [outputs]: card is tagged "
            f"subgroup_stratification.status: blocked_needs_per_sample_reader but "
            f"still declares {sorted(panorama_fields)}. A blocked card cannot emit "
            f"per-subgroup records — drop the field until a per-sample reader is bound."
        )


def _blocked_subtype_status_check(spec: dict, report: ValidationReport) -> None:
    """C3 (status-honesty, 2026-08-15) — a `tier: subtype` card whose subgroup_stratification is
    `blocked_needs_per_sample_reader` cannot be LIVE and MUST declare an explicit non-`wired` top-level
    status.

    WHY the `tier: subtype` conjunct (verified against the tree, not the naive predicate): the top-level
    `status` field DEFAULTS to `wired` when omitted (schema), and the required-cards gate treats a
    defaulted/`wired` card as 'must produce'. For a `tier: subtype` card the per-subgroup PANORAMA *is*
    the card's entire identity — if that stratification is blocked, the card produces nothing, so a
    defaulted-wired status is a false liveness claim. But `blocked_needs_per_sample_reader` ALSO appears
    on `tier: indication` POOLED cards (tumor-rna-vs-adjacent, tumor-vs-normal-selectivity,
    tumor-protein-abundance-cptac, ...) where it flags only that the *optional* subgroup FEATURE is
    blocked — those cards are genuinely live and are correctly in required_cards. Keying C3 on the
    subgroup status ALONE would force those live cards non-wired and break the required-cards gate, so the
    check is scoped to `tier: subtype` (identity-is-the-panorama) cards only.
    """
    if spec.get("tier") != "subtype":
        return
    strat = spec.get("subgroup_stratification") or {}
    if strat.get("status") != "blocked_needs_per_sample_reader":
        return
    card_id = spec.get("card_id", "<unknown>")
    # status DEFAULTS to `wired` when omitted (schema) — both omitted and explicit `wired` are the defect.
    status = spec.get("status")
    if status is None or status == "wired":
        report.add_error(
            f"BLOCKED_SUBTYPE_STATUS: card `{card_id}` is `tier: subtype` with "
            f"subgroup_stratification.status: blocked_needs_per_sample_reader — its per-subgroup panorama "
            f"(the card's entire identity) cannot be produced, so it is NOT live. A subtype-tier card "
            f"that cannot emit its panorama MUST declare an explicit non-`wired` top-level status "
            f"(dormant_pending_data / placeholder_not_wired); omitting it defaults to `wired`, which "
            f"falsely claims the card produces and lets the required-cards gate treat it as must-produce."
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
    outputs = spec.get("outputs") or {}
    declares_figure = bool(outputs.get("figure") or outputs.get("figures"))
    if not declares_figure:
        return
    card_id = spec.get("card_id", "<unknown>")
    emitters = _registered_figure_emitters()
    if emitters is None:
        return  # skills repo unreachable — graceful skip, never a false failure
    # a card with a registered live-path emitter is complete.
    if card_id in emitters:
        return
    if card_id in KNOWN_FIGURE_DEBT:
        report.add_warning(
            f"FIGURE_DEBT: card `{card_id}` declares a figure but has NO emitter in "
            f"compose-dashboard CARD_FIGURE_EMITTERS (tracked viz-debt, audit 2026-07-20). "
            f"Add a `_emit_{card_id.replace('-', '_')}` to _figure_emitters.py + register it "
            f"to clear (then drop from KNOWN_FIGURE_DEBT)."
        )
        return
    report.add_error(
        f"FIGURE_DECLARED_NOT_EMITTED: card `{card_id}` declares a figure but has no "
        f"emitter registered in compose-dashboard CARD_FIGURE_EMITTERS and is not on the "
        f"KNOWN_FIGURE_DEBT waiver. Register a figure emitter for it, or add it to "
        f"KNOWN_FIGURE_DEBT with a tracked-debt rationale. New cards must not silently "
        f"declare a figure nothing produces."
    )


def _method_entrypoint_check(spec: dict, report: ValidationReport) -> None:
    """Method-wiring resolution (foundation audit 2026-09-13) — a declared `entrypoint` must EXIST.

    For every `methods[]` entry carrying an `entrypoint`, resolve (module, entrypoint) the way the
    skills generic dispatcher does — `module` else `call` with hyphens→underscores, then the symbol as
    a module-level export — and ERROR when either half does not resolve. Two failure shapes:

      METHOD_MODULE_MISSING   no methods/<module>.py or methods/<module>/__init__.py at all.
      METHOD_ENTRYPOINT_MISSING  the module exists but does not EXPORT the named symbol. The common
        cause is a function defined in a submodule that the package `__init__` never re-exported:
        `getattr(package, fn)` then raises AttributeError even though `grep def fn` finds it.

    ERROR, not warning, on every card regardless of status: an entrypoint is only ever written to be
    called, so a broken one is a defect whether or not the card is live today. Cards with no
    entrypoint declare nothing here and are out of this check's population (their routability is
    validate_card_method_routability's job). Graceful-skips when analysis-methods is absent.
    """
    if not _analysis_methods_available():
        return
    card_id = spec.get("card_id", "<unknown>")
    for i, method in enumerate(spec.get("methods") or []):
        if not isinstance(method, dict) or not method.get("entrypoint"):
            continue
        module_path = _method_module_path(method)
        entrypoint = method["entrypoint"]
        if not module_path:
            report.add_error(
                f"METHOD_MODULE_MISSING [methods[{i}]]: card `{card_id}` declares "
                f"entrypoint {entrypoint!r} with neither `module` nor `call` to resolve it against."
            )
            continue
        bindings = _method_module_bindings(module_path)
        if bindings is None:
            report.add_error(
                f"METHOD_MODULE_MISSING [methods[{i}]]: card `{card_id}` declares "
                f"module {module_path!r} (entrypoint {entrypoint!r}) but analysis-methods has no "
                f"methods/{module_path.replace('.', '/')}.py or .../__init__.py. The live reader "
                f"imports `methods.{module_path}` — this declaration cannot resolve."
            )
            continue
        if bindings is _OPAQUE_MODULE:
            continue  # star-import re-export → export set undeterminable statically, do not judge
        if entrypoint not in bindings:
            report.add_error(
                f"METHOD_ENTRYPOINT_MISSING [methods[{i}]]: card `{card_id}` declares "
                f"entrypoint {entrypoint!r} on module {module_path!r}, but `methods.{module_path}` "
                f"does not export that name. `getattr` on it raises AttributeError. If the function "
                f"lives in a submodule, point `module` at the submodule (e.g. "
                f"'{module_path}.read') or re-export it from the package __init__."
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
    mtype = spec.get("measurement_type")
    card_id = spec.get("card_id", "<unknown>")
    if mtype is None:
        report.add_warning(
            f"MEASUREMENT_TYPE_MISSING: card `{card_id}` does not declare a `measurement_type` "
            f"(DATA_TO_SKILL_CONTRACT Rule 1). Tracked migration debt — pre-existing cards are "
            f"un-migrated; NEW cards must declare their measurement_type + register it in "
            f"vocabularies/measurement_types.yaml."
        )
        return
    registered = _registered_measurement_types()
    if registered is None:
        return  # vocab file absent (net-new / mid-migration checkout) — graceful skip, never false-fail
    if mtype not in registered:
        report.add_error(
            f"MEASUREMENT_TYPE_UNREGISTERED: card `{card_id}` declares measurement_type "
            f"`{mtype}` which is NOT a key in vocabularies/measurement_types.yaml. Register the "
            f"type (per the concordance test, Rule 2) or fix the name — the pull resolver matches "
            f"gates to providers by this key, so an unregistered type is invisible to every gate."
        )
        return

    # C5 (entity_grains CEILING, Rule 5): a card may not advertise an entity_grain its measurement_type's
    # substrate cannot emit. The type declares the capability ceiling; a card SELECTS a grain within it.
    # A grain above the ceiling is a real defect — the runtime query would return an honest data_unavailable
    # for that grain, so promising it on the card is a false capability claim. Only checked when BOTH the
    # card AND the type declare entity_grains (migration-safe: an un-migrated card/type is skipped). Graceful-
    # skip when the vocab is unreadable.
    card_grains = spec.get("entity_grains")
    type_grains_map = _measurement_type_entity_grains()
    if card_grains and type_grains_map is not None:
        ceiling = type_grains_map.get(mtype)
        if ceiling:
            over = set(card_grains) - ceiling
            if over:
                report.add_error(
                    f"ENTITY_GRAINS_CEILING: card `{card_id}` advertises entity_grain(s) {sorted(over)} "
                    f"that its measurement_type `{mtype}` cannot emit (type ceiling = {sorted(ceiling)}, "
                    f"Rule 5). A card must SELECT a grain within its substrate's ceiling — advertising a "
                    f"coarser/finer grain the substrate can't produce is a false capability claim (the "
                    f"runtime returns data_unavailable for it). Drop the grain or widen the type's "
                    f"entity_grains in vocabularies/measurement_types.yaml."
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
    ctx = spec.get("sample_context")
    if ctx is None:
        return
    card_id = spec.get("card_id", "<unknown>")
    mtype = spec.get("measurement_type")
    if not mtype:
        return
    for prefix, expected in _MEASUREMENT_TYPE_CONTEXT_PREFIX.items():
        if mtype.startswith(prefix):
            if ctx != expected:
                report.add_error(
                    f"SAMPLE_CONTEXT_MISMATCH: card `{card_id}` declares sample_context `{ctx}` but "
                    f"its measurement_type `{mtype}` implies `{expected}` (prefix `{prefix}`). The two "
                    f"axes are orthogonal in general, but the type already fixes the sample context — "
                    f"a disagreement would mis-bucket the per-modality sub-verdict. Fix one."
                )
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
    card_id = spec.get("card_id", "<unknown>")
    mtype = spec.get("measurement_type")
    if not mtype:
        return
    relevant = _modality_relevant_types()
    if relevant is None:
        return  # vocab absent — graceful skip
    card_mr = spec.get("modality_relevance")
    if mtype in relevant and not card_mr:
        report.add_warning(
            f"MODALITY_RELEVANCE_MISSING: card `{card_id}` has measurement_type `{mtype}`, which is "
            f"declared modality-relevant in vocabularies/measurement_types.yaml. Consider adding an "
            f"ADVISORY `modality_relevance: [...]` annotation naming the modality-fit gate(s) this "
            f"card informs. NOTE: this is documentation only — evidence routing is driven by the "
            f"per-rule signals{{}} dict, not this field, so omitting it does NOT strand the card."
        )
        return
    # optional consistency: card's declared lenses should be within the type's routing set
    if mtype in relevant and card_mr:
        try:
            with _MEASUREMENT_TYPES_PATH.open() as f:
                type_mr = set(
                    (yaml.safe_load(f) or {}).get("measurement_types", {}).get(mtype, {}).get("modality_relevance")
                    or []
                )
        except (OSError, yaml.YAMLError):
            type_mr = set()
        extra = set(card_mr) - type_mr if type_mr else set()
        if extra:
            report.add_warning(
                f"MODALITY_RELEVANCE_DRIFT: card `{card_id}` declares modality_relevance lens(es) "
                f"{sorted(extra)} not in its measurement_type `{mtype}` routing set {sorted(type_mr)}. "
                f"The card claims a modality gate the type does not route to — align the card + the "
                f"vocab entry."
            )

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
            emitted = sig_map[card_id]  # modalities this card's rules actually emit
            mute = [m for m in card_mr if m not in emitted]  # declared lenses with no signal-carrying rule
            if mute:
                report.add_warning(
                    f"MODALITY_RELEVANCE_MUTE: card `{card_id}` declares modality_relevance {sorted(card_mr)} "
                    f"but its interpretation rules emit signals only for {sorted(emitted) or 'no modality'}; "
                    f"lens(es) {sorted(mute)} are DECLARED-RELEVANT-BUT-MUTE — no rule carries that "
                    f"modality's signal, so the card's evidence cannot route to that modality gate "
                    f"(the real router is the per-rule signals{{}} dict, not the declaration). Add a rule "
                    f"emitting the {sorted(mute)} signal, or drop the lens from modality_relevance."
                )


def _axis_binding_check(spec: dict, report: ValidationReport) -> None:
    """Cross-check the card→skill binding metadata (consumed_by / axis_edge, plan Part 5) against the
    canonical ontology vocabularies/target_profiling_axes.yaml:
      - each consumed_by[].lens names a question `short`, a conditioner id, or the `self_contained`
        sentinel (inline-verdict hosts);
      - axis_edge.reports_into (if present) names a QUESTION short (not a conditioner).
    Graceful-skip if the ontology is absent (mid-migration checkout). role:verdict⇒verdict_source is
    enforced by the JSON Schema; not re-checked here."""
    lens_ok = _ontology_axis_shorts()
    consumed_by = spec.get("consumed_by")
    if isinstance(consumed_by, list) and lens_ok is not None:
        valid_lens = lens_ok | _LENS_SENTINELS
        for i, entry in enumerate(consumed_by):
            if not isinstance(entry, dict):
                continue
            lens = entry.get("lens")
            if lens is not None and lens not in valid_lens:
                report.add_error(
                    f"CONSUMED_BY_LENS: consumed_by[{i}].lens {lens!r} is not a question short, "
                    f"conditioner id, or `self_contained` in target_profiling_axes.yaml"
                )
    axis_edge = spec.get("axis_edge")
    q_only = _question_shorts_only()
    if isinstance(axis_edge, dict) and q_only is not None:
        ri = axis_edge.get("reports_into")
        if ri is not None and ri not in q_only:
            report.add_error(
                f"AXIS_EDGE_REPORTS_INTO: axis_edge.reports_into {ri!r} is not a question short "
                f"in target_profiling_axes.yaml"
            )


def validate_card_file(path: str | Path, schema: dict | None = None) -> ValidationReport:
    """Validate a single card_spec YAML file. Returns a ValidationReport."""
    path = Path(path)
    report = ValidationReport(card_path=str(path))
    if not path.exists():
        report.add_error(f"FILE_NOT_FOUND: {path}")
        return report
    try:
        with path.open() as f:
            spec = yaml.safe_load(f)
    except yaml.YAMLError as e:
        report.add_error(f"YAML_PARSE: {e}")
        return report
    if not isinstance(spec, dict):
        report.add_error(f"YAML_SHAPE: expected mapping at top level, got {type(spec).__name__}")
        return report
    if schema is None:
        schema = _load_schema()
    _structural_check(spec, report, schema)
    if report.ok:  # only run downstream checks if structural is clean
        _threshold_ref_check(spec, report)
        _class_cutpoint_check(spec, report)
        _shallow_predicate_check(spec, report)
        _interpretation_summary_field_check(spec, report)
        _interpretation_declaration_check(spec, report)
        _composed_card_semantics_check(spec, report)
        _required_inputs_product_id_check(spec, report)
        _grain_and_tier_check(spec, report)
        _blocked_subtype_status_check(spec, report)
        _figure_emission_check(spec, report)
        _method_entrypoint_check(spec, report)
        _measurement_type_check(spec, report)
        _sample_context_check(spec, report)
        _modality_relevance_check(spec, report)
        _axis_binding_check(spec, report)
        _capsule_contract_check(spec, report)
        _summary_vocabulary_declaration_check(spec, report)
    return report


def validate_directory(dir_path: str | Path) -> list[ValidationReport]:
    """Validate every *.card.yaml in a directory (recursively). Returns reports list."""
    dir_path = Path(dir_path)
    schema = _load_schema()
    reports = []
    for path in sorted(dir_path.rglob("*.card.yaml")):
        reports.append(validate_card_file(path, schema=schema))
    return reports


def _format_report(report: ValidationReport) -> str:
    lines = [f"  {report.card_path}"]
    for err in report.errors:
        lines.append(f"    [ERROR]   {err}")
    for warn in report.warnings:
        lines.append(f"    [WARNING] {warn}")
    if report.ok and not report.warnings:
        lines.append("    [OK]")
    return "\n".join(lines)


def validate_derived_from_refs(cards_dir: Path) -> list[str]:
    """C1 (composed-card reachability, 2026-08-15): every `derived_from[].card_id` on every card MUST
    resolve to a LIVE card_id in cards/, OR to a historical alias (`from` -> `to` in
    vocabularies/card_id_aliases.yaml whose `to` is a live card). A derived_from pointing at a card that
    does not exist (typo, deleted, or renamed-without-alias) is an ERROR — a composed card whose upstream
    is unresolvable is dead at compose time (the method has no card to read). This is the existence half
    of the reachability check the schema advertises; the field-level 'emits the fields this card reads'
    half remains unimplemented (schema description down-scoped to match). Directory-level (needs the full
    card set + the alias map). No-op on an empty/absent dir."""
    cards_dir = Path(cards_dir)
    live: set[str] = set()
    derived_edges: list[tuple[str, str]] = []  # (referencing_card_id, upstream_card_id)
    for p in sorted(cards_dir.rglob("*.card.yaml")):
        try:
            doc = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError:
            continue
        cid = doc.get("card_id")
        if cid:
            live.add(cid)
        for entry in doc.get("derived_from") or []:
            up = (entry or {}).get("card_id") if isinstance(entry, dict) else None
            if up:
                derived_edges.append((cid or p.name, up))
    aliases = _card_id_aliases()
    problems: list[str] = []
    for referencing, upstream in derived_edges:
        if upstream in live:
            continue
        # alias resolution: an old id is acceptable iff it maps to a live card
        aliased_to = aliases.get(upstream)
        if aliased_to is not None and aliased_to in live:
            continue
        if aliased_to is not None:
            problems.append(
                f"[ERROR] card '{referencing}': derived_from references '{upstream}', a historical alias "
                f"whose target '{aliased_to}' is not a live card in cards/ (stale alias — fix the alias "
                f"target or the reference)."
            )
        else:
            problems.append(
                f"[ERROR] card '{referencing}': derived_from references '{upstream}' which is neither a "
                f"live card_id in cards/ nor a historical alias in vocabularies/card_id_aliases.yaml "
                f"(unresolvable upstream — a composed card cannot read a card that does not exist)."
            )
    return problems


def validate_verdict_card_summary_schema_coverage(cards_dir: Path) -> list[str]:
    """RATCHET (TC1, 2026-09-06): every resolver-consumed (verdict-bearing) card MUST have a committed
    per-card summary output schema at schemas/methods/<card>.summary.schema.json — the method->card
    shape contract. A verdict-bearing card with no shape contract is the drift gap the framework review
    flagged: a method renaming/dropping a summary field the card's rules key on can go undetected and
    silently dead the interpretation rule + resolver rung. The verdict-bearing set is the authoritative
    coverage/card_resolver_consumption.yaml snapshot. Non-verdict-bearing cards remain opt-in. Generate
    a missing schema with: python validators/gen_summary_schemas.py --only <card>. No-op if the snapshot
    is absent (graceful, mirrors the other sibling/cross-ref checks)."""
    cards_dir = Path(cards_dir)
    snapshot = cards_dir.parent / "coverage" / "card_resolver_consumption.yaml"
    methods_dir = cards_dir.parent / "schemas" / "methods"
    if not snapshot.is_file():
        return []
    try:
        verdict_cards = (yaml.safe_load(snapshot.read_text()) or {}).get("resolver_consumed_cards") or []
    except yaml.YAMLError:
        return []
    existing = {p.name[: -len(".card.yaml")] for p in cards_dir.glob("*.card.yaml")}
    problems: list[str] = []
    for c in sorted(verdict_cards):
        if c not in existing:
            continue  # a snapshot entry with no card file is the resolver-consumption validator's concern
        if not (methods_dir / f"{c}.summary.schema.json").is_file():
            problems.append(
                f"[ERROR] SUMMARY_SCHEMA_MISSING: verdict-bearing card '{c}' has no "
                f"schemas/methods/{c}.summary.schema.json (the method->card summary shape contract). "
                f"Generate it: python validators/gen_summary_schemas.py --only {c}"
            )
    return problems


# Annotated exceptions to the shared-measurement_type vocabulary check below. Key = (measurement_type,
# field); value = the WHY. An entry here is a claim that the divergence is INTENDED and the two cards mean
# genuinely different things by their differing tokens — not a mute button. Keep the reason specific
# enough that the next reader can tell whether it still holds.
_VOCABULARY_DIVERGENCE_ALLOWED = {
    ("rna_protein_concordance", "rna_as_biomarker"): (
        "the divergent tokens are SOURCE-SPECIFIC insufficiency reasons — insufficient_paired_models "
        "(cell lines), insufficient_paired_tumors (tumors), indeterminate (single-cell surface). The "
        "graded core (adequate_proxy / partial_proxy / poor_proxy / data_unavailable) IS shared, and "
        "collapsing the reasons would lose which pairing was missing."
    ),
    # ("ici_response_expression", "ici_response_class") was the SECOND entry and is DELETED (2026-09-13):
    # the durable fix shipped rather than the annotation being renewed. methods/imvigor210_ici_response
    # now folds the R derive script's `no_association` onto the canonical `no_ici_association` at the
    # framework boundary (verified live on NECTIN4/BLCA), and ici-response-imvigor210 v1.1.0 declares the
    # aligned token — so the two cards under ici_response_expression once again share one vocabulary and
    # the check passes for the RIGHT reason. Kept as a comment because the deletion is the point: an
    # allowlist entry is a debt, and this is what paying it looks like.
}


def validate_shared_measurement_type_vocabularies(cards_dir: Path) -> list[str]:
    """Two cards under ONE measurement_type must not spell the SAME summary field's vocabulary
    differently (2026-09-12).

    A measurement_type is the DATA_TO_SKILL_CONTRACT unit — the promise that consumers can read one
    claim the same way whichever card carries it. When two cards diverge on a shared field's
    vocabulary, that promise breaks SILENTLY: the divergence lives in two files that are never diffed
    against each other, nothing fails, and the cost lands later on whoever writes the first
    interpretation rule for the field. They pick one spelling, it matches one card, and the rule is
    permanently dead on the other — a dead rule that looks authored, which is the worst failure shape
    the corpus has (an `equals:` that can never be true reads as coverage).

    Found the `ici_response_expression :: ici_response_class` null-class divergence
    (no_ici_association vs no_association), which has since been FIXED at the source (the imvigor210
    reader folds the product token) rather than annotated forever. Genuinely intended divergences go in
    _VOCABULARY_DIVERGENCE_ALLOWED with a reason, so this check stays an ERROR rather than a warning
    nobody reads."""
    cards_dir = Path(cards_dir)
    # measurement_type -> field -> card_id -> frozenset(tokens)
    by_type: dict[str, dict[str, dict[str, frozenset]]] = {}
    for p in sorted(cards_dir.glob("*.card.yaml")):
        try:
            doc = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError:
            continue
        mt, cid = doc.get("measurement_type"), doc.get("card_id")
        if not mt or not cid:
            continue
        vocab = (doc.get("outputs") or {}).get("summary_fields_vocabulary") or {}
        for sf, tokens in vocab.items():
            if not isinstance(tokens, list):
                continue
            by_type.setdefault(str(mt), {}).setdefault(str(sf), {})[str(cid)] = frozenset(map(str, tokens))

    problems: list[str] = []
    for mt in sorted(by_type):
        for sf in sorted(by_type[mt]):
            per_card = by_type[mt][sf]
            if len(per_card) < 2 or len(set(per_card.values())) == 1:
                continue
            allowed = _VOCABULARY_DIVERGENCE_ALLOWED.get((mt, sf))
            shared = frozenset.intersection(*per_card.values())
            detail = "; ".join(
                f"{cid} adds {sorted(tokens - shared)}" for cid, tokens in sorted(per_card.items()) if tokens - shared
            )
            if allowed:
                problems.append(f"[WARNING] VOCABULARY_DIVERGENCE_ALLOWED [{mt}::{sf}]: {detail}. Annotated: {allowed}")
            else:
                problems.append(
                    f"[ERROR] VOCABULARY_DIVERGENCE [{mt}::{sf}]: cards sharing measurement_type "
                    f"'{mt}' declare different vocabularies for the SAME summary sf '{sf}' — "
                    f"{detail} (shared: {sorted(shared)}). A rule keying on one spelling is "
                    f"permanently dead on the other card. Align the tokens (fixing the emitting "
                    f"reader/product if it is the one that is wrong), or — if the divergence is "
                    f"genuinely intended — add ('{mt}', '{sf}') to "
                    f"_VOCABULARY_DIVERGENCE_ALLOWED in validators/validate_cards.py with the reason."
                )
    return problems


def interpretation_debt_summary(cards_dir: Path) -> Optional[str]:
    """The published interpretation-debt meter (2026-09-11). One aggregate line, not one gap per card.

    Deliberately NOT a per-card warning. `rules_pending` is DECLARED debt, and the framework's
    convention for declared debt (KNOWN_FIGURE_DEBT) is that declaring it stops it counting as a gap —
    emitting 35 warnings here would inflate the atlas gap count for cards whose authors have already
    said what they owe. The gap-worthy state is UNDECLARED intent, which
    _interpretation_declaration_check reports per card.

    Returns None when there is nothing to report (no cards, or no rules dir to compare against)."""
    cards_dir = Path(cards_dir)
    rule_bearing = _card_modality_signals()
    if rule_bearing is None:
        return None
    counts: dict[str, int] = {}
    n_rule_less = 0
    for p in sorted(cards_dir.glob("*.card.yaml")):
        try:
            doc = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError:
            continue
        if doc.get("card_id") in rule_bearing:
            continue
        n_rule_less += 1
        counts[str(doc.get("interpretation"))] = counts.get(str(doc.get("interpretation")), 0) + 1
    if not n_rule_less:
        return None
    return (
        f"Interpretation debt: {counts.get('rules_pending', 0)} card(s) compute a categorical class "
        f"about the target that no interpretation rule reads (rules_pending); "
        f"{counts.get('informational', 0)} report the evidence base or the indication cohort "
        f"(informational); {counts.get('descriptive', 0)} emit no class at all (descriptive); "
        f"{counts.get('None', 0)} undeclared. {n_rule_less} of "
        f"{len(list(cards_dir.glob('*.card.yaml')))} cards are named by no rule."
    )


def validate_dashboard_required_cards(cards_dir: Path) -> list[str]:
    """Cross-check (2026-08-12): every dashboard_spec `required_cards` entry must reference a card whose
    `status` is `wired` (or OMITTED, which defaults to wired). A non-wired card
    (placeholder_not_wired / dormant_pending_data) listed in required_cards is an ERROR — it belongs in
    `placeholder_cards`. This keeps `required` meaning 'must produce' rather than 'may be silently
    not_wired' (compose-dashboard's availability_state honestly flags such cards at runtime, but the
    contract should declare them up front). Also warns if a placeholder_cards entry is actually
    status=wired (mislabel). Reads dashboards/ as a sibling of the cards dir; no-op if absent."""
    cards_dir = Path(cards_dir)
    dashboards_dir = cards_dir.parent / "dashboards"
    if not dashboards_dir.is_dir():
        return []
    status_by_card: dict[str, str] = {}
    for p in cards_dir.rglob("*.card.yaml"):
        try:
            doc = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError:
            continue
        cid = doc.get("card_id")
        if cid:
            status_by_card[cid] = doc.get("status", "wired")
    problems: list[str] = []
    for dpath in sorted(dashboards_dir.glob("*.dashboard_spec.yaml")):
        try:
            dash = yaml.safe_load(dpath.read_text()) or {}
        except yaml.YAMLError:
            continue
        did = dash.get("dashboard_id", dpath.name)
        for entry in dash.get("required_cards") or []:
            cid = (entry or {}).get("card_id")
            st = status_by_card.get(cid, "wired")
            if st != "wired":
                problems.append(
                    f"[ERROR] {did}: required_cards references '{cid}' whose card.status is "
                    f"'{st}' (not wired) — move it to placeholder_cards (required_cards must produce)."
                )
        for entry in dash.get("placeholder_cards") or []:
            cid = (entry or {}).get("card_id")
            st = status_by_card.get(cid, "wired")
            if cid in status_by_card and st == "wired":
                problems.append(
                    f"[WARNING] {did}: placeholder_cards lists '{cid}' but its card.status is 'wired' "
                    f"— a wired card belongs in required_cards/optional_cards."
                )
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
    modules_dir = cards_dir.parent / "dashboards" / "modality-modules"
    if not modules_dir.is_dir():
        return []
    real: set[str] = set()
    for p in cards_dir.rglob("*.card.yaml"):
        try:
            d = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError:
            continue
        if d.get("card_id"):
            real.add(d["card_id"])

    def _card_ids(node) -> set[str]:
        out: set[str] = set()
        if isinstance(node, dict):
            cid = node.get("card_id")
            if isinstance(cid, str):
                out.add(cid)
            for v in node.values():
                out |= _card_ids(v)
        elif isinstance(node, list):
            for v in node:
                out |= _card_ids(v)
        return out

    problems: list[str] = []
    for mp in sorted(modules_dir.glob("*.module.yaml")):
        try:
            m = yaml.safe_load(mp.read_text()) or {}
        except yaml.YAMLError:
            continue
        mid = m.get("modality_module", mp.name)
        for cid in sorted(_card_ids(m)):
            if cid not in real:
                problems.append(
                    f"[ERROR] modality-module '{mid}': references card '{cid}' which has no card "
                    f"contract in cards/ (phantom reference — create a card spec or fix the id)."
                )
    return problems


def validate_card_method_routability(cards_dir: Path) -> list[str]:
    """Method-wiring routability (foundation audit 2026-09-13): every card must be READABLE on the live
    path, or DECLARE that it is not.

    A card is routable iff (a) some `methods[]` entry declares an `entrypoint` — the generic dispatcher
    handles it — or (b) its card_id appears in one of the skills `*DISPATCHERS` registries (bespoke /
    panorama / dual-grain). A card that is neither emits nothing on every run, and nothing else in the
    build says so: the required-cards gate reads `status`, the figure check reads emitters, and the
    product-id check reads inputs — none of them ask whether a reader exists AT ALL.

    Three assertions, deliberately in both directions (mirror-guards):
      1. every unroutable card is on KNOWN_UNROUTED_CARDS  → a NEW unwired card is an ERROR,
      2. every KNOWN_UNROUTED_CARDS entry is still unroutable and still a real card → a stale waiver
         is an ERROR, so the waiver cannot outlive the gap it documents,
      3. every waived card declares a non-live `status`  → the exemption is by DECLARATION. A card
         that claims `wired` while being unreadable is the exact false-liveness this check exists for,
         and adding it to the waiver must not launder that claim.

    Skips with a WARNING (never a silent pass) when the skills dispatcher registries are unreachable —
    an isolated CI cannot tell a bespoke-routed card from an orphan, and a check that quietly returns
    nothing in that state is green for the wrong reason.
    """
    cards_dir = Path(cards_dir)
    routed = _dispatcher_routed_card_ids()
    if routed is None:
        return [
            "[WARNING] method routability: SKIPPED — could not read the dispatcher registries at "
            f"{_LIVE_READERS_PATH} (sibling skills repo absent, or no `*{_DISPATCHER_REGISTRY_SUFFIX}` "
            "dict found). Without them a bespoke-routed card is indistinguishable from an unwired one, "
            "so this check abstains rather than reporting phantom gaps. Set CLAUDE_ONCOLOGY_SKILLS_ROOT "
            "to run it."
        ]

    statuses: dict[str, str] = {}
    unroutable: set[str] = set()
    for path in sorted(cards_dir.rglob("*.card.yaml")):
        try:
            spec = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError:
            continue
        card_id = spec.get("card_id")
        if not card_id:
            continue
        # `status` DEFAULTS to `wired` when omitted (schema) — an omitted status is a liveness CLAIM.
        statuses[card_id] = spec.get("status") or "wired"
        has_entrypoint = any(isinstance(m, dict) and m.get("entrypoint") for m in (spec.get("methods") or []))
        if not has_entrypoint and card_id not in routed:
            unroutable.add(card_id)

    problems: list[str] = []
    for card_id in sorted(unroutable - KNOWN_UNROUTED_CARDS):
        problems.append(
            f"[ERROR] card '{card_id}' (status: {statuses.get(card_id)}) is UNROUTABLE: it declares no "
            f"`methods[].entrypoint` (so the generic dispatcher cannot read it) and no "
            f"`*{_DISPATCHER_REGISTRY_SUFFIX}` registry in {_LIVE_READERS_PATH.name} names it (so no "
            f"bespoke reader exists). The card would emit nothing on every run. Declare "
            f"module+entrypoint, add a dispatcher, or — if it is genuinely data-blocked — set a "
            f"non-live status and add it to KNOWN_UNROUTED_CARDS with a reason."
        )
    for card_id in sorted(KNOWN_UNROUTED_CARDS - unroutable):
        if card_id not in statuses:
            problems.append(
                f"[ERROR] KNOWN_UNROUTED_CARDS names '{card_id}', which has no card contract in "
                f"{cards_dir.name}/ — a waiver for a card that no longer exists. Drop the entry."
            )
        else:
            problems.append(
                f"[ERROR] KNOWN_UNROUTED_CARDS names '{card_id}', but it is now ROUTABLE (a reader was "
                f"wired). Remove it from the waiver so the set keeps meaning what it says."
            )
    for card_id in sorted(KNOWN_UNROUTED_CARDS & unroutable):
        status = statuses.get(card_id)
        if status not in _NON_LIVE_STATUSES:
            problems.append(
                f"[ERROR] card '{card_id}' is on KNOWN_UNROUTED_CARDS but declares `status: {status}` — "
                f"an unreadable card claiming liveness. Exemption is by DECLARATION: set one of "
                f"{sorted(_NON_LIVE_STATUSES)} (the waiver documents the gap, it does not excuse the "
                f"false liveness claim)."
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate iter-1 card_spec YAML files against card.schema.json + cross-reference rules."
    )
    parser.add_argument(
        "path",
        help="Path to a single card_spec YAML file, or a directory containing *.card.yaml files (searched recursively).",
    )
    parser.add_argument("--strict-warnings", action="store_true", help="Treat warnings as errors (CI mode).")
    args = parser.parse_args(argv)
    target = Path(args.path)

    if target.is_dir():
        reports = validate_directory(target)
    else:
        reports = [validate_card_file(target)]

    print("validate_cards.py results:")
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
    print(f"Summary: {len(reports)} card_spec(s); {n_ok} clean, {n_err} with errors, {n_warn} with warnings.")

    # Dashboard required_cards ↔ card.status cross-check (2026-08-12): a non-wired card in required_cards
    # is an error (belongs in placeholder_cards). Runs only for a directory target (needs the card set).
    dashboard_problems = (
        (
            validate_dashboard_required_cards(target)
            + validate_modality_module_card_refs(target)
            + validate_derived_from_refs(target)
            + validate_verdict_card_summary_schema_coverage(target)
            + validate_shared_measurement_type_vocabularies(target)
            + validate_card_method_routability(target)
        )
        if target.is_dir()
        else []
    )
    if target.is_dir():
        debt = interpretation_debt_summary(target)
        if debt:
            print()
            print(debt)

    dash_errors = [p for p in dashboard_problems if p.startswith("[ERROR]")]
    dash_warnings = [p for p in dashboard_problems if p.startswith("[WARNING]")]
    if dashboard_problems:
        print()
        print(
            "Cross-card checks (required_cards<->status, modality-module refs, derived_from "
            "reachability, shared-measurement_type vocabularies, method routability):"
        )
        for p in dashboard_problems:
            print(f"  {p}")

    if any(not r.ok for r in reports) or dash_errors:
        return 1
    if args.strict_warnings and (any(r.warnings for r in reports) or dash_warnings):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
