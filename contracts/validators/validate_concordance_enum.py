#!/usr/bin/env python3
"""
validate_concordance_enum.py — governance validator for vocabularies/concordance_class.enum.yaml.

The enum is the roster of `concordance_class` tokens the landed L2b concordance families emit.
Those tokens are PUBLISHED WIRE NAMES, matched as bare strings by evidence_frame.py frozensets,
presence_l3d_story.py, the dependency_claims.py token maps and the question tables' hard-coded
`claim_vector.<island>` provenance_ref paths. This validator is what stops the roster drifting from
the code it claims to describe. Structure arc #2210 Wave-0b; epic #1507.

WHAT THIS ENFORCES (and why each clause exists rather than being a style rule):

  1. SHAPE / STRICT KEYS. Required top-level keys; `enum_id` equals the filename stem minus
     `.enum.yaml`; semver `version`; a `governance` block with every clause non-empty. Keys are
     checked against CLOSED allowlists at every level — a misspelled `dispostion:` would otherwise be
     silently ignored, which is a fail-open on the one discipline this file exists to carry.

  2. THE TWO INDEXES MUST AGREE. `families[*].tokens` and `values[*].families` are the same
     (family, token) pairs indexed both ways, and this clause asserts set equality. The redundancy in
     the YAML is deliberate and this is the reason for it: a token added to one view and forgotten in
     the other is the single most likely way the file goes wrong, and it is invisible to every other
     clause.

  3. RELATION VOCABULARY EQUALITY, NOT SUBSET. The `relations` block must name EXACTLY the closed
     dependence-relation set. Subset would let a relation be dropped from the enum while
     dependence_edges.py still emits it — a coverage GAP that reads as a clean file. (The skills-side
     test asserts the same equality against the live `DEPENDENCE_RELATIONS` frozenset, which is what
     keeps the mirror in validate_property_catalog.py honest too.)

  4. THE DESIGN DECISION IS MECHANISED, NOT PROSE. `contradicts` is admitted as declared-but-not-
     emitted-by-a-family-fold. That position is only worth anything if it cannot be edited into
     something else by accident, so: a relation with `emitted_by_family_folds: false` must carry an
     empty `dispositions` list AND an `admitted_as` AND a witness block naming where it IS reached;
     a relation with `emitted_by_family_folds: true` must carry a non-empty `dispositions` list. And
     the disposition -> relation map is checked in BOTH directions against the relations block's
     inverse, so the two cannot disagree.

  5. NO GATE ON A COUNT. `coverage_dimensions` entries must declare `is_a_gate: false` and carry a
     `rationale`. This is the clause that keeps a measured gap a DIMENSION: an absence-assertion that
     goes vacuous is a design change disguised as a pass, and the way that happens is somebody
     quietly promoting a count to a threshold. `population_floors` ARE gated — their job is
     anti-vacuity, and they are checked to sit at or below the measured values so additive growth
     never reds.

  6. ROSTER CONSISTENCY WITH THE CATALOG. The enum's family keys must equal
     property_catalog/integrated_families.yaml's family keys EXACTLY, and each family's `island_key`,
     `builder` and `builder_function` must equal that file's `integration` values. The enum may not
     introduce a family: families belong to their owning epics (#1730 / #1755 / #1779 / #1812), and a
     family registered here but absent there is a false claim of coverage.

  7. EMISSION SITES MUST EXIST. Each `builder` path must exist on disk and each `builder_function`
     must appear as a top-level `def` in it. This is the referential-integrity analogue of the
     catalog validator's card/field check — see the note on card_field_index below.

  8. DEAD ENTRIES ARE ERRORS. Every declared disposition must be used by at least one token; every
     `documented_not_emitted` token must be ABSENT from `values` (a token that is both is a
     contradiction, and the block's whole purpose is to record the ones that are not emitted); every
     `related_ungoverned_vocabularies` entry must name a field OTHER than `concordance_class` (this
     file governs that field, so anything on it belongs in `values`).

  9. ADDITIVITY (opt-in, `--additive-against <git-ref>`). At TOKEN granularity: no token removed, no
     token's disposition changed, no (family, token) pair removed, and any addition accompanied by a
     version bump. Opt-in because it needs git; when the flag IS passed and the ref cannot be
     resolved the run is RED, never a silent skip — the caller asked for the clause and must not get
     a green without it. The error text is deliberately identical to the catalog validator's so both
     test suites assert the same contract.

WHAT IT DELIBERATELY DOES NOT DO:

  * It does not use `card_field_index()`. The enum contains no card references — its referents are
    builder FUNCTIONS, not measurement fields — so importing the card index would add a clause that
    examines nothing. Clause 7 is the analogue that does apply. Referential integrity against cards
    for these families already runs, on the catalog side, over the same 13 families' arms.
  * It does not check that the tokens in `values` are ACTUALLY emitted. That needs to import the
    builders, and the dependency direction is skills/ -> contracts/, never the reverse. The emitter
    cross-check lives in skills/_skills_common/tests/test_concordance_class_enum_coverage.py, which
    re-derives the token sets from the builders and asserts equality in BOTH directions. This
    validator is the shape half; that test is the truth half. Neither is sufficient alone.
  * Per SK#2091 nothing here is a verdict gate, and nothing here asserts verdict inertness.

Usage:
  python validators/validate_concordance_enum.py
  python validators/validate_concordance_enum.py --enum vocabularies/concordance_class.enum.yaml \
      --families vocabularies/property_catalog/integrated_families.yaml
  python validators/validate_concordance_enum.py --additive-against origin/main
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

import yaml

# Reuse, do not re-implement: Report, the strict-key and non-empty-string helpers, the semver and
# snake_case patterns, the git reader, the repo/contracts anchors and the closed relation set all
# come from the sibling validator. In particular `_git_show` carries the cwd=REPO_ROOT behaviour
# that the additivity clause depends on, and VALID_RELATIONS is the single mirror of
# dependence_edges.py on the contracts side — duplicating it here would create a second one.
from validate_property_catalog import (  # noqa: E402  (path-relative sibling import, see __main__)
    _SEMVER,
    _SNAKE,
    CONTRACTS_ROOT,
    REPO_ROOT,
    VALID_RELATIONS,
    Report,
    _git_show,
    _nonempty_str,
    _strict_keys,
)

TOP_KEYS = {
    "enum_id",
    "version",
    "description",
    "governance",
    "dispositions",
    "relations",
    "coverage_dimensions",
    "population_floors",
    "families",
    "values",
    "documented_not_emitted",
    "related_ungoverned_vocabularies",
}
REQUIRED_TOP_KEYS = (
    "enum_id",
    "version",
    "description",
    "governance",
    "dispositions",
    "relations",
    "coverage_dimensions",
    "population_floors",
    "families",
    "values",
)
GOVERNANCE_CLAUSES = ("role", "versioning", "ownership", "change_discipline", "naming_is_not_uniform")

DISPOSITION_KEYS = {"disposition", "definition", "dependence_relation"}
RELATION_KEYS = {
    "relation",
    "dispositions",
    "emitted_by_family_folds",
    "note",
    "admitted_as",
    "declared_in",
    "emitted_outside_family_folds_by",
    "measurement_scope",
}
WITNESS_KEYS = {"builder", "builder_function", "called_from", "emits_field", "reached_when"}
DIMENSION_KEYS = {"dimension", "measured", "unemitted", "is_a_gate", "rationale"}
FLOOR_KEYS = {"families", "family_token_pairs", "distinct_tokens", "note"}
FAMILY_KEYS = {"island_key", "builder", "builder_function", "tokens", "note"}
VALUE_KEYS = {"value", "disposition", "definition", "families"}
DNE_KEYS = {"token", "named_in", "named_where", "why_not_emitted", "disposition_if_ever_emitted", "action"}
UNGOVERNED_KEYS = {"field", "site", "tokens", "why_out_of_scope"}

# This file governs exactly this field. Anything recorded as "related but ungoverned" on this field
# would be a token that belongs in `values`.
GOVERNED_FIELD = "concordance_class"


def _toplevel_defs(py_path: Path) -> "set[str] | None":
    """Top-level function names in a python module, or None when it cannot be read/parsed."""
    try:
        tree = ast.parse(py_path.read_text())
    except (OSError, SyntaxError):
        return None
    return {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _pairs_from_families(families: dict) -> set:
    out = set()
    for fam, spec in families.items():
        if isinstance(spec, dict):
            for tok in spec.get("tokens") or []:
                if isinstance(tok, str):
                    out.add((fam, tok))
    return out


def _pairs_from_values(values: list) -> set:
    out = set()
    for entry in values:
        if isinstance(entry, dict) and isinstance(entry.get("value"), str):
            for fam in entry.get("families") or []:
                if isinstance(fam, str):
                    out.add((fam, entry["value"]))
    return out


def _check_shape(r: Report, path: Path, doc: dict) -> None:
    _strict_keys(r, path.name, doc, TOP_KEYS)
    for k in REQUIRED_TOP_KEYS:
        if k not in doc:
            r.err(f"{path.name}: missing required top-level key `{k}`")
    stem = path.name.removesuffix(".enum.yaml")
    if doc.get("enum_id") != stem:
        r.err(f"{path.name}: `enum_id` is {doc.get('enum_id')!r} but the filename stem is {stem!r}")
    version = doc.get("version")
    if not isinstance(version, str) or not _SEMVER.match(version):
        r.err(f"{path.name}: `version` must be semver MAJOR.MINOR.PATCH, got {version!r}")
    _nonempty_str(r, path.name, doc, "description")
    gov = doc.get("governance")
    if not isinstance(gov, dict):
        r.err(f"{path.name}: `governance` must be a mapping with {list(GOVERNANCE_CLAUSES)}")
    else:
        _strict_keys(r, f"{path.name}.governance", gov, set(GOVERNANCE_CLAUSES))
        for clause in GOVERNANCE_CLAUSES:
            _nonempty_str(r, f"{path.name}.governance", gov, clause)


def _check_dispositions(r: Report, where: str, doc: dict) -> "dict[str, str]":
    """-> {disposition: dependence_relation}. Errors are recorded, never raised."""
    out: dict[str, str] = {}
    dispositions = doc.get("dispositions")
    if not isinstance(dispositions, list) or not dispositions:
        r.err(f"{where}: `dispositions` must be a non-empty list")
        return out
    for i, d in enumerate(dispositions):
        w = f"{where}.dispositions[{i}]"
        if not isinstance(d, dict):
            r.err(f"{w}: must be a mapping")
            continue
        _strict_keys(r, w, d, DISPOSITION_KEYS)
        _nonempty_str(r, w, d, "definition")
        name = d.get("disposition")
        if not isinstance(name, str) or not _SNAKE.match(name or ""):
            r.err(f"{w}: `disposition` must be snake_case, got {name!r}")
            continue
        if name in out:
            r.err(f"{w}: duplicate disposition `{name}`")
            continue
        rel = d.get("dependence_relation")
        if rel not in VALID_RELATIONS:
            r.err(
                f"{w}: `dependence_relation` {rel!r} is not in the closed dependence_edges.py "
                f"vocabulary {sorted(VALID_RELATIONS)}"
            )
        out[name] = rel
    return out


def _check_relations(r: Report, where: str, doc: dict, disp_relation: "dict[str, str]") -> None:
    block = doc.get("relations")
    if not isinstance(block, dict):
        r.err(f"{where}: `relations` must be a mapping")
        return
    _nonempty_str(r, f"{where}.relations", block, "vocabulary_source")
    _nonempty_str(r, f"{where}.relations", block, "vocabulary_symbol")
    entries = block.get("values")
    if not isinstance(entries, list) or not entries:
        r.err(f"{where}.relations: `values` must be a non-empty list")
        return

    named: dict[str, dict] = {}
    for i, e in enumerate(entries):
        w = f"{where}.relations.values[{i}]"
        if not isinstance(e, dict):
            r.err(f"{w}: must be a mapping")
            continue
        _strict_keys(r, w, e, RELATION_KEYS)
        rel = e.get("relation")
        if not isinstance(rel, str) or not rel:
            r.err(f"{w}: missing `relation`")
            continue
        if rel in named:
            r.err(f"{w}: duplicate relation `{rel}`")
            continue
        named[rel] = e

        emitted = e.get("emitted_by_family_folds")
        if not isinstance(emitted, bool):
            r.err(f"{w}: `emitted_by_family_folds` must be an explicit boolean, got {emitted!r}")
        dispositions = e.get("dispositions")
        if not isinstance(dispositions, list):
            r.err(f"{w}: `dispositions` must be a list (use `[]` for a relation no fold emits)")
            continue
        for d in dispositions:
            if d not in disp_relation:
                r.err(f"{w}: disposition `{d}` is not declared in the `dispositions` block")
        # Clause 4: the design decision, mechanised. Prose can be edited without consequence; these
        # two implications cannot.
        if emitted is True and not dispositions:
            r.err(
                f"{w}: relation `{rel}` claims `emitted_by_family_folds: true` but maps to NO "
                f"disposition — a relation no disposition reaches is not emitted"
            )
        if emitted is False:
            if dispositions:
                r.err(
                    f"{w}: relation `{rel}` claims `emitted_by_family_folds: false` but maps to "
                    f"dispositions {dispositions} — those dispositions ARE reached by family folds"
                )
            _nonempty_str(r, w, e, "admitted_as")
            witness = e.get("emitted_outside_family_folds_by")
            if witness is None:
                r.err(
                    f"{w}: relation `{rel}` is not emitted by a family fold and must carry "
                    f"`emitted_outside_family_folds_by` naming where it IS reached (or be removed "
                    f"from the vocabulary) — an unwitnessed absence is the assertion that goes vacuous"
                )
            elif not isinstance(witness, dict):
                r.err(f"{w}.emitted_outside_family_folds_by: must be a mapping")
            else:
                _strict_keys(r, f"{w}.emitted_outside_family_folds_by", witness, WITNESS_KEYS)
                for k in ("builder", "builder_function", "emits_field", "reached_when"):
                    _nonempty_str(r, f"{w}.emitted_outside_family_folds_by", witness, k)
                _check_emission_site(r, f"{w}.emitted_outside_family_folds_by", witness)

    # Clause 3: EQUALITY, not subset.
    if set(named) != VALID_RELATIONS:
        missing = sorted(VALID_RELATIONS - set(named))
        extra = sorted(set(named) - VALID_RELATIONS)
        r.err(
            f"{where}.relations: must name EXACTLY the closed dependence_edges.py vocabulary "
            f"{sorted(VALID_RELATIONS)} (missing {missing}, unknown {extra}) — a subset would let a "
            f"relation be dropped here while the code still emits it"
        )

    # Clause 4, second direction: the dispositions block and the relations block are inverses.
    inverse: dict[str, str] = {}
    for rel, e in named.items():
        for d in e.get("dispositions") or []:
            inverse[d] = rel
    for disp, rel in sorted(disp_relation.items()):
        if disp not in inverse:
            r.err(
                f"{where}: disposition `{disp}` declares `dependence_relation: {rel}` but no relation "
                f"lists it under `dispositions` — the two indexes must be inverses"
            )
        elif inverse[disp] != rel:
            r.err(
                f"{where}: disposition `{disp}` declares `dependence_relation: {rel}` but the "
                f"relations block files it under `{inverse[disp]}`"
            )


def _check_emission_site(r: Report, where: str, spec: dict) -> None:
    """Clause 7: the builder path exists and the named function is a top-level def in it."""
    builder = spec.get("builder")
    func = spec.get("builder_function")
    if not isinstance(builder, str) or not builder:
        return
    path = (REPO_ROOT / builder).resolve()
    if not path.is_file():
        r.err(f"{where}: `builder` {builder} does not exist on disk — the emission site is unverifiable")
        return
    defs = _toplevel_defs(path)
    if defs is None:
        r.err(f"{where}: `builder` {builder} could not be parsed as python")
        return
    if isinstance(func, str) and func and func not in defs:
        r.err(
            f"{where}: `builder_function` {func} is not a top-level def in {builder} — the roster "
            f"names an emission site that is not there"
        )


def _check_dimensions(r: Report, where: str, doc: dict) -> None:
    dims = doc.get("coverage_dimensions")
    if not isinstance(dims, list) or not dims:
        r.err(f"{where}: `coverage_dimensions` must be a non-empty list")
        return
    for i, d in enumerate(dims):
        w = f"{where}.coverage_dimensions[{i}]"
        if not isinstance(d, dict):
            r.err(f"{w}: must be a mapping")
            continue
        _strict_keys(r, w, d, DIMENSION_KEYS)
        _nonempty_str(r, w, d, "dimension")
        _nonempty_str(r, w, d, "rationale")
        if d.get("measured") is None:
            r.err(f"{w}: missing `measured` — an unmeasured dimension is a null, not a dimension")
        # Clause 5. A dimension is a NUMBER, emitted as data. The moment one becomes a gate it starts
        # asserting an absence, and an absence-assertion that goes vacuous reads as a pass.
        if d.get("is_a_gate") is not False:
            r.err(
                f"{w}: `is_a_gate` must be explicitly `false` (got {d.get('is_a_gate')!r}) — coverage "
                f"gaps here are recorded as DIMENSIONS, never gated; see the relations block"
            )


def _check_floors(r: Report, where: str, doc: dict, n_families: int, pairs: set, tokens: set) -> None:
    floors = doc.get("population_floors")
    if not isinstance(floors, dict):
        r.err(f"{where}: `population_floors` must be a mapping with {sorted(FLOOR_KEYS - {'note'})}")
        return
    _strict_keys(r, f"{where}.population_floors", floors, FLOOR_KEYS)
    measured = {"families": n_families, "family_token_pairs": len(pairs), "distinct_tokens": len(tokens)}
    for key, actual in sorted(measured.items()):
        floor = floors.get(key)
        if not isinstance(floor, int) or isinstance(floor, bool) or floor <= 0:
            r.err(f"{where}.population_floors: `{key}` must be a positive integer, got {floor!r}")
            continue
        if actual < floor:
            r.err(
                f"{where}.population_floors: measured {key}={actual} is BELOW the floor {floor} — "
                f"this file cannot pass vacuously on a population it does not have"
            )
    # `families` is EXACT, not a floor: this file may not introduce a family (clause 6), so a family
    # count above the floor means the enum and the catalog have diverged in a way clause 6 should
    # have caught — and if clause 6 was the thing that broke, this is the backstop.
    if isinstance(floors.get("families"), int) and n_families != floors["families"]:
        r.err(
            f"{where}.population_floors: `families` is exact, not a floor — measured {n_families} "
            f"families against a declared {floors['families']}; a new family belongs to its owning "
            f"epic and must be added to integrated_families.yaml first"
        )


def _check_families(r: Report, where: str, doc: dict, catalog_families: "dict | None") -> dict:
    families = doc.get("families")
    if not isinstance(families, dict) or not families:
        r.err(f"{where}: `families` must be a non-empty mapping")
        return {}
    for fam, spec in sorted(families.items()):
        w = f"{where}.families.{fam}"
        if not _SNAKE.match(fam):
            r.err(f"{w}: family key must be snake_case")
        if not isinstance(spec, dict):
            r.err(f"{w}: must be a mapping")
            continue
        _strict_keys(r, w, spec, FAMILY_KEYS)
        for k in ("island_key", "builder", "builder_function"):
            _nonempty_str(r, w, spec, k)
        tokens = spec.get("tokens")
        if not isinstance(tokens, list) or not tokens:
            r.err(f"{w}: `tokens` must be a non-empty list")
        else:
            seen = set()
            for tok in tokens:
                if not isinstance(tok, str) or not _SNAKE.match(tok or ""):
                    r.err(f"{w}.tokens: {tok!r} must be a snake_case string")
                elif tok in seen:
                    r.err(f"{w}.tokens: duplicate token `{tok}`")
                else:
                    seen.add(tok)
        _check_emission_site(r, w, spec)

    # Clause 6: roster consistency with the catalog.
    if catalog_families is None:
        r.err(
            f"{where}: integrated_families.yaml could not be read — the roster cross-check is this "
            f"validator's load-bearing clause and must not be skipped"
        )
        return families
    if set(families) != set(catalog_families):
        only_enum = sorted(set(families) - set(catalog_families))
        only_catalog = sorted(set(catalog_families) - set(families))
        r.err(
            f"{where}.families: family keys must equal integrated_families.yaml's exactly "
            f"(only here: {only_enum}; only in the catalog: {only_catalog}) — this enum may not "
            f"introduce a family, and a catalog family with no token roster is an unwritten vocabulary"
        )
    for fam in sorted(set(families) & set(catalog_families)):
        spec = families[fam]
        if not isinstance(spec, dict):
            continue
        integration = (catalog_families[fam] or {}).get("integration") or {}
        for key in ("island_key", "builder", "builder_function"):
            mine, theirs = spec.get(key), integration.get(key)
            if theirs is not None and mine != theirs:
                r.err(
                    f"{where}.families.{fam}: `{key}` is {mine!r} but integrated_families.yaml says "
                    f"{theirs!r} — the two registers describe the same family and must agree"
                )
    return families


def _check_values(r: Report, where: str, doc: dict, dispositions: set, family_keys: set) -> "tuple[set, set]":
    """-> (distinct tokens, dispositions actually used)."""
    values = doc.get("values")
    tokens: set = set()
    used: set = set()
    if not isinstance(values, list) or not values:
        r.err(f"{where}: `values` must be a non-empty list")
        return tokens, used
    for i, e in enumerate(values):
        w = f"{where}.values[{i}]"
        if not isinstance(e, dict):
            r.err(f"{w}: must be a mapping")
            continue
        _strict_keys(r, w, e, VALUE_KEYS)
        _nonempty_str(r, w, e, "definition")
        tok = e.get("value")
        if not isinstance(tok, str) or not _SNAKE.match(tok or ""):
            r.err(f"{w}: `value` must be a snake_case token, got {tok!r}")
            continue
        if tok in tokens:
            r.err(f"{w}: duplicate token `{tok}` — `values` is keyed by token; use `families` for reuse")
            continue
        tokens.add(tok)
        disp = e.get("disposition")
        if disp not in dispositions:
            r.err(f"{w}: `disposition` {disp!r} is not declared in the `dispositions` block")
        else:
            used.add(disp)
        fams = e.get("families")
        if not isinstance(fams, list) or not fams:
            r.err(f"{w}: `families` must be a non-empty list — a token no family emits is not a value")
            continue
        seen = set()
        for fam in fams:
            if fam not in family_keys:
                r.err(f"{w}.families: `{fam}` is not a declared family")
            elif fam in seen:
                r.err(f"{w}.families: duplicate family `{fam}`")
            else:
                seen.add(fam)
    for disp in sorted(dispositions - used):
        r.err(
            f"{where}: disposition `{disp}` is declared but no token uses it — a dead disposition "
            f"makes the taxonomy look richer than the vocabulary is"
        )
    return tokens, used


def _check_tail_blocks(r: Report, where: str, doc: dict, dispositions: set, tokens: set) -> None:
    dne = doc.get("documented_not_emitted")
    if dne is not None:
        if not isinstance(dne, list):
            r.err(f"{where}: `documented_not_emitted` must be a list")
        else:
            for i, e in enumerate(dne):
                w = f"{where}.documented_not_emitted[{i}]"
                if not isinstance(e, dict):
                    r.err(f"{w}: must be a mapping")
                    continue
                _strict_keys(r, w, e, DNE_KEYS)
                for k in ("token", "named_in", "why_not_emitted"):
                    _nonempty_str(r, w, e, k)
                tok = e.get("token")
                if isinstance(tok, str) and tok in tokens:
                    r.err(
                        f"{w}: `{tok}` is recorded as documented-but-not-emitted AND present in "
                        f"`values` — it cannot be both; if a builder emits it, it is a value"
                    )
                disp = e.get("disposition_if_ever_emitted")
                if disp is not None and disp not in dispositions:
                    r.err(f"{w}: `disposition_if_ever_emitted` {disp!r} is not a declared disposition")

    ungoverned = doc.get("related_ungoverned_vocabularies")
    if ungoverned is not None:
        if not isinstance(ungoverned, list):
            r.err(f"{where}: `related_ungoverned_vocabularies` must be a list")
            return
        for i, e in enumerate(ungoverned):
            w = f"{where}.related_ungoverned_vocabularies[{i}]"
            if not isinstance(e, dict):
                r.err(f"{w}: must be a mapping")
                continue
            _strict_keys(r, w, e, UNGOVERNED_KEYS)
            for k in ("field", "site", "why_out_of_scope"):
                _nonempty_str(r, w, e, k)
            if e.get("field") == GOVERNED_FIELD:
                r.err(
                    f"{w}: `{GOVERNED_FIELD}` is the field this enum GOVERNS — tokens on it belong in "
                    f"`values`, not in the ungoverned register"
                )
            toks = e.get("tokens")
            if not isinstance(toks, list) or not toks:
                r.err(
                    f"{w}: `tokens` must be a non-empty list — naming a vocabulary without its members "
                    f"records nothing a later sweep can use"
                )


def validate_enum(enum_path: Path, families_path: Path) -> Report:
    r = Report()
    try:
        doc = yaml.safe_load(enum_path.read_text()) or {}
    except (OSError, yaml.YAMLError) as exc:
        r.err(f"{enum_path}: could not be read as YAML: {exc}")
        return r
    if not isinstance(doc, dict):
        r.err(f"{enum_path}: top level must be a mapping")
        return r

    catalog_families: "dict | None" = None
    try:
        cat = yaml.safe_load(families_path.read_text()) or {}
        if isinstance(cat, dict) and isinstance(cat.get("families"), dict):
            catalog_families = cat["families"]
    except (OSError, yaml.YAMLError):
        catalog_families = None

    where = enum_path.name
    _check_shape(r, enum_path, doc)
    disp_relation = _check_dispositions(r, where, doc)
    _check_relations(r, where, doc, disp_relation)
    _check_dimensions(r, where, doc)
    families = _check_families(r, where, doc, catalog_families)
    tokens, _used = _check_values(r, where, doc, set(disp_relation), set(families))
    _check_tail_blocks(r, where, doc, set(disp_relation), tokens)

    # Clause 2: the two indexes are inverses of each other.
    from_families = _pairs_from_families(families)
    from_values = _pairs_from_values(doc.get("values") if isinstance(doc.get("values"), list) else [])
    if from_families != from_values:
        only_fam = sorted(from_families - from_values)
        only_val = sorted(from_values - from_families)
        r.err(
            f"{where}: the two (family, token) indexes disagree — in families[*].tokens but not in "
            f"values[*].families: {only_fam}; in values[*].families but not in families[*].tokens: "
            f"{only_val}. They are the same set indexed both ways and must match exactly"
        )

    _check_floors(r, where, doc, len(families), from_families | from_values, tokens)
    return r


def check_token_additivity(enum_path: Path, ref: str) -> Report:
    """No token removed, no disposition changed, no (family, token) pair removed; additions bump.

    A ref that cannot be resolved is an ERROR, not a skip: the caller explicitly asked for this
    clause, and returning green without having run it is the fail-open this validator exists to
    prevent. The message is deliberately word-for-word the catalog validator's.
    """
    r = Report()
    probe = subprocess.run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        r.err(f"--additive-against: ref `{ref}` does not resolve — refusing to report green on an unrun clause")
        return r

    # `relative_to` needs BOTH sides absolute, and the path normally arrives RELATIVE (preland.sh and
    # CI pass it from cwd contracts/), so resolve() FIRST — without it this raises ValueError and the
    # clause CRASHES instead of running. This is the bug PR-0a shipped and caught; it is repeated here
    # as a comment because the shape is repeated here too.
    try:
        rel = enum_path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        r.err(f"{enum_path}: resolves outside the repo root {REPO_ROOT} — cannot compare against {ref}")
        return r
    prior_text = _git_show(ref, rel)
    if prior_text is None:
        return r  # new file at this ref — nothing to be additive against
    try:
        prior = yaml.safe_load(prior_text) or {}
        current = yaml.safe_load(enum_path.read_text()) or {}
    except yaml.YAMLError as exc:
        r.err(f"{enum_path.name}: could not compare against {ref}: {exc}")
        return r
    if not isinstance(prior, dict) or not isinstance(current, dict):
        return r

    def _by_token(doc: dict) -> dict:
        out = {}
        for e in doc.get("values") or []:
            if isinstance(e, dict) and isinstance(e.get("value"), str):
                out[e["value"]] = e
        return out

    prior_tokens, cur_tokens = _by_token(prior), _by_token(current)
    removed = sorted(set(prior_tokens) - set(cur_tokens))
    if removed:
        r.err(
            f"{enum_path.name}: tokens removed vs {ref}: {removed} — concordance_class tokens are "
            f"PUBLISHED wire names, string-matched by consumers that fail OPEN when a match stops "
            f"happening; migrate by add -> consume -> remove, and a removal needs a MAJOR bump"
        )
    for tok in sorted(set(prior_tokens) & set(cur_tokens)):
        p_disp = prior_tokens[tok].get("disposition")
        c_disp = cur_tokens[tok].get("disposition")
        if p_disp != c_disp:
            r.err(
                f"{enum_path.name}::{tok}: `disposition` changed vs {ref} ({p_disp} -> {c_disp}) — the "
                f"disposition is what the token MEANS, and it selects the dependence relation; a "
                f"different disposition is a different token"
            )
    prior_pairs = _pairs_from_families(prior.get("families") or {}) | _pairs_from_values(prior.get("values") or [])
    cur_pairs = _pairs_from_families(current.get("families") or {}) | _pairs_from_values(current.get("values") or [])
    lost = sorted(prior_pairs - cur_pairs)
    if lost:
        r.err(
            f"{enum_path.name}: (family, token) pairs removed vs {ref}: {lost} — a family losing a "
            f"token it still emits is a coverage gap that reads as a clean file"
        )
    new_tokens = sorted(set(cur_tokens) - set(prior_tokens))
    new_pairs = sorted(cur_pairs - prior_pairs)
    if (new_tokens or new_pairs) and current.get("version") == prior.get("version"):
        r.err(
            f"{enum_path.name}: added tokens {new_tokens} / new (family, token) pairs {new_pairs} "
            f"without bumping `version` (still {current.get('version')!r}) — an addition is at least "
            f"a MINOR bump"
        )
    return r


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--enum", type=Path, default=CONTRACTS_ROOT / "vocabularies" / "concordance_class.enum.yaml")
    ap.add_argument(
        "--families",
        type=Path,
        default=CONTRACTS_ROOT / "vocabularies" / "property_catalog" / "integrated_families.yaml",
    )
    ap.add_argument(
        "--additive-against",
        metavar="GIT_REF",
        default=None,
        help="also enforce token-level additivity against this git ref (RED if the ref does not resolve)",
    )
    args = ap.parse_args(argv)

    print("validate_concordance_enum.py results:")
    if not args.enum.is_file():
        print(f"  [ERROR]   enum file {args.enum} does not exist")
        return 1
    if not args.families.is_file():
        print(
            f"  [ERROR]   {args.families} not found — the roster cross-check against the family "
            f"catalog is this validator's load-bearing clause and must not be skipped"
        )
        return 1

    r = validate_enum(args.enum, args.families)
    for e in r.errors:
        print(f"  [ERROR]   {e}")
    for w in r.warnings:
        print(f"  [WARNING] {w}")
    total_errors = len(r.errors)

    if args.additive_against:
        ar = check_token_additivity(args.enum, args.additive_against)
        for e in ar.errors:
            print(f"  [ERROR]   {e}")
        total_errors += len(ar.errors)

    # The summary re-reads the file, and an unparseable file has ALREADY been reported as an error
    # above. Re-raising here would make the run CRASH rather than FAIL, and preland.sh prints
    # `FAIL <label>` identically for both — so the distinction would be invisible exactly when it
    # matters. Degrade the counts, never the verdict.
    try:
        doc = yaml.safe_load(args.enum.read_text()) or {}
    except yaml.YAMLError:
        doc = {}
    if not isinstance(doc, dict):
        doc = {}
    families = doc.get("families") if isinstance(doc.get("families"), dict) else {}
    values = doc.get("values") if isinstance(doc.get("values"), list) else []
    pairs = _pairs_from_families(families) | _pairs_from_values(values)
    print(
        f"\nSummary: {len(families)} famil(ies), {len(values)} token(s), {len(pairs)} (family, token) "
        f"pair(s); {'OK' if total_errors == 0 else str(total_errors) + ' error(s)'}."
    )
    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    # Sibling import: running this as a script puts validators/ on sys.path[0], so
    # `from validate_property_catalog import ...` resolves. The tests load this module by path and
    # do the same insertion explicitly.
    sys.exit(_main())
