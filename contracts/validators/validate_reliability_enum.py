#!/usr/bin/env python3
"""
validate_reliability_enum.py — governance validator for vocabularies/reliability.enum.yaml.

The enum is the token ROSTER + structural discipline for the derived `reliability` facet (epic #1507;
structure arc #2210; the #2306 rollout, STEP 1 — governance layer, add-only, NO emit). The facet is a
typed, derived, byte-stable-omitted, verdict-INERT object attached (at emit time, steps 2-4) to each
L2a source-property and each L2b source-support arm. This file governs the vocabulary its four
token-bearing fields draw from; it does not attach or emit anything. See the enum's header for the
add->consume->remove sequencing and why the object is minted governed at birth.

WHAT THIS ENFORCES (and why each clause exists rather than being a style rule):

  1. SHAPE / STRICT KEYS. Required top-level keys; `enum_id` equals the filename stem AND the governed
     field name `reliability`; semver `version`; `criterion` and `description` non-empty; a
     `governance` block with every clause (including the two GUARDRAILS `derivation_is_a_projection`
     and `honest_degradation`) non-empty. Keys are checked against CLOSED allowlists at every level — a
     misspelled `datum_kin:` would otherwise be silently ignored, and since the datum-kind drives the
     whole scalar/flag/anchor discipline, the silent ignore would fail OPEN on this file's core rule.

  2. FIELD SHAPE. `fields` is a non-empty list; each entry has strict keys, a snake_case `field`, a
     `datum_kind` / `optionality` / `absent_repr` from closed sets, a boolean `grows`, a `carried_on`
     from a closed set, and a non-empty `rationale`.

  3. DATUM-KIND DISCIPLINE (the core rule). The datum_kind FIXES the rest of the field's shape:
     `integer_anchor` carries NO tokens, `grows: false`, `absent_repr: omit`; `scalar_state` carries a
     non-empty token roster, `grows: false`, `absent_repr` in {omit, sentinel_token} (a CLOSED set is
     not grown additively); `flag_vocab` carries a non-empty token roster, `grows: true`,
     `absent_repr: empty_list` (a list whose absence is `[]`). This is what keeps four independent
     sub-vocabularies from each inventing their own growth/absence semantics.

  4. SENTINEL DISCIPLINE. A field whose absence is a sentinel token (`powered: unmeasured`) MUST declare
     `absent_token` and it MUST be one of that field's tokens — otherwise the absence read strands. A
     field whose absence is an omitted key or an empty list MUST NOT declare `absent_token`, or two
     absence representations would both claim to be authoritative.

  5. TOKEN ROSTER. Each token-bearing field's `tokens` is a non-empty list of `{token, definition}`,
     snake_case tokens, duplicate-free WITHIN the field (identity is (field, token), so a token may
     recur across fields but not within one), each `definition` non-empty. A token with no definition
     is an unauditable wire name.

  6. FLOORS ARE ANTI-VACUITY, NOT DECORATION. `population_floors` must be met. `fields`,
     `token_bearing_fields` and `scalar_state_tokens` are pinned to EQUALITY (the field set and the two
     scalar sets are LOCKED by #2306 — a field or scalar state added or dropped is a shape change to be
     re-ratified, not a silent edit); `flag_vocab_tokens` and `governed_tokens` are `>=` floors (flag
     vocabularies grow additively). At an empty roster the whole test suite would be green while proving
     nothing, which is what the floors forbid.

  7. A DIMENSION MAY NOT CLAIM TO BE A GATE. Each `coverage_dimensions` entry must carry
     `is_a_gate: false` explicitly. Emitters and consumers are 0 at birth BY DESIGN (this is the
     governance layer; emit is steps 2-4). A gate on those zeros would block the arc or force emission
     ahead of its own child issues. Requiring the field present-and-false stops a later session quietly
     promoting a dimension into a gate, and stops this validator being read as enforcing a coverage
     level it deliberately does not enforce.

  8. REFERENTIAL — a catalog `reliability` block draws only GOVERNED tokens (VACUOUS AT BIRTH). When a
     property_catalog entry declares an optional `reliability` block, every token it carries
     (`powered` / `detection_strength` scalars, `confound_flags` / `artifact_flags` list members) must
     be in this enum's roster. Nothing declares one yet, so this clause is vacuous today and is driven
     by planted fixtures in the test — but it is the add->consume->remove enforcement that makes the
     eventual emit safe. The per-block STRUCTURAL admission (strict keys, scalar types) is
     validate_property_catalog.py's RELIABILITY_KEYS clause; this is the TOKEN-VALUE half.

  9. ADDITIVITY (opt-in, `--additive-against GIT_REF`). No field removed, no token removed from any
     field (a removed wire name fails OPEN in every consumer that string-matches it), a token added to a
     `flag_vocab` field requires a `version` bump, and a token added to a `scalar_state` field is
     REFUSED regardless of version (widening a locked closed set is a #2306 re-mint, not additive
     growth). A field's `datum_kind` may not change. An unresolvable ref is an ERROR, never a skip —
     reporting green on an unrun clause is the fail-open this validator exists to prevent.

WHAT IT DELIBERATELY DOES NOT CHECK. It does not check that the facet is EMITTED anywhere (it is not —
this is the governance layer; emit is steps 2-4 and a check would red the whole point). It does not
re-derive `n_effective` or any value (the deriver is step 2 and lives in _skills_common; this file
governs the vocabulary only). And per SK#2091 nothing here is a verdict gate or an inertness proof.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

# Reuse, do not re-implement — the Nth validator in the family, so the arc's rule applies: import from
# the catalog validator rather than growing another copy. `_git_show` in particular carries the
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

GOVERNED_FIELD = "reliability"

TOP_KEYS = {
    "enum_id",
    "version",
    "description",
    "governance",
    "criterion",
    "fields",
    "population_floors",
    "coverage_dimensions",
    "documented_not_emitted",
    "related_ungoverned_vocabularies",
}
REQUIRED_TOP_KEYS = ("enum_id", "version", "description", "governance", "criterion", "fields")
GOVERNANCE_CLAUSES = (
    "role",
    "versioning",
    "ownership",
    "change_discipline",
    "derivation_is_a_projection",
    "honest_degradation",
)

FIELD_KEYS = {
    "field",
    "datum_kind",
    "optionality",
    "absent_repr",
    "absent_token",
    "grows",
    "carried_on",
    "rationale",
    "tokens",
}
TOKEN_KEYS = {"token", "definition"}

VALID_DATUM_KINDS = {"integer_anchor", "scalar_state", "flag_vocab"}
VALID_OPTIONALITY = {"required", "optional"}
VALID_ABSENT_REPR = {"omit", "sentinel_token", "empty_list"}
VALID_CARRIED_ON = {"all", "detection_abundance"}
TOKEN_BEARING_KINDS = {"scalar_state", "flag_vocab"}

FLOOR_KEYS = {
    "fields",
    "token_bearing_fields",
    "scalar_state_tokens",
    "flag_vocab_tokens",
    "governed_tokens",
    "note",
}
DIMENSION_KEYS = {"dimension", "measured", "is_a_gate", "intended_emit_sites", "rationale"}
DNE_KEYS = {"field_or_token", "named_in", "named_where", "why_not_emitted", "action"}
UNGOVERNED_KEYS = {"field", "site", "tokens", "why_out_of_scope"}

# The optional per-property declaration block's key set, mirrored from
# validate_property_catalog.RELIABILITY_KEYS so the referential clause knows what to read. The catalog
# validator owns the STRUCTURAL admission; this constant is only for reading a declared block's tokens.
RELIABILITY_BLOCK_KEYS = {"n_effective", "powered", "confound_flags", "artifact_flags", "detection_strength"}
SCALAR_FIELDS_IN_BLOCK = ("powered", "detection_strength")
FLAG_FIELDS_IN_BLOCK = ("confound_flags", "artifact_flags")


def _powered_token(value) -> "str | None":
    """A runtime `powered` value maps to a governed token: booleans -> 'true'/'false', string as-is."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    return None


