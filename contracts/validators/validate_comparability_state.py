#!/usr/bin/env python3
"""
validate_comparability_state.py — governance validator for vocabularies/comparability_state.enum.yaml.

The enum records, per landed L2b concordance family, whether that family's arms were comparable as
measured, were MADE comparable by an explicit normalisation, or are not comparable in some reachable
case. It is the machine-readable projection of the `integration.comparability` PROSE that
property_catalog/integrated_families.yaml already carries for all 13 families. Structure arc #2210
Wave-0c; epic #1507.

WHAT THIS ENFORCES (and why each clause exists rather than being a style rule):

  1. SHAPE / STRICT KEYS. Required top-level keys; `enum_id` equals the filename stem minus
     `.enum.yaml`; semver `version`; `criterion` non-empty; a `governance` block with every clause
     non-empty. Keys are checked against CLOSED allowlists at every level — a misspelled `emision:`
     would otherwise be silently ignored, and since clause 5 keys the whole piloted/declared_only
     asymmetry off that field, the silent ignore would fail OPEN on this file's central discipline.

  2. THE TWO INDEXES MUST AGREE. `families[*].states` and `values[*].families` are the same
     (family, state) pairs indexed both ways, and this clause asserts set equality. Mirrors 0b's
     clause 2 for the same reason: a state added to one view and forgotten in the other is the single
     most likely way the file goes wrong, and only a mutual check catches it.

  3. THE FAMILY ROSTER IS PINNED TO THE CATALOG, BOTH DIRECTIONS. Every family declared here must
     exist in integrated_families.yaml and every family there must be declared here. This is the
     load-bearing clause: it is what makes a peer epic adding a 14th L2b family a RED rather than a
     silent coverage gap. An undeclared family is a FALSE ABSENCE — the file would report full
     coverage of a roster it no longer covers.

  4. PER-FAMILY SHAPE. `emission` from a closed set, `states` a non-empty duplicate-free subset of
     the declared values, `basis` non-empty. `basis` is required because a declaration read from
     prose with no citation is unauditable, and 12 of 13 declarations are exactly that.

  5. DECLARATION IS NOT EMISSION (the asymmetry clause). A `piloted` family MUST carry `gate_rule`,
     `per_concordance_class`, `omits_state_for` and `omission_basis`; a `declared_only` family MUST
     NOT carry any of them. A per-claim resolution map on a family whose builder emits nothing would
     claim a resolution no code performs — a false claim of coverage, which this file's governance
     block names as worse than an absent entry.

  6. A PILOTED FAMILY'S MAP IS EXHAUSTIVE OVER ITS `concordance_class` TOKENS, cross-checked against
     concordance_class.enum.yaml. `per_concordance_class` and `omits_state_for` must partition that
     family's token set exactly — disjoint, and together equal to it. This is the clause that honours
     0b's measured result that the unit of identity is (family, token) and never the bare token:
     `single_source_only` is emitted by 5 families and means something different in each, so a map
     keyed on tokens must be resolved WITHIN a family or it is meaningless. It also means a new token
     added to a piloted family by a peer epic is RED here until its comparability is decided, which is
     the point — a new fold outcome with no comparability licence is exactly what must not pass.

  7. NO ORPHAN STATE IN EITHER DIRECTION. The `values` roster and the union of every family's
     `states` must be equal. A value no family declares is dead vocabulary; a state some family
     declares that the roster omits is an undefined token in a governed file.

  8. EVERY STATE HAS AT LEAST ONE DECLARED FAMILY. Separated from clause 7 and named, because it is
     the specific design question this file was built to answer: a three-token enum whose middle
     token no family can ever reach is a design problem, not a vocabulary. `normalized_to_compare` is
     declared by 3 families and emitted by 0, and the distinction between "unemitted" and
     "unreachable" is the whole content of the answer — so it gets its own clause and its own tooth.

  9. FLOORS ARE ANTI-VACUITY, NOT DECORATION. `population_floors` must be met, and `families` is
     pinned to EQUALITY with the catalog so it cannot drift either way. `piloted_families >= 1`
     because every tooth in this file's test suite runs through the one family that emits: at zero
     piloted families the suite would still be green while proving nothing.

 10. A DIMENSION MAY NOT CLAIM TO BE A GATE. Each `coverage_dimensions` entry must carry
     `is_a_gate: false` explicitly. 12 of 13 families emit nothing, and the honest treatment of that
     number is to REPORT it — a gate on it would either block the arc or force emission into builders
     owned by four peer epics. Requiring the field to be present and false stops a later session
     quietly promoting a dimension into a gate, and stops this validator being read as enforcing a
     coverage level it deliberately does not enforce.

 11. ADDITIVITY (opt-in, `--additive-against GIT_REF`). No family removed, no state removed from a
     family, no value removed, no `piloted` family regressed to `declared_only`, and any addition
     requires a `version` bump. An unresolvable ref is an ERROR, never a skip — reporting green on an
     unrun clause is the fail-open this validator exists to prevent.

WHAT IT DELIBERATELY DOES NOT CHECK. It does not check that a declaration MATCHES the catalog's prose
— prose is not machine-comparable, and a clause pretending otherwise (substring matching, say) would
be green-for-the-wrong-reason theatre. The audit trail is `basis`, which a human can check against the
cited block. It also does not check builder identity: this file records none, on purpose (see the
enum's header), and resolving it is concordance_class.enum.yaml's job.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

# Reuse, do not re-implement. Third validator in the family, so the prompt's rule applies: import from
# the two that exist rather than growing a third copy. `_git_show` in particular carries the
# cwd=REPO_ROOT behaviour the additivity clause depends on.
from validate_property_catalog import (  # noqa: E402  (path-relative sibling import, see __main__)
    _SEMVER,
    _SNAKE,
    CONTRACTS_ROOT,
    REPO_ROOT,
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
    "criterion",
    "values",
    "families",
    "population_floors",
    "coverage_dimensions",
    "documented_not_emitted",
    "related_ungoverned_vocabularies",
}
REQUIRED_TOP_KEYS = ("enum_id", "version", "description", "governance", "criterion", "values", "families")
GOVERNANCE_CLAUSES = (
    "role",
    "versioning",
    "ownership",
    "change_discipline",
    "declaration_is_not_emission",
)

VALUE_KEYS = {"value", "definition", "admits", "families"}
FAMILY_KEYS = {
    "emission",
    "states",
    "basis",
    "gate_rule",
    "per_concordance_class",
    "omits_state_for",
    "omission_basis",
    "note",
}
# The keys that only a PILOTED family may carry — clause 5's subject.
PILOT_ONLY_KEYS = ("gate_rule", "per_concordance_class", "omits_state_for", "omission_basis")
VALID_EMISSIONS = {"piloted", "declared_only"}

FLOOR_KEYS = {"families", "family_state_pairs", "distinct_states", "piloted_families", "note"}
DIMENSION_KEYS = {"dimension", "measured", "unemitted", "is_a_gate", "rationale"}
DNE_KEYS = {"state", "named_in", "named_where", "why_not_emitted", "action"}
UNGOVERNED_KEYS = {"field", "site", "tokens", "why_out_of_scope"}

GOVERNED_FIELD = "comparability_state"


def _pairs_from_families(families: dict) -> set:
    """{(family, state)} from the families[*].states view."""
    pairs = set()
    for fam, spec in (families or {}).items():
        if isinstance(spec, dict) and isinstance(spec.get("states"), list):
            for s in spec["states"]:
                if isinstance(s, str):
                    pairs.add((fam, s))
    return pairs


def _pairs_from_values(values: list) -> set:
    """{(family, state)} from the values[*].families inverse view."""
    pairs = set()
    for entry in values or []:
        if not isinstance(entry, dict):
            continue
        val = entry.get("value")
        if not isinstance(val, str):
            continue
        for fam in entry.get("families") or []:
            if isinstance(fam, str):
                pairs.add((fam, val))
    return pairs


def _check_shape(r: Report, path: Path, doc: dict) -> None:
    """Clause 1."""
    where = path.name
    _strict_keys(r, where, doc, TOP_KEYS)
    for k in REQUIRED_TOP_KEYS:
        if k not in doc:
            r.err(f"{where}: missing required top-level key `{k}`")
    stem = path.name[: -len(".enum.yaml")] if path.name.endswith(".enum.yaml") else path.stem
    if doc.get("enum_id") != stem:
        r.err(f"{where}: `enum_id` is {doc.get('enum_id')!r} but the filename says {stem!r} — they must match")
    if doc.get("enum_id") != GOVERNED_FIELD:
        r.err(f"{where}: `enum_id` must be {GOVERNED_FIELD!r} (the governed claim field), got {doc.get('enum_id')!r}")
    ver = doc.get("version")
    if not isinstance(ver, str) or not _SEMVER.match(ver):
        r.err(f"{where}: `version` must be semver MAJOR.MINOR.PATCH, got {ver!r}")
    _nonempty_str(r, where, doc, "description")
    _nonempty_str(r, where, doc, "criterion")
    gov = doc.get("governance")
    if not isinstance(gov, dict):
        r.err(f"{where}: `governance` must be a mapping with {list(GOVERNANCE_CLAUSES)}")
        return
    _strict_keys(r, f"{where}.governance", gov, set(GOVERNANCE_CLAUSES))
    for clause in GOVERNANCE_CLAUSES:
        _nonempty_str(r, f"{where}.governance", gov, clause)


def _check_values(r: Report, where: str, doc: dict) -> set:
    """Clauses 1 (value shape) and 8 (every state has a family). Returns the declared state set."""
    values = doc.get("values")
    if not isinstance(values, list) or not values:
        r.err(f"{where}: `values` must be a non-empty list of state entries")
        return set()
    seen: set = set()
    for i, entry in enumerate(values):
        w = f"{where}.values[{i}]"
        if not isinstance(entry, dict):
            r.err(f"{w}: must be a mapping")
            continue
        _strict_keys(r, w, entry, VALUE_KEYS)
        val = entry.get("value")
        if not isinstance(val, str) or not _SNAKE.match(val or ""):
            r.err(f"{w}: `value` must be a snake_case token, got {val!r}")
            continue
        w = f"{where}.values[{val}]"
        if val in seen:
            r.err(f"{w}: duplicate state `{val}` — the roster must list each state once")
        seen.add(val)
        _nonempty_str(r, w, entry, "definition")
        _nonempty_str(r, w, entry, "admits")
        fams = entry.get("families")
        # CLAUSE 8, named: a state no family declares is not a vocabulary member, it is dead weight.
        # This is the clause that answers "can any family ever reach the middle token?" — and the
        # answer must be yes for all three or the enum is the wrong shape.
        if not isinstance(fams, list) or not fams:
            r.err(
                f"{w}: `families` must be a non-empty list — a state no family declares is unreachable "
                f"vocabulary, and a governed enum may not carry one (see clause 8)"
            )
        elif len(set(fams)) != len(fams):
            dupes = sorted({f for f in fams if fams.count(f) > 1})
            r.err(f"{w}: duplicate famil(ies) in `families`: {dupes}")
    return seen


def _check_families(r: Report, where: str, doc: dict, declared_states: set, catalog_families: "dict | None") -> dict:
    """Clauses 3, 4, 5."""
    families = doc.get("families")
    if not isinstance(families, dict) or not families:
        r.err(f"{where}: `families` must be a non-empty mapping of family -> declaration")
        return {}

    # CLAUSE 3 — pinned to the catalog in BOTH directions.
    if catalog_families is None:
        r.err(
            f"{where}: could not read the family roster from integrated_families.yaml — the roster "
            f"cross-check is this validator's load-bearing clause and must not be skipped"
        )
    else:
        missing = sorted(set(catalog_families) - set(families))
        extra = sorted(set(families) - set(catalog_families))
        if missing:
            r.err(
                f"{where}: {len(missing)} L2b famil(ies) in integrated_families.yaml have NO "
                f"comparability_state declared: {missing}. An undeclared family is a FALSE ABSENCE — "
                f"this file would report coverage of a roster it no longer covers"
            )
        if extra:
            r.err(
                f"{where}: famil(ies) declared here but absent from integrated_families.yaml: {extra}. "
                f"The catalog is authoritative for the roster"
            )

    for fam, spec in families.items():
        w = f"{where}.families[{fam}]"
        if not isinstance(fam, str) or not _SNAKE.match(fam or ""):
            r.err(f"{w}: family key must be a snake_case token")
        if not isinstance(spec, dict):
            r.err(f"{w}: must be a mapping")
            continue
        _strict_keys(r, w, spec, FAMILY_KEYS)
        _nonempty_str(r, w, spec, "basis")

        emission = spec.get("emission")
        if emission not in VALID_EMISSIONS:
            r.err(f"{w}: `emission` must be one of {sorted(VALID_EMISSIONS)}, got {emission!r}")

        states = spec.get("states")
        if not isinstance(states, list) or not states:
            r.err(f"{w}: `states` must be a non-empty list")
            states = []
        else:
            if len(set(states)) != len(states):
                dupes = sorted({s for s in states if states.count(s) > 1})
                r.err(f"{w}: duplicate state(s) in `states`: {dupes}")
            unknown = sorted(set(states) - declared_states)
            if unknown:
                r.err(f"{w}: state(s) {unknown} are not in the `values` roster {sorted(declared_states)}")

        # CLAUSE 5 — the asymmetry. Keys that assert a per-claim resolution belong only to a family
        # whose builder actually performs one.
        present_pilot_keys = [k for k in PILOT_ONLY_KEYS if k in spec]
        if emission == "piloted":
            for k in PILOT_ONLY_KEYS:
                if k not in spec:
                    r.err(
                        f"{w}: `emission: piloted` requires `{k}` — a family that emits the field must "
                        f"declare, per concordance_class, which state it resolves to"
                    )
            _nonempty_str(r, w, spec, "gate_rule")
            _nonempty_str(r, w, spec, "omission_basis")
        elif emission == "declared_only" and present_pilot_keys:
            r.err(
                f"{w}: `emission: declared_only` may NOT carry {present_pilot_keys} — those keys claim a "
                f"per-claim resolution that no code performs. Declaration is not emission"
            )
    return families


def _check_pilot_maps(r: Report, where: str, families: dict, family_tokens: "dict | None") -> None:
    """Clause 6: a piloted family's map partitions that family's `concordance_class` token set."""
    piloted = {f: s for f, s in families.items() if isinstance(s, dict) and s.get("emission") == "piloted"}
    if not piloted:
        return
    if family_tokens is None:
        r.err(
            f"{where}: {sorted(piloted)} declare `emission: piloted` but the `concordance_class` token "
            f"roster could not be read — clause 6 cannot be reported green on an unrun cross-check"
        )
        return
    for fam, spec in piloted.items():
        w = f"{where}.families[{fam}]"
        tokens = family_tokens.get(fam)
        if tokens is None:
            r.err(f"{w}: family absent from concordance_class.enum.yaml, so its token set is unknown")
            continue
        pcc = spec.get("per_concordance_class")
        omits = spec.get("omits_state_for")
        if not isinstance(pcc, dict) or not pcc:
            r.err(f"{w}: `per_concordance_class` must be a non-empty mapping of token -> state list")
            pcc = {}
        if not isinstance(omits, list):
            r.err(f"{w}: `omits_state_for` must be a list of tokens (possibly empty)")
            omits = []

        mapped, omitted = set(pcc), set(omits)
        both = sorted(mapped & omitted)
        if both:
            r.err(
                f"{w}: token(s) {both} appear in BOTH `per_concordance_class` and `omits_state_for` — a "
                f"token either resolves to a state or omits the key, never both"
            )
        covered = mapped | omitted
        unknown = sorted(covered - set(tokens))
        if unknown:
            r.err(
                f"{w}: token(s) {unknown} are not `concordance_class` tokens of family `{fam}` "
                f"(its roster is {sorted(tokens)}). The unit of identity is (family, token)"
            )
        uncovered = sorted(set(tokens) - covered)
        if uncovered:
            r.err(
                f"{w}: token(s) {uncovered} of family `{fam}` have no comparability decision — a piloted "
                f"family's map must be EXHAUSTIVE over its token set, either resolving the token to a "
                f"state or naming it in `omits_state_for`. A fold outcome with no comparability licence "
                f"must not pass"
            )

        declared = set(spec.get("states") or [])
        used: set = set()
        for token, tstates in pcc.items():
            wt = f"{w}.per_concordance_class[{token}]"
            if not isinstance(tstates, list) or not tstates:
                r.err(f"{wt}: must be a non-empty list of states this token may resolve to")
                continue
            if len(set(tstates)) != len(tstates):
                r.err(f"{wt}: duplicate state(s) {sorted({s for s in tstates if tstates.count(s) > 1})}")
            out_of_set = sorted(set(tstates) - declared)
            if out_of_set:
                r.err(f"{wt}: state(s) {out_of_set} not in the family's declared `states` {sorted(declared)}")
            used |= set(tstates)
        unreachable = sorted(declared - used)
        if unreachable:
            r.err(
                f"{w}: state(s) {unreachable} are declared in `states` but no `concordance_class` token "
                f"resolves to them — on a PILOTED family every declared state must be reachable, or the "
                f"declaration overstates what the builder can produce"
            )


def _check_floors(r: Report, where: str, doc: dict, families: dict, pairs: set, states: set, n_catalog) -> None:
    """Clause 9."""
    floors = doc.get("population_floors")
    if not isinstance(floors, dict):
        r.err(f"{where}: `population_floors` must be a mapping — the anti-vacuity floors are not optional")
        return
    _strict_keys(r, f"{where}.population_floors", floors, FLOOR_KEYS)
    n_piloted = sum(1 for s in families.values() if isinstance(s, dict) and s.get("emission") == "piloted")
    measured = {
        "families": len(families),
        "family_state_pairs": len(pairs),
        "distinct_states": len(states),
        "piloted_families": n_piloted,
    }
    for key, got in measured.items():
        want = floors.get(key)
        if not isinstance(want, int):
            r.err(f"{where}.population_floors: `{key}` must be an int, got {want!r}")
            continue
        if got < want:
            r.err(
                f"{where}.population_floors: {key} floor is {want} but only {got} measured — the "
                f"population SHRANK, which is the failure a floor exists to catch"
            )
    # `families` is pinned to EQUALITY, not a floor: clause 3 already forbids drift in both
    # directions, so a floor that merely permitted growth would contradict it.
    if isinstance(n_catalog, int) and isinstance(floors.get("families"), int) and floors["families"] != n_catalog:
        r.err(
            f"{where}.population_floors: `families` is {floors['families']} but integrated_families.yaml "
            f"declares {n_catalog} — the family floor is pinned to EQUALITY with the catalog"
        )
    if isinstance(floors.get("piloted_families"), int) and floors["piloted_families"] < 1:
        r.err(
            f"{where}.population_floors: `piloted_families` floor must be >= 1 — every tooth in this "
            f"file's suite runs through a family that emits, so at zero the suite proves nothing"
        )


def _check_tail_blocks(r: Report, where: str, doc: dict, states: set) -> None:
    """Clause 10 plus shape checks on the optional trailing blocks."""
    dims = doc.get("coverage_dimensions")
    if dims is not None:
        if not isinstance(dims, list) or not dims:
            r.err(f"{where}.coverage_dimensions: must be a non-empty list when present")
        else:
            for i, d in enumerate(dims):
                w = f"{where}.coverage_dimensions[{i}]"
                if not isinstance(d, dict):
                    r.err(f"{w}: must be a mapping")
                    continue
                _strict_keys(r, w, d, DIMENSION_KEYS)
                _nonempty_str(r, w, d, "dimension")
                _nonempty_str(r, w, d, "rationale")
                if not isinstance(d.get("measured"), int):
                    r.err(f"{w}: `measured` must be an int — an unmeasured dimension reports nothing")
                # CLAUSE 10.
                if d.get("is_a_gate") is not False:
                    r.err(
                        f"{w}: `is_a_gate` must be present and exactly `false`. These numbers are "
                        f"REPORTED, never enforced; a dimension that claims to be a gate is either a "
                        f"gate this validator does not implement or a promotion nobody reviewed"
                    )
                for s in d.get("unemitted") or []:
                    if s not in states:
                        r.err(f"{w}: `unemitted` names {s!r}, which is not a declared state")

    dne = doc.get("documented_not_emitted")
    if dne is not None:
        if not isinstance(dne, list) or not dne:
            r.err(f"{where}.documented_not_emitted: must be a non-empty list when present")
        else:
            for i, e in enumerate(dne):
                w = f"{where}.documented_not_emitted[{i}]"
                if not isinstance(e, dict):
                    r.err(f"{w}: must be a mapping")
                    continue
                _strict_keys(r, w, e, DNE_KEYS)
                if e.get("state") not in states:
                    r.err(f"{w}: `state` {e.get('state')!r} is not a declared state")
                for k in ("named_where", "why_not_emitted", "action"):
                    _nonempty_str(r, w, e, k)
                named_in = e.get("named_in")
                if not isinstance(named_in, list) or not named_in:
                    r.err(
                        f"{w}: `named_in` must be a non-empty list of families — a state documented as "
                        f"not-emitted must still say WHERE it is declared, or it is hypothetical after all"
                    )

    ung = doc.get("related_ungoverned_vocabularies")
    if ung is not None:
        if not isinstance(ung, list) or not ung:
            r.err(f"{where}.related_ungoverned_vocabularies: must be a non-empty list when present")
        else:
            for i, e in enumerate(ung):
                w = f"{where}.related_ungoverned_vocabularies[{i}]"
                if not isinstance(e, dict):
                    r.err(f"{w}: must be a mapping")
                    continue
                _strict_keys(r, w, e, UNGOVERNED_KEYS)
                for k in sorted(UNGOVERNED_KEYS):
                    _nonempty_str(r, w, e, k)


def _family_token_index(concordance_enum_path: Path) -> "dict[str, set] | None":
    """{family: {concordance_class token}} from the 0b enum. None when unreadable."""
    try:
        doc = yaml.safe_load(concordance_enum_path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return None
    fams = doc.get("families") if isinstance(doc, dict) else None
    if not isinstance(fams, dict):
        return None
    out: dict[str, set] = {}
    for fam, spec in fams.items():
        if isinstance(spec, dict) and isinstance(spec.get("tokens"), list):
            out[fam] = {t for t in spec["tokens"] if isinstance(t, str)}
    return out or None


def validate_enum(enum_path: Path, families_path: Path, concordance_enum_path: Path) -> Report:
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
    states = _check_values(r, where, doc)
    families = _check_families(r, where, doc, states, catalog_families)
    _check_pilot_maps(r, where, families, _family_token_index(concordance_enum_path))

    # CLAUSE 2 — the two indexes are inverses of each other.
    from_families = _pairs_from_families(families)
    from_values = _pairs_from_values(doc.get("values") if isinstance(doc.get("values"), list) else [])
    if from_families != from_values:
        only_fam = sorted(from_families - from_values)
        only_val = sorted(from_values - from_families)
        r.err(
            f"{where}: the two (family, state) indexes disagree — in families[*].states but not in "
            f"values[*].families: {only_fam}; in values[*].families but not in families[*].states: "
            f"{only_val}. They are the same set indexed both ways and must match exactly"
        )

    # CLAUSE 7 — no orphan state in either direction.
    from_fam_states = {s for _f, s in from_families}
    orphan_values = sorted(states - from_fam_states)
    undeclared = sorted(from_fam_states - states)
    if orphan_values:
        r.err(f"{where}: state(s) {orphan_values} are in the `values` roster but no family declares them")
    if undeclared:
        r.err(f"{where}: state(s) {undeclared} are declared by a family but missing from the `values` roster")

    _check_tail_blocks(r, where, doc, states)
    _check_floors(
        r,
        where,
        doc,
        families,
        from_families | from_values,
        states,
        len(catalog_families) if isinstance(catalog_families, dict) else None,
    )
    return r


def check_additivity(enum_path: Path, ref: str) -> Report:
    """Clause 11. No family or state removed, no piloted regression; additions bump the version.

    A ref that cannot be resolved is an ERROR, not a skip: the caller explicitly asked for this
    clause, and returning green without having run it is the fail-open this validator exists to
    prevent. The message is deliberately word-for-word the sibling validators'.
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

    # resolve() FIRST: the path normally arrives RELATIVE (preland.sh and CI pass it from cwd
    # contracts/), and `relative_to` needs both sides absolute or it raises ValueError and the clause
    # CRASHES instead of running. That is the bug PR-0a shipped and caught; the shape is repeated here
    # so the comment is too.
    try:
        rel = enum_path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        r.err(f"--additive-against: {enum_path} is outside the repo root {REPO_ROOT}")
        return r

    old_text = _git_show(ref, rel)
    if old_text is None:
        # The file is NEW at this ref. Nothing to be additive against, and that is not a violation.
        return r
    try:
        old = yaml.safe_load(old_text) or {}
    except yaml.YAMLError as exc:
        r.err(f"--additive-against {ref}: the committed {rel} is not parseable YAML ({exc})")
        return r
    try:
        new = yaml.safe_load(enum_path.read_text()) or {}
    except (OSError, yaml.YAMLError) as exc:
        r.err(f"--additive-against {ref}: the working {rel} is not parseable YAML ({exc})")
        return r
    if not isinstance(old, dict) or not isinstance(new, dict):
        r.err(f"--additive-against {ref}: both revisions of {rel} must be mappings")
        return r

    old_fams = old.get("families") if isinstance(old.get("families"), dict) else {}
    new_fams = new.get("families") if isinstance(new.get("families"), dict) else {}
    gone = sorted(set(old_fams) - set(new_fams))
    if gone:
        r.err(f"--additive-against {ref}: famil(ies) REMOVED from the roster: {gone}. Removal is breaking")

    old_pairs = _pairs_from_families(old_fams)
    new_pairs = _pairs_from_families(new_fams)
    lost = sorted(old_pairs - new_pairs)
    if lost:
        r.err(
            f"--additive-against {ref}: (family, state) declaration(s) REMOVED: {lost}. Dropping a state "
            f"from a family says a case that was reachable no longer is — additive-only forbids it"
        )

    old_states = {e.get("value") for e in (old.get("values") or []) if isinstance(e, dict)}
    new_states = {e.get("value") for e in (new.get("values") or []) if isinstance(e, dict)}
    dropped = sorted(s for s in old_states - new_states if isinstance(s, str))
    if dropped:
        r.err(f"--additive-against {ref}: state(s) REMOVED from the roster: {dropped}. Removal is breaking")

    for fam, spec in old_fams.items():
        if not isinstance(spec, dict) or spec.get("emission") != "piloted":
            continue
        new_spec = new_fams.get(fam)
        if isinstance(new_spec, dict) and new_spec.get("emission") != "piloted":
            r.err(
                f"--additive-against {ref}: family `{fam}` regressed from `piloted` to "
                f"{new_spec.get('emission')!r} — un-piloting a family removes emitted governed surface"
            )

    added_pairs = new_pairs - old_pairs
    added_states = new_states - old_states
    added_fams = set(new_fams) - set(old_fams)
    if (added_pairs or added_states or added_fams) and old.get("version") == new.get("version"):
        r.err(
            f"--additive-against {ref}: additions present (+{len(added_fams)} famil(ies), "
            f"+{len(added_states)} state(s), +{len(added_pairs)} pair(s)) but `version` is unchanged at "
            f"{new.get('version')!r} — an additive change is a MINOR bump"
        )
    return r


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--enum", type=Path, default=CONTRACTS_ROOT / "vocabularies" / "comparability_state.enum.yaml")
    ap.add_argument(
        "--families",
        type=Path,
        default=CONTRACTS_ROOT / "vocabularies" / "property_catalog" / "integrated_families.yaml",
    )
    ap.add_argument(
        "--concordance-enum",
        type=Path,
        default=CONTRACTS_ROOT / "vocabularies" / "concordance_class.enum.yaml",
        help="the concordance_class roster a piloted family's per_concordance_class map is checked against",
    )
    ap.add_argument(
        "--additive-against",
        metavar="GIT_REF",
        default=None,
        help="also enforce declaration-level additivity against this git ref (RED if the ref does not resolve)",
    )
    args = ap.parse_args(argv)

    print("validate_comparability_state.py results:")
    if not args.enum.is_file():
        print(f"  [ERROR]   enum file {args.enum} does not exist")
        return 1
    if not args.families.is_file():
        print(
            f"  [ERROR]   {args.families} not found — the roster cross-check against the family "
            f"catalog is this validator's load-bearing clause and must not be skipped"
        )
        return 1
    if not args.concordance_enum.is_file():
        print(
            f"  [ERROR]   {args.concordance_enum} not found — a piloted family's per-token map is "
            f"checked against it, and clause 6 must not be reported green unrun"
        )
        return 1

    r = validate_enum(args.enum, args.families, args.concordance_enum)
    for e in r.errors:
        print(f"  [ERROR]   {e}")
    for w in r.warnings:
        print(f"  [WARNING] {w}")
    total_errors = len(r.errors)

    if args.additive_against:
        ar = check_additivity(args.enum, args.additive_against)
        for e in ar.errors:
            print(f"  [ERROR]   {e}")
        total_errors += len(ar.errors)

    # The summary re-reads the file, and an unparseable file has ALREADY been reported above.
    # Re-raising here would make the run CRASH rather than FAIL, and preland.sh prints `FAIL <label>`
    # identically for both — so the distinction would be invisible exactly when it matters. Degrade
    # the counts, never the verdict.
    try:
        doc = yaml.safe_load(args.enum.read_text()) or {}
    except yaml.YAMLError:
        doc = {}
    if not isinstance(doc, dict):
        doc = {}
    families = doc.get("families") if isinstance(doc.get("families"), dict) else {}
    values = doc.get("values") if isinstance(doc.get("values"), list) else []
    pairs = _pairs_from_families(families) | _pairs_from_values(values)
    piloted = sorted(f for f, s in families.items() if isinstance(s, dict) and s.get("emission") == "piloted")
    print(
        f"\nSummary: {len(families)} famil(ies), {len(values)} state(s), {len(pairs)} (family, state) "
        f"pair(s), {len(piloted)} piloted ({', '.join(piloted) or 'none'}); "
        f"{'OK' if total_errors == 0 else str(total_errors) + ' error(s)'}."
    )
    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    # Sibling import: running this as a script puts validators/ on sys.path[0], so
    # `from validate_property_catalog import ...` resolves. The tests load this module by path and do
    # the same insertion explicitly.
    sys.exit(_main())