def _tokens_of(field_spec: dict) -> "list[str]":
    out = []
    for t in field_spec.get("tokens") or []:
        if isinstance(t, dict) and isinstance(t.get("token"), str):
            out.append(t["token"])
    return out


def _fields_index(doc: dict) -> "dict[str, dict]":
    """{field_name: field_spec} from the `fields` list. Skips malformed entries (clause 2 reports them)."""
    out: dict[str, dict] = {}
    for entry in doc.get("fields") or []:
        if isinstance(entry, dict) and isinstance(entry.get("field"), str):
            out[entry["field"]] = entry
    return out


def _governed_token_sets(doc: dict) -> "dict[str, set]":
    """{field_name: {governed token}} for the token-bearing fields — the referential clause's lookup."""
    out: dict[str, set] = {}
    for name, spec in _fields_index(doc).items():
        if spec.get("datum_kind") in TOKEN_BEARING_KINDS:
            out[name] = set(_tokens_of(spec))
    return out


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
        r.err(f"{where}: `enum_id` must be {GOVERNED_FIELD!r} (the governed facet name), got {doc.get('enum_id')!r}")
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


def _check_fields(r: Report, where: str, doc: dict) -> None:
    """Clauses 2, 3, 4, 5."""
    fields = doc.get("fields")
    if not isinstance(fields, list) or not fields:
        r.err(f"{where}: `fields` must be a non-empty list of field declarations")
        return
    seen: set = set()
    for i, spec in enumerate(fields):
        w = f"{where}.fields[{i}]"
        if not isinstance(spec, dict):
            r.err(f"{w}: must be a mapping")
            continue
        _strict_keys(r, w, spec, FIELD_KEYS)
        name = spec.get("field")
        if not isinstance(name, str) or not _SNAKE.match(name or ""):
            r.err(f"{w}: `field` must be a snake_case token, got {name!r}")
            continue
        w = f"{where}.fields[{name}]"
        if name in seen:
            r.err(f"{w}: duplicate field `{name}` — each field is declared once")
        seen.add(name)
        _nonempty_str(r, w, spec, "rationale")

        kind = spec.get("datum_kind")
        if kind not in VALID_DATUM_KINDS:
            r.err(f"{w}: `datum_kind` must be one of {sorted(VALID_DATUM_KINDS)}, got {kind!r}")
        if spec.get("optionality") not in VALID_OPTIONALITY:
            r.err(f"{w}: `optionality` must be one of {sorted(VALID_OPTIONALITY)}, got {spec.get('optionality')!r}")
        absent_repr = spec.get("absent_repr")
        if absent_repr not in VALID_ABSENT_REPR:
            r.err(f"{w}: `absent_repr` must be one of {sorted(VALID_ABSENT_REPR)}, got {absent_repr!r}")
        if not isinstance(spec.get("grows"), bool):
            r.err(f"{w}: `grows` must be a boolean, got {spec.get('grows')!r}")
        if spec.get("carried_on") not in VALID_CARRIED_ON:
            r.err(f"{w}: `carried_on` must be one of {sorted(VALID_CARRIED_ON)}, got {spec.get('carried_on')!r}")

        # CLAUSE 3 — the datum_kind fixes grows / absent_repr / whether tokens are carried.
        has_tokens = "tokens" in spec and spec.get("tokens") is not None
        if kind == "integer_anchor":
            if has_tokens:
                r.err(f"{w}: `integer_anchor` carries NO `tokens` — it is a projected int, not a vocabulary")
            if spec.get("grows") is not False:
                r.err(f"{w}: `integer_anchor` must be `grows: false`")
            if absent_repr != "omit":
                r.err(f"{w}: `integer_anchor` absence is an OMITTED key (`absent_repr: omit`), got {absent_repr!r}")
        elif kind == "scalar_state":
            if not has_tokens:
                r.err(f"{w}: `scalar_state` requires a non-empty `tokens` roster")
            if spec.get("grows") is not False:
                r.err(f"{w}: `scalar_state` must be `grows: false` — a closed state set is not grown additively")
            if absent_repr not in ("omit", "sentinel_token"):
                r.err(
                    f"{w}: `scalar_state` absence is an omitted key or a sentinel token "
                    f"(`absent_repr` in {{omit, sentinel_token}}), got {absent_repr!r}"
                )
        elif kind == "flag_vocab":
            if not has_tokens:
                r.err(f"{w}: `flag_vocab` requires a non-empty `tokens` roster")
            if spec.get("grows") is not True:
                r.err(f"{w}: `flag_vocab` must be `grows: true` — flag vocabularies grow additively")
            if absent_repr != "empty_list":
                r.err(f"{w}: `flag_vocab` absence is the empty list (`absent_repr: empty_list`), got {absent_repr!r}")

        # CLAUSE 4 — the sentinel discipline.
        tokens = _tokens_of(spec)
        if absent_repr == "sentinel_token":
            at = spec.get("absent_token")
            if not isinstance(at, str) or not at:
                r.err(f"{w}: `absent_repr: sentinel_token` requires a string `absent_token` naming the absence state")
            elif at not in tokens:
                r.err(
                    f"{w}: `absent_token` {at!r} is not one of this field's tokens {sorted(tokens)} — the "
                    f"absence sentinel must be a declared state or the absence read strands"
                )
        elif "absent_token" in spec:
            r.err(
                f"{w}: `absent_token` is only meaningful with `absent_repr: sentinel_token` — an omitted-key "
                f"or empty-list field must not also name a sentinel, or two absence representations conflict"
            )

        # CLAUSE 5 — token roster shape.
        if has_tokens:
            if not isinstance(spec.get("tokens"), list) or not spec["tokens"]:
                r.err(f"{w}: `tokens` must be a non-empty list")
            else:
                local: set = set()
                for j, t in enumerate(spec["tokens"]):
                    wt = f"{w}.tokens[{j}]"
                    if not isinstance(t, dict):
                        r.err(f"{wt}: must be a mapping with {sorted(TOKEN_KEYS)}")
                        continue
                    _strict_keys(r, wt, t, TOKEN_KEYS)
                    tok = t.get("token")
                    if not isinstance(tok, str) or not _SNAKE.match(tok or ""):
                        r.err(f"{wt}: `token` must be a snake_case token, got {tok!r}")
                    else:
                        if tok in local:
                            r.err(f"{w}: duplicate token `{tok}` — a field lists each token once")
                        local.add(tok)
                    _nonempty_str(r, wt, t, "definition")


def _check_floors(r: Report, where: str, doc: dict) -> None:
    """Clause 6."""
    floors = doc.get("population_floors")
    if not isinstance(floors, dict):
        r.err(f"{where}: `population_floors` must be a mapping — the anti-vacuity floors are not optional")
        return
    _strict_keys(r, f"{where}.population_floors", floors, FLOOR_KEYS)

    fields = _fields_index(doc)
    scalar_tokens = sum(len(_tokens_of(s)) for s in fields.values() if s.get("datum_kind") == "scalar_state")
    flag_tokens = sum(len(_tokens_of(s)) for s in fields.values() if s.get("datum_kind") == "flag_vocab")
    token_bearing = sum(1 for s in fields.values() if s.get("datum_kind") in TOKEN_BEARING_KINDS)
    measured = {
        "fields": len(fields),
        "token_bearing_fields": token_bearing,
        "scalar_state_tokens": scalar_tokens,
        "flag_vocab_tokens": flag_tokens,
        "governed_tokens": scalar_tokens + flag_tokens,
    }
    # `>=` floors catch a SHRINKING population (every key).
    for key, got in measured.items():
        want = floors.get(key)
        if not isinstance(want, int):
            r.err(f"{where}.population_floors: `{key}` must be an int, got {want!r}")
            continue
        if got < want:
            r.err(
                f"{where}.population_floors: {key} floor is {want} but only {got} measured — the population "
                f"SHRANK, which is the failure a floor exists to catch"
            )
    # EQUALITY pins: the field set and the two scalar sets are locked by #2306, so an addition that
    # forgot to bump the declared count is drift, not growth.
    for key in ("fields", "token_bearing_fields", "scalar_state_tokens"):
        want = floors.get(key)
        if isinstance(want, int) and want != measured[key]:
            r.err(
                f"{where}.population_floors: `{key}` is {want} but {measured[key]} measured — this count is "
                f"pinned to EQUALITY (the #2306 shape locks it); flag vocabularies grow, this does not"
            )


def _check_tail_blocks(r: Report, where: str, doc: dict) -> None:
    """Clause 7 plus shape checks on the optional trailing blocks."""
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
                _nonempty_str(r, w, d, "intended_emit_sites")
                _nonempty_str(r, w, d, "rationale")
                if not isinstance(d.get("measured"), int):
                    r.err(f"{w}: `measured` must be an int — an unmeasured dimension reports nothing")
                # CLAUSE 7.
                if d.get("is_a_gate") is not False:
                    r.err(
                        f"{w}: `is_a_gate` must be present and exactly `false`. These numbers are REPORTED, "
                        f"never enforced; a dimension that claims to be a gate is either a gate this "
                        f"validator does not implement or a promotion nobody reviewed"
                    )

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
                _nonempty_str(r, w, e, "field_or_token")
                for k in ("named_where", "why_not_emitted", "action"):
                    _nonempty_str(r, w, e, k)
                named_in = e.get("named_in")
                if not isinstance(named_in, list) or not named_in:
                    r.err(
                        f"{w}: `named_in` must be a non-empty list — a facet documented as not-emitted must "
                        f"still say WHERE it will be emitted, or it is hypothetical after all"
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


def _check_catalog_references(r: Report, where: str, doc: dict, catalog_dir: "Path | None") -> None:
    """Clause 8 — a catalog `reliability` block draws only governed tokens. VACUOUS AT BIRTH.

    If the catalog directory cannot be read, that is an ERROR (a cross-file clause must FAIL on an
    unreadable counterpart, never pass quietly). If it reads but no entry declares a `reliability`
    block, the clause is correctly a no-op — nothing consumes the vocabulary yet (add->consume->remove).
    """
    if catalog_dir is None:
        r.err(
            f"{where}: the property_catalog directory could not be read — the referential clause must FAIL "
            f"on an unreadable counterpart rather than pass having examined nothing"
        )
        return
    governed = _governed_token_sets(doc)
    for path in sorted(catalog_dir.glob("*.yaml")):
        try:
            cat = yaml.safe_load(path.read_text()) or {}
        except (OSError, yaml.YAMLError) as exc:
            r.err(f"{where}: could not read catalog file {path.name} for the reliability cross-check: {exc}")
            continue
        if not isinstance(cat, dict):
            continue
        for section in ("properties", "families"):
            entries = cat.get(section)
            if not isinstance(entries, dict):
                continue
            for eid, entry in entries.items():
                if not isinstance(entry, dict):
                    continue
                block = entry.get("reliability")
                if not isinstance(block, dict):
                    continue
                w = f"{path.name}::{eid}.reliability"
                for scalar in SCALAR_FIELDS_IN_BLOCK:
                    if scalar not in block:
                        continue
                    tok = _powered_token(block[scalar]) if scalar == "powered" else block[scalar]
                    if not isinstance(tok, str):
                        r.err(f"{w}: `{scalar}` value {block[scalar]!r} is not a token this enum governs")
                        continue
                    if tok not in governed.get(scalar, set()):
                        r.err(
                            f"{w}: `{scalar}` token {tok!r} is not in the governed roster "
                            f"{sorted(governed.get(scalar, set()))} — an ungoverned token would repeat the "
                            f"valence-marker drift this enum exists to prevent"
                        )
                for flag_field in FLAG_FIELDS_IN_BLOCK:
                    if flag_field not in block:
                        continue
                    values = block[flag_field]
                    if not isinstance(values, list):
                        r.err(f"{w}: `{flag_field}` must be a list of governed tokens, got {values!r}")
                        continue
                    for tok in values:
                        if tok not in governed.get(flag_field, set()):
                            r.err(
                                f"{w}: `{flag_field}` token {tok!r} is not in the governed roster "
                                f"{sorted(governed.get(flag_field, set()))}"
                            )


def _read_catalog_dir(catalog_dir: Path) -> "Path | None":
    """None when the directory is absent — the caller turns that into a loud referential-clause error."""
    return catalog_dir if catalog_dir.is_dir() else None


def validate_enum(enum_path: Path, catalog_dir: Path) -> Report:
    r = Report()
    try:
        doc = yaml.safe_load(enum_path.read_text()) or {}
    except (OSError, yaml.YAMLError) as exc:
        r.err(f"{enum_path}: could not be read as YAML: {exc}")
        return r
    if not isinstance(doc, dict):
        r.err(f"{enum_path}: top level must be a mapping")
        return r

    where = enum_path.name
    _check_shape(r, enum_path, doc)
    _check_fields(r, where, doc)
    _check_floors(r, where, doc)
    _check_tail_blocks(r, where, doc)
    _check_catalog_references(r, where, doc, _read_catalog_dir(catalog_dir))
    return r


def check_additivity(enum_path: Path, ref: str) -> Report:
    """Clause 9. No field or token removed, no datum_kind change, flag additions bump the version, and a
    scalar-state addition is refused as a #2306 re-mint.

    A ref that cannot be resolved is an ERROR, not a skip: the caller explicitly asked for this clause,
    and returning green without having run it is the fail-open this validator exists to prevent. An
    --additive-against clause is VACUOUS when the file is ABSENT at the ref (a new file at birth), and it
    reports CLEAN then — commit first, then re-probe (the clause reads git, not the working tree). The
    test carries a `test_the_enum_EXISTS_at_HEAD_...` guard so that vacuity is a RED with an explanation.
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

    # resolve() FIRST: the path arrives RELATIVE from preland.sh / CI (cwd contracts/), and
    # `relative_to` needs both sides absolute or it raises ValueError and the clause CRASHES instead of
    # running — the bug the sibling validators shipped and caught; the shape is repeated here.
    try:
        rel = enum_path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        r.err(f"--additive-against: {enum_path} is outside the repo root {REPO_ROOT}")
        return r

    old_text = _git_show(ref, rel)
    if old_text is None:
        # NEW at this ref — nothing to be additive against, and that is not a violation (see docstring).
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

    old_fields = _fields_index(old)
    new_fields = _fields_index(new)
    gone = sorted(set(old_fields) - set(new_fields))
    if gone:
        r.err(f"--additive-against {ref}: field(s) REMOVED: {gone}. Removing a governed field is breaking")

    version_bumped = old.get("version") != new.get("version")
    for name in sorted(set(old_fields) & set(new_fields)):
        old_spec, new_spec = old_fields[name], new_fields[name]
        old_kind = old_spec.get("datum_kind")
        new_kind = new_spec.get("datum_kind")
        if old_kind != new_kind:
            r.err(
                f"--additive-against {ref}: field `{name}` changed `datum_kind` {old_kind!r} -> {new_kind!r} — "
                f"the datum kind is part of the field's identity and may not change in place"
            )
        old_toks = set(_tokens_of(old_spec))
        new_toks = set(_tokens_of(new_spec))
        removed = sorted(old_toks - new_toks)
        if removed:
            r.err(
                f"--additive-against {ref}: token(s) {removed} REMOVED from field `{name}`. A removed token is a "
                f"wire-name break — consumers that string-match it fail OPEN. Removal is breaking"
            )
        added = sorted(new_toks - old_toks)
        if added:
            # Which kind is the field NOW? A flag_vocab grows with a bump; a scalar_state does not grow.
            kind = new_kind if new_kind in VALID_DATUM_KINDS else old_kind
            if kind == "scalar_state":
                r.err(
                    f"--additive-against {ref}: token(s) {added} ADDED to scalar_state field `{name}` — widening a "
                    f"LOCKED closed set is a #2306 shape re-mint, not additive growth; refused regardless of version"
                )
            elif not version_bumped:
                r.err(
                    f"--additive-against {ref}: token(s) {added} ADDED to flag field `{name}` but `version` is "
                    f"unchanged at {new.get('version')!r} — a flag-vocabulary addition is at least a MINOR bump"
                )
    return r


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--enum", type=Path, default=CONTRACTS_ROOT / "vocabularies" / "reliability.enum.yaml")
    ap.add_argument(
        "--catalog",
        type=Path,
        default=CONTRACTS_ROOT / "vocabularies" / "property_catalog",
        help="the property_catalog directory whose declared reliability blocks are token-checked (clause 8)",
    )
    ap.add_argument(
        "--additive-against",
        metavar="GIT_REF",
        default=None,
        help="also enforce token-level additivity against this git ref (RED if the ref does not resolve)",
    )
    args = ap.parse_args(argv)

    print("validate_reliability_enum.py results:")
    if not args.enum.is_file():
        print(f"  [ERROR]   enum file {args.enum} does not exist")
        return 1
    if not args.catalog.is_dir():
        print(
            f"  [ERROR]   {args.catalog} not found — the referential cross-check against declared "
            f"reliability blocks is clause 8 and must not be reported green unrun"
        )
        return 1

    r = validate_enum(args.enum, args.catalog)
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

    # The summary re-reads the file; an unparseable file has ALREADY been reported above. Re-raising here
    # would make the run CRASH rather than FAIL, and preland.sh prints `FAIL <label>` identically for
    # both — so the distinction would be invisible exactly when it matters. Degrade counts, never verdict.
    try:
        doc = yaml.safe_load(args.enum.read_text()) or {}
    except yaml.YAMLError:
        doc = {}
    if not isinstance(doc, dict):
        doc = {}
    fields = _fields_index(doc)
    token_sets = _governed_token_sets(doc)
    n_tokens = sum(len(s) for s in token_sets.values())
    print(
        f"\nSummary: {len(fields)} field(s), {len(token_sets)} token-bearing, {n_tokens} governed token(s); "
        f"{'OK' if total_errors == 0 else str(total_errors) + ' error(s)'}."
    )
    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    # Sibling import: running this as a script puts validators/ on sys.path[0], so
    # `from validate_property_catalog import ...` resolves. The tests load this module by path and do the
    # same insertion explicitly.
    sys.exit(_main())
