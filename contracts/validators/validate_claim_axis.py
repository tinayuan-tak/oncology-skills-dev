#!/usr/bin/env python3
"""
validate_claim_axis.py — governance validator for vocabularies/claim_axis.enum.yaml.

The registry records one entry per `(skill, axis_key)` for every headline claim axis the fleet's 15
skills declare, plus the catalogued biological properties each axis `resolves:`. Structure arc #2210
Wave-0d; epic #1507. It exists because "which skills ask the same question" was previously answerable
only by reading 15 `run.py` files, and because the answer is NOT "the ones sharing a token":
`NORMAL_TISSUE` / `SAFE` / `SAFETY` are three names for one property and `DEP` is one name for two.

WHAT THIS ENFORCES (and why each clause exists rather than being a style rule):

  1. SHAPE / STRICT KEYS. Required top-level keys; `enum_id` equals the filename stem minus
     `.enum.yaml` and equals `claim_axis`; semver `version`; non-empty `description` and `criterion`; a
     `governance` block with every clause non-empty. Keys are checked against CLOSED allowlists at
     every level. A misspelled `resolves_pendng:` would otherwise be silently ignored — and since
     clause 5 keys the whole resolved/pending asymmetry off that field, the silent ignore would fail
     OPEN on this file's central discipline.

  2. THE PAIR IS THE IDENTITY, AND IT IS UNIQUE. `(skill, axis_key)` must be duplicate-free across
     `axes`, and every `skill` must be a real `skills/<name>/` directory. This is the direct
     transposition of Wave-0b's measured result that `single_source_only` is emitted by 5 concordance
     families and means a different comparison in each: the bare token is not an identity. Measured
     here rather than assumed — 61 axes over 60 distinct tokens, one collision.

  3. THE THREE VIEWS MUST AGREE. `axes`, the `skills:` inverse index (gate + display order) and the
     `properties:` inverse index (property -> axes) are the same facts indexed three ways, and this
     clause asserts set equality between each index and the primary roster. Mirrors 0b clause 2 and 0c
     clause 2 for the same reason: an entry added to one view and forgotten in another is the single
     most likely way the file goes wrong, and only a mutual check catches it.

  4. `resolves:` CITES THE QUALIFIED FORM AND IT RESOLVES. Every id must match
     `<catalog_id>.<entry_id>` and name a real entry of that catalog file. The BARE form is rejected
     outright with its own message, because the catalog namespace genuinely collides: 27 entries, only
     25 distinct bare ids, since `selectivity` and `subtype_restriction` each name one `l2a_property`
     in expression.yaml AND one unrelated `l2b_family` in integrated_families.yaml. Guessing would
     produce a confident wrong join for 2 of 27 entries.

  5. DECLARATION IS NOT DEFERRAL (the asymmetry clause). An axis with a non-empty `resolves:` must NOT
     carry `resolves_pending:`; an axis with an empty `resolves:` MUST carry one, non-empty. 47 of 61
     axes are in the second state, and an unexplained empty list is indistinguishable from an
     oversight — which is how a registry starts reporting coverage it does not have.

  6. `resolves:` IS PINNED TO THE CATALOG'S `consumers:` BLOCK, BOTH DIRECTIONS, WITH ABSENCE A
     FIRST-CLASS MEMBER. The catalog already declares, per property, which `(skill, axis_key)` consumes
     it. This clause reconciles that against `resolves:` as a set of pairs and asserts EQUALITY — a
     property naming an axis that does not cite it back is a FALSE ABSENCE in this file, and an axis
     citing a property that does not name it is an unsourced claim. Critically the comparison runs over
     the FULL axis population with the empty set as a real value, not "check it when a `resolves:` is
     present": 0c proved that a conditional check is structurally blind to the case where a key should
     have been there and was not.

  7. THE COLLISION DECLARATION IS RECONCILED AGAINST THE MEASURED COLLISIONS, BOTH DIRECTIONS, AGAIN
     WITH ABSENCE FIRST-CLASS. An `axis_key` used by more than one skill MUST carry `collides_with:`
     naming exactly the other pairs, and an axis_key used by only one skill must NOT carry it. Derived
     from the roster, never from a hand-maintained list — and `documented_collisions` must name exactly
     the measured colliding tokens. A collision is LEGAL and DECLARED here, never resolved: resolving
     one means renaming a `claim_vector.<axis>` wire name, which is #2229's add -> consume -> remove
     work and a silent-degradation risk this file may not take.

  8. FLOORS ARE ANTI-VACUITY, NOT DECORATION. `population_floors` must be met. `skills` is a FLOOR and
     deliberately NOT pinned to equality: contracts/ may not read skills' `HeadlineSpec`s (the
     dependency direction is skills/ -> contracts/), so the equality half lives in
     skills/_skills_common/tests/test_claim_axis_registry_coverage.py. Naming that split here is part
     of the clause: a reader who assumes this validator holds the roster to equality would think the
     registry is complete when it is only self-consistent.

  9. A DIMENSION MAY NOT CLAIM TO BE A GATE. Each `coverage_dimensions` entry must carry
     `is_a_gate: false` explicitly, an int `measured` and an int `total` with `measured <= total`. 47 of
     61 axes resolve no property because five l2a catalogs are Wave-1 items owned by #2211-#2214 and the
     hands-on safety seed. The honest treatment of that number is to REPORT it; a gate would block this
     item behind four others or force catalog entries invented ahead of their measurement. Requiring the
     field present and false stops a later session quietly promoting a dimension into a gate.

 10. ADDITIVITY (opt-in, `--additive-against GIT_REF`). No `(skill, axis_key)` removed, no `resolves:`
     id removed from an axis, no `label` changed, no `critical` flag flipped, and any addition requires
     a `version` bump. `(skill, axis_key)` pairs and qualified property ids are PUBLISHED names. An
     unresolvable ref is an ERROR, never a skip — reporting green on an unrun clause is the fail-open
     this validator exists to prevent.

WHAT IT DELIBERATELY DOES NOT CHECK. It does not compare `label`, `critical` or the axis roster against
the real `HeadlineSpec`s, and it must not: contracts/ reading skills' code inverts the dependency
direction. Every one of those comparisons lives in the skills-side coverage test, which re-derives them
from the ASTs fail-loud. It also does not check `informs:` wording against `CLAIM_INFORMS` — those are
two different shapes (lens names vs questions) and a substring pin across them would be
green-for-the-wrong-reason theatre. And it asserts nothing about any verdict, in either direction
(SK#2091).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import yaml

# Reuse, do not re-implement. Fourth validator in the family, so the arc's rule applies: import from the
# siblings rather than growing a fourth copy. `_git_show` in particular carries the cwd=REPO_ROOT
# behaviour the additivity clause depends on.
from validate_property_catalog import (  # noqa: E402  (path-relative sibling import, see __main__)
    _SEMVER,
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
    "criterion",
    "governance",
    "axes",
    "skills",
    "properties",
    "population_floors",
    "coverage_dimensions",
    "documented_collisions",
    "related_ungoverned_vocabularies",
}
REQUIRED_TOP_KEYS = ("enum_id", "version", "description", "criterion", "governance", "axes", "skills", "properties")
GOVERNANCE_CLAUSES = ("role", "versioning", "ownership", "change_discipline", "identity_is_the_pair")

AXIS_KEYS = {"skill", "axis_key", "label", "informs", "critical", "resolves", "resolves_pending", "collides_with"}
REQUIRED_AXIS_KEYS = ("skill", "axis_key", "label", "informs", "critical", "resolves")
SKILL_INDEX_KEYS = {"gate", "axis_keys"}
PROPERTY_INDEX_KEYS = {"resolved_by", "note"}
PAIR_KEYS = {"skill", "axis_key"}
FLOOR_KEYS = {"skills", "axes", "distinct_axis_keys", "resolved_axes", "resolved_properties", "note"}
DIMENSION_KEYS = {"dimension", "measured", "total", "is_a_gate", "rationale"}
COLLISION_KEYS = {"axis_key", "skills", "why_legal", "why_declared", "action"}
UNGOVERNED_KEYS = {"field", "site", "tokens", "why_out_of_scope"}

GOVERNED_FIELD = "claim_axis"
_AXIS_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")
_SKILL = re.compile(r"^[a-z][a-z0-9-]*$")
_GATE = re.compile(r"^[a-z][a-z0-9_]*$")
# The QUALIFIED property id. The dot is mandatory: see clause 4 and the enum header.
_QUALIFIED_PROPERTY_ID = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


def _pair(entry: dict) -> tuple:
    return (entry.get("skill"), entry.get("axis_key"))


def _axes_list(doc: dict) -> list:
    return [a for a in (doc.get("axes") or []) if isinstance(a, dict)]


def _pairs_from_axes(doc_or_axes) -> set:
    """{(skill, axis_key)} from the primary roster."""
    axes = _axes_list(doc_or_axes) if isinstance(doc_or_axes, dict) else list(doc_or_axes or [])
    return {_pair(a) for a in axes if isinstance(a.get("skill"), str) and isinstance(a.get("axis_key"), str)}


def _resolves_map(axes: list) -> dict:
    """(skill, axis_key) -> frozenset(qualified property id). EVERY axis appears, including the ones
    whose set is EMPTY — that is what makes clause 6 a reconciliation over the full population rather
    than a "check it when present" check, which 0c proved is blind to a key that should be absent."""
    out = {}
    for a in axes:
        p = _pair(a)
        rs = a.get("resolves")
        out[p] = frozenset(r for r in (rs if isinstance(rs, list) else []) if isinstance(r, str))
    return out


def _measured_collisions(pairs: set) -> dict:
    """axis_key -> {skills using it}, restricted to the keys used by MORE THAN ONE skill. Derived from
    the roster, never from a hand-maintained list, so it cannot drift away from the population."""
    by_token: dict = {}
    for skill, axis in pairs:
        by_token.setdefault(axis, set()).add(skill)
    return {ax: sk for ax, sk in by_token.items() if len(sk) > 1}


def _catalog_index(catalog_dir: Path) -> "tuple[dict, dict] | tuple[None, None]":
    """Read the property catalog once. Returns

        (qualified_id -> {(skill, axis_key)}, catalog_id -> {entry_id})

    or (None, None) when the directory is unreadable/empty. `consumers:` entries carrying `surface:`
    instead of `axis_key:` are deliberately EXCLUDED from the first map: they are non-axis consumers and
    this registry governs axes only, so folding them in would make clause 6 demand entries for axes that
    do not exist.
    """
    if not catalog_dir.is_dir():
        return None, None
    consumers: dict = {}
    entries: dict = {}
    for path in sorted(catalog_dir.glob("*.yaml")):
        try:
            doc = yaml.safe_load(path.read_text()) or {}
        except (OSError, yaml.YAMLError):
            return None, None
        if not isinstance(doc, dict):
            return None, None
        cid = doc.get("catalog_id")
        if not isinstance(cid, str):
            return None, None
        entries.setdefault(cid, set())
        for section in ("properties", "families"):
            for key, entry in (doc.get(section) or {}).items():
                if not isinstance(entry, dict):
                    continue
                entries[cid].add(key)
                qid = f"{cid}.{key}"
                for c in entry.get("consumers") or []:
                    if isinstance(c, dict) and isinstance(c.get("axis_key"), str) and isinstance(c.get("skill"), str):
                        consumers.setdefault(qid, set()).add((c["skill"], c["axis_key"]))
    if not entries:
        return None, None
    return consumers, entries


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
        r.err(f"{where}: `enum_id` must be {GOVERNED_FIELD!r}, got {doc.get('enum_id')!r}")
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


def _check_axes(r: Report, where: str, doc: dict, skills_root: Path, catalog_entries: "dict | None") -> list:
    """Clauses 2, 4, 5 (and the per-entry half of 7). Returns the axis entries."""
    axes = doc.get("axes")
    if not isinstance(axes, list) or not axes:
        r.err(f"{where}: `axes` must be a non-empty list of (skill, axis_key) entries")
        return []
    seen: set = set()
    for i, entry in enumerate(axes):
        w = f"{where}.axes[{i}]"
        if not isinstance(entry, dict):
            r.err(f"{w}: must be a mapping")
            continue
        _strict_keys(r, w, entry, AXIS_KEYS)
        for k in REQUIRED_AXIS_KEYS:
            if k not in entry:
                r.err(f"{w}: missing required key `{k}`")
        skill, axis = entry.get("skill"), entry.get("axis_key")
        if not isinstance(skill, str) or not _SKILL.match(skill or ""):
            r.err(f"{w}: `skill` must be a hyphen-case skill directory name, got {skill!r}")
        elif skills_root is not None and not (skills_root / skill).is_dir():
            r.err(
                f"{w}: `skill` {skill!r} is not a directory under {skills_root} — the roster names a skill that does not exist"
            )
        if not isinstance(axis, str) or not _AXIS_KEY.match(axis or ""):
            r.err(f"{w}: `axis_key` must be an UPPER_SNAKE wire token, got {axis!r}")
        w = f"{where}.axes[{skill}/{axis}]"
        # CLAUSE 2 — the PAIR is the identity. A bare-axis_key uniqueness check here would REJECT the
        # legal `DEP` collision, which is exactly the conflation this file exists to prevent.
        if (skill, axis) in seen:
            r.err(f"{w}: duplicate `(skill, axis_key)` pair — the pair is the identity and must appear once")
        seen.add((skill, axis))
        _nonempty_str(r, w, entry, "label")
        _nonempty_str(r, w, entry, "informs")
        if entry.get("critical") not in (True, False):
            r.err(
                f"{w}: `critical` must be present and exactly true or false. It is REQUIRED rather than "
                f"defaulted: an absent flag would read as 'not critical', so a forgotten key would "
                f"silently understate a decision-critical axis"
            )

        rs = entry.get("resolves")
        if not isinstance(rs, list):
            r.err(f"{w}: `resolves` must be a list (possibly empty) of qualified property ids")
            rs = []
        elif len(set(rs)) != len(rs):
            r.err(f"{w}: duplicate id(s) in `resolves`: {sorted({x for x in rs if rs.count(x) > 1})}")
        for rid in rs:
            # CLAUSE 4.
            if not isinstance(rid, str) or not _QUALIFIED_PROPERTY_ID.match(rid or ""):
                r.err(
                    f"{w}: `resolves` entry {rid!r} must be the QUALIFIED form `<catalog_id>.<entry_id>`. "
                    f"The bare entry id is REJECTED, not guessed: the catalog's 27 entries have only 25 "
                    f"distinct bare ids (`selectivity` and `subtype_restriction` each name one "
                    f"l2a_property in expression.yaml AND one unrelated l2b_family in "
                    f"integrated_families.yaml), so a bare id is genuinely ambiguous"
                )
                continue
            if catalog_entries is None:
                continue
            cid, _, eid = rid.partition(".")
            if cid not in catalog_entries:
                r.err(f"{w}: `resolves` entry {rid!r} names catalog {cid!r}, which is not a property_catalog file")
            elif eid not in catalog_entries[cid]:
                r.err(f"{w}: `resolves` entry {rid!r} does not resolve — {cid}.yaml declares no entry {eid!r}")

        # CLAUSE 5 — the asymmetry. Both halves, so neither an unexplained hole nor a stale deferral note
        # can survive.
        pending = entry.get("resolves_pending")
        if rs and pending is not None:
            r.err(
                f"{w}: `resolves` is non-empty, so `resolves_pending` may not be present — a deferral note "
                f"on an axis that already resolves a property is a stale claim about the roadmap"
            )
        if not rs:
            if pending is None:
                r.err(
                    f"{w}: `resolves` is EMPTY, so `resolves_pending` is REQUIRED — an unexplained empty "
                    f"list is indistinguishable from an oversight, which is how a registry starts "
                    f"reporting coverage it does not have"
                )
            else:
                _nonempty_str(r, w, entry, "resolves_pending")

        cw = entry.get("collides_with")
        if cw is not None:
            if not isinstance(cw, list) or not cw:
                r.err(f"{w}: `collides_with` must be a non-empty list of (skill, axis_key) pairs when present")
            else:
                for j, c in enumerate(cw):
                    wc = f"{w}.collides_with[{j}]"
                    if not isinstance(c, dict):
                        r.err(f"{wc}: must be a mapping with {sorted(PAIR_KEYS)}")
                        continue
                    _strict_keys(r, wc, c, PAIR_KEYS)
                    if c.get("axis_key") != axis:
                        r.err(
                            f"{wc}: names axis_key {c.get('axis_key')!r} but a collision is by DEFINITION "
                            f"the SAME token in another skill, so it must be {axis!r}"
                        )
                    if c.get("skill") == skill:
                        r.err(f"{wc}: names its own skill — a collision is across skills, never within one")
    return _axes_list(doc)


def _check_skill_index(r: Report, where: str, doc: dict, axes: list, skills_root: Path) -> None:
    """Clause 3, first inverse index: skill -> {gate, axis_keys in display order}."""
    index = doc.get("skills")
    if not isinstance(index, dict) or not index:
        r.err(f"{where}: `skills` must be a non-empty mapping of skill -> {{gate, axis_keys}}")
        return
    from_roster: dict = {}
    for a in axes:
        if isinstance(a.get("skill"), str) and isinstance(a.get("axis_key"), str):
            from_roster.setdefault(a["skill"], []).append(a["axis_key"])

    missing = sorted(set(from_roster) - set(index))
    extra = sorted(set(index) - set(from_roster))
    if missing:
        r.err(f"{where}.skills: skill(s) {missing} appear in `axes` but have no `skills:` index entry")
    if extra:
        r.err(
            f"{where}.skills: skill(s) {extra} are indexed but declare no axis in `axes` — a skill with no axis is not a claim-axis consumer"
        )

    gates: dict = {}
    for skill, spec in index.items():
        w = f"{where}.skills[{skill}]"
        if not isinstance(skill, str) or not _SKILL.match(skill or ""):
            r.err(f"{w}: skill key must be a hyphen-case directory name")
        elif skills_root is not None and not (skills_root / skill).is_dir():
            r.err(f"{w}: not a directory under {skills_root}")
        if not isinstance(spec, dict):
            r.err(f"{w}: must be a mapping with {sorted(SKILL_INDEX_KEYS)}")
            continue
        _strict_keys(r, w, spec, SKILL_INDEX_KEYS)
        gate = spec.get("gate")
        if not isinstance(gate, str) or not _GATE.match(gate or ""):
            r.err(f"{w}: `gate` must be a snake_case verdict-gate name, got {gate!r}")
        else:
            gates.setdefault(gate, []).append(skill)
        keys = spec.get("axis_keys")
        if not isinstance(keys, list) or not keys:
            r.err(f"{w}: `axis_keys` must be a non-empty list in DISPLAY order")
            continue
        if len(set(keys)) != len(keys):
            r.err(f"{w}: duplicate axis_key(s) in `axis_keys`: {sorted({k for k in keys if keys.count(k) > 1})}")
        roster = from_roster.get(skill)
        if roster is not None and list(keys) != list(roster):
            r.err(
                f"{w}: `axis_keys` {list(keys)} does not match this skill's `axes` entries in order "
                f"{list(roster)}. The index carries the DISPLAY ORDER, which is information the flat "
                f"roster would otherwise lose, so it is pinned to the roster sequence and not merely to "
                f"its set"
            )
    for gate, owners in sorted(gates.items()):
        if len(owners) > 1:
            r.err(
                f"{where}.skills: gate {gate!r} is claimed by {sorted(owners)} — a verdict gate has one "
                f"owning skill, so this is either a copy-paste or a real gate collision"
            )


def _check_property_index(r: Report, where: str, doc: dict, axes: list, catalog_entries: "dict | None") -> None:
    """Clause 3, second inverse index: qualified property id -> the axes that resolve it."""
    index = doc.get("properties")
    if not isinstance(index, dict) or not index:
        r.err(f"{where}: `properties` must be a non-empty mapping of qualified property id -> resolved_by")
        return
    from_roster: dict = {}
    for p, ids in _resolves_map(axes).items():
        for rid in ids:
            from_roster.setdefault(rid, set()).add(p)

    missing = sorted(set(from_roster) - set(index))
    extra = sorted(set(index) - set(from_roster))
    if missing:
        r.err(f"{where}.properties: propert(ies) {missing} are cited by an axis's `resolves` but absent from the index")
    if extra:
        r.err(
            f"{where}.properties: propert(ies) {extra} are indexed but no axis's `resolves` cites them — dead index entries"
        )

    for rid, spec in index.items():
        w = f"{where}.properties[{rid}]"
        if not isinstance(rid, str) or not _QUALIFIED_PROPERTY_ID.match(rid or ""):
            r.err(f"{w}: index key must be the qualified form `<catalog_id>.<entry_id>` (see clause 4)")
        elif catalog_entries is not None:
            cid, _, eid = rid.partition(".")
            if cid not in catalog_entries or eid not in catalog_entries.get(cid, ()):
                r.err(f"{w}: index key does not resolve to a property_catalog entry")
        if not isinstance(spec, dict):
            r.err(f"{w}: must be a mapping with {sorted(PROPERTY_INDEX_KEYS)}")
            continue
        _strict_keys(r, w, spec, PROPERTY_INDEX_KEYS)
        if "note" in spec:
            _nonempty_str(r, w, spec, "note")
        rb = spec.get("resolved_by")
        if not isinstance(rb, list) or not rb:
            r.err(f"{w}: `resolved_by` must be a non-empty list of (skill, axis_key) pairs")
            continue
        declared: set = set()
        for j, c in enumerate(rb):
            wc = f"{w}.resolved_by[{j}]"
            if not isinstance(c, dict):
                r.err(f"{wc}: must be a mapping with {sorted(PAIR_KEYS)}")
                continue
            _strict_keys(r, wc, c, PAIR_KEYS)
            declared.add((c.get("skill"), c.get("axis_key")))
        expected = from_roster.get(rid)
        if expected is not None and declared != expected:
            r.err(
                f"{w}: `resolved_by` {sorted(declared)} disagrees with the axes whose `resolves` cites "
                f"{rid}: {sorted(expected)}. The two views are the same facts indexed both ways"
            )


def _check_catalog_consumers(r: Report, where: str, axes: list, consumers: "dict | None") -> None:
    """Clause 6 — `resolves` reconciled against the catalog's `consumers:` block, both directions, over
    the FULL axis population with the EMPTY set a first-class value."""
    if consumers is None:
        r.err(
            f"{where}: could not read the property catalog's `consumers:` blocks — reconciling `resolves` "
            f"against them is this validator's load-bearing clause and must not be reported green unrun"
        )
        return
    declared_pairs: set = set()
    for p, ids in _resolves_map(axes).items():
        for rid in ids:
            declared_pairs.add((rid, p))
    catalog_pairs = {(rid, pair) for rid, pairs in consumers.items() for pair in pairs}

    only_catalog = sorted(catalog_pairs - declared_pairs)
    only_here = sorted(declared_pairs - catalog_pairs)
    if only_catalog:
        r.err(
            f"{where}: the property catalog names {len(only_catalog)} (property, axis) consumer(s) that "
            f"the axis does NOT cite back in `resolves`: {only_catalog}. That is a FALSE ABSENCE — this "
            f"registry would report an axis as resolving nothing while the catalog says it does. Note the "
            f"reconciliation runs over EVERY axis with the empty `resolves` set as a real value, not only "
            f"over the axes that happen to carry one: a 'check it when present' clause is structurally "
            f"blind to exactly this case"
        )
    if only_here:
        r.err(
            f"{where}: {len(only_here)} (property, axis) claim(s) in `resolves` are NOT declared as "
            f"`consumers:` by the catalog entry: {only_here}. An unsourced claim — the catalog is "
            f"authoritative for which axis consumes a property"
        )


def _check_collisions(r: Report, where: str, doc: dict, axes: list) -> None:
    """Clause 7 — declared collisions reconciled against the MEASURED ones, both directions."""
    pairs = _pairs_from_axes(axes)
    measured = _measured_collisions(pairs)

    for a in axes:
        skill, axis = _pair(a)
        w = f"{where}.axes[{skill}/{axis}]"
        expected = {(s, axis) for s in measured.get(axis, ()) if s != skill}
        cw = a.get("collides_with")
        got = {(c.get("skill"), c.get("axis_key")) for c in (cw if isinstance(cw, list) else []) if isinstance(c, dict)}
        if expected and not cw:
            r.err(
                f"{w}: axis_key {axis!r} is ALSO used by {sorted(s for s, _ in expected)} but this entry "
                f"carries no `collides_with`. The declaration is what stops a reader inferring 'same "
                f"token, same biology' — and an absent key is precisely the case a 'validate it when "
                f"present' clause cannot see, so absence is compared here as a first-class value"
            )
        elif not expected and cw:
            r.err(
                f"{w}: `collides_with` is present but axis_key {axis!r} is used by no other skill — a "
                f"declared collision that does not exist misdirects every reader of this entry"
            )
        elif expected and got != expected:
            r.err(f"{w}: `collides_with` {sorted(got)} does not match the measured collision {sorted(expected)}")

    declared = doc.get("documented_collisions")
    if measured and declared is None:
        r.err(
            f"{where}: {sorted(measured)} collide across skills but there is no `documented_collisions` "
            f"block. A legal collision must be DECLARED, with its reason, or the next reader resolves it "
            f"by renaming a `claim_vector.<axis>` wire name — which degrades SILENTLY to `unmeasured`"
        )
        return
    if declared is None:
        return
    if not isinstance(declared, list) or not declared:
        r.err(f"{where}.documented_collisions: must be a non-empty list when present")
        return
    named: set = set()
    for i, e in enumerate(declared):
        w = f"{where}.documented_collisions[{i}]"
        if not isinstance(e, dict):
            r.err(f"{w}: must be a mapping")
            continue
        _strict_keys(r, w, e, COLLISION_KEYS)
        for k in ("why_legal", "why_declared", "action"):
            _nonempty_str(r, w, e, k)
        ax = e.get("axis_key")
        if not isinstance(ax, str) or ax not in measured:
            r.err(f"{w}: `axis_key` {ax!r} does not collide across skills in the roster (measured: {sorted(measured)})")
            continue
        named.add(ax)
        sk = e.get("skills")
        if not isinstance(sk, list) or set(sk) != measured[ax]:
            r.err(f"{w}: `skills` {sk!r} must be exactly the skills measured using {ax!r}: {sorted(measured[ax])}")
    undocumented = sorted(set(measured) - named)
    if undocumented:
        r.err(f"{where}.documented_collisions: axis_key(s) {undocumented} collide but are not documented")


def _check_floors(r: Report, where: str, doc: dict, axes: list) -> None:
    """Clause 8."""
    floors = doc.get("population_floors")
    if not isinstance(floors, dict):
        r.err(f"{where}: `population_floors` must be a mapping — the anti-vacuity floors are not optional")
        return
    _strict_keys(r, f"{where}.population_floors", floors, FLOOR_KEYS)
    _nonempty_str(r, f"{where}.population_floors", floors, "note")
    pairs = _pairs_from_axes(axes)
    rmap = _resolves_map(axes)
    measured = {
        "skills": len({s for s, _ in pairs}),
        "axes": len(pairs),
        "distinct_axis_keys": len({a for _, a in pairs}),
        "resolved_axes": sum(1 for ids in rmap.values() if ids),
        "resolved_properties": len({rid for ids in rmap.values() for rid in ids}),
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
    if isinstance(floors.get("skills"), int) and floors["skills"] < 15:
        r.err(
            f"{where}.population_floors: `skills` floor must be >= 15 (the measured fleet at v1.0.0). "
            f"It is a FLOOR and not an equality pin on purpose — contracts/ may not read skills' "
            f"HeadlineSpecs, so the equality half lives in "
            f"skills/_skills_common/tests/test_claim_axis_registry_coverage.py"
        )


def _check_tail_blocks(r: Report, where: str, doc: dict) -> None:
    """Clause 9 plus shape checks on the optional trailing blocks."""
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
                m, t = d.get("measured"), d.get("total")
                if not isinstance(m, int) or isinstance(m, bool):
                    r.err(f"{w}: `measured` must be an int — an unmeasured dimension reports nothing")
                if not isinstance(t, int) or isinstance(t, bool):
                    r.err(
                        f"{w}: `total` must be an int — a measurement without its denominator is not a coverage number"
                    )
                if isinstance(m, int) and isinstance(t, int) and not isinstance(m, bool) and m > t:
                    r.err(f"{w}: `measured` ({m}) exceeds `total` ({t})")
                # CLAUSE 9.
                if d.get("is_a_gate") is not False:
                    r.err(
                        f"{w}: `is_a_gate` must be present and exactly `false`. These numbers are "
                        f"REPORTED, never enforced; a dimension that claims to be a gate is either a gate "
                        f"this validator does not implement or a promotion nobody reviewed"
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
                for k in ("field", "site", "why_out_of_scope"):
                    _nonempty_str(r, w, e, k)
                if not isinstance(e.get("tokens"), list) or not e.get("tokens"):
                    r.err(f"{w}: `tokens` must be a non-empty list")


def validate_enum(enum_path: Path, catalog_dir: Path, skills_root: Path) -> Report:
    r = Report()
    try:
        doc = yaml.safe_load(enum_path.read_text()) or {}
    except (OSError, yaml.YAMLError) as exc:
        r.err(f"{enum_path}: could not be read as YAML: {exc}")
        return r
    if not isinstance(doc, dict):
        r.err(f"{enum_path}: top level must be a mapping")
        return r

    consumers, catalog_entries = _catalog_index(catalog_dir)
    where = enum_path.name

    _check_shape(r, enum_path, doc)
    axes = _check_axes(r, where, doc, skills_root, catalog_entries)
    _check_skill_index(r, where, doc, axes, skills_root)
    _check_property_index(r, where, doc, axes, catalog_entries)
    _check_catalog_consumers(r, where, axes, consumers)
    _check_collisions(r, where, doc, axes)
    _check_tail_blocks(r, where, doc)
    _check_floors(r, where, doc, axes)
    return r


def check_additivity(enum_path: Path, ref: str) -> Report:
    """Clause 10. No pair removed, no `resolves` id removed, no `label` or `critical` changed; additions
    bump the version.

    A ref that cannot be resolved is an ERROR, not a skip: the caller explicitly asked for this clause,
    and returning green without having run it is the fail-open this validator exists to prevent. The
    message is deliberately word-for-word the sibling validators'.
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
    # CRASHES instead of running. That is the bug PR-0a shipped and caught.
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

    old_axes, new_axes = _axes_list(old), _axes_list(new)
    old_by, new_by = {_pair(a): a for a in old_axes}, {_pair(a): a for a in new_axes}

    gone = sorted(k for k in set(old_by) - set(new_by))
    if gone:
        r.err(
            f"--additive-against {ref}: (skill, axis_key) pair(s) REMOVED: {gone}. The pair is a PUBLISHED "
            f"name — `claim_vector.<axis>` paths are hard-coded in question-table provenance_refs, and a "
            f"mismatch degrades SILENTLY to `unmeasured`. Migrate by add -> consume -> remove"
        )

    for key in sorted(set(old_by) & set(new_by)):
        o, n = old_by[key], new_by[key]
        if o.get("label") != n.get("label"):
            r.err(
                f"--additive-against {ref}: {key} `label` changed {o.get('label')!r} -> {n.get('label')!r}. "
                f"The label is pinned byte-for-byte to the skill's `axis_labels` entry, so a change here "
                f"is either a BREAKING relabel or a drift from the code"
            )
        if o.get("critical") != n.get("critical"):
            r.err(
                f"--additive-against {ref}: {key} `critical` flipped {o.get('critical')!r} -> "
                f"{n.get('critical')!r}. Critical-axis membership floors confidence "
                f"(headline_core.derive_confidence), so this is a behavioural claim, not an edit"
            )
        lost = sorted(set(o.get("resolves") or []) - set(n.get("resolves") or []))
        if lost:
            r.err(
                f"--additive-against {ref}: {key} no longer resolves {lost} — dropping a property says an "
                f"alignment that held no longer does. Additive-only forbids it"
            )

    added_pairs = set(new_by) - set(old_by)
    old_res = {(p, rid) for p, a in old_by.items() for rid in (a.get("resolves") or [])}
    new_res = {(p, rid) for p, a in new_by.items() for rid in (a.get("resolves") or [])}
    added_res = new_res - old_res
    if (added_pairs or added_res) and old.get("version") == new.get("version"):
        r.err(
            f"--additive-against {ref}: additions present (+{len(added_pairs)} axis pair(s), "
            f"+{len(added_res)} resolves entr(ies)) but `version` is unchanged at {new.get('version')!r} — "
            f"an additive change is a MINOR bump"
        )
    return r


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--enum", type=Path, default=CONTRACTS_ROOT / "vocabularies" / "claim_axis.enum.yaml")
    ap.add_argument(
        "--catalog",
        type=Path,
        default=CONTRACTS_ROOT / "vocabularies" / "property_catalog",
        help="the property catalog directory `resolves:` ids and `consumers:` blocks are checked against",
    )
    ap.add_argument(
        "--skills",
        type=Path,
        default=REPO_ROOT / "skills",
        help="the skills root; every `skill:` must be a directory under it (existence ONLY — reading "
        "their HeadlineSpecs would invert the dependency direction and belongs to the skills-side test)",
    )
    ap.add_argument(
        "--additive-against",
        metavar="GIT_REF",
        default=None,
        help="also enforce additivity against this git ref (RED if the ref does not resolve)",
    )
    args = ap.parse_args(argv)

    print("validate_claim_axis.py results:")
    if not args.enum.is_file():
        print(f"  [ERROR]   enum file {args.enum} does not exist")
        return 1
    if not args.catalog.is_dir():
        print(
            f"  [ERROR]   {args.catalog} not found — reconciling `resolves:` against the catalog's "
            f"`consumers:` blocks is this validator's load-bearing clause and must not be skipped"
        )
        return 1
    if not args.skills.is_dir():
        print(f"  [ERROR]   {args.skills} not found — every `skill:` is checked to be a real directory under it")
        return 1

    r = validate_enum(args.enum, args.catalog, args.skills)
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

    # The summary re-reads the file, and an unparseable file has ALREADY been reported above. Re-raising
    # here would make the run CRASH rather than FAIL, and preland.sh prints `FAIL <label>` identically for
    # both — so the distinction would be invisible exactly when it matters. Degrade the counts, never the
    # verdict.
    try:
        doc = yaml.safe_load(args.enum.read_text()) or {}
    except yaml.YAMLError:
        doc = {}
    if not isinstance(doc, dict):
        doc = {}
    axes = _axes_list(doc)
    pairs = _pairs_from_axes(axes)
    rmap = _resolves_map(axes)
    collisions = sorted(_measured_collisions(pairs))
    print(
        f"\nSummary: {len({s for s, _ in pairs})} skill(s), {len(pairs)} axis pair(s), "
        f"{len({a for _, a in pairs})} distinct axis_key(s), "
        f"{sum(1 for ids in rmap.values() if ids)} axis(es) resolving "
        f"{len({rid for ids in rmap.values() for rid in ids})} propert(ies), "
        f"{len(collisions)} collision(s) ({', '.join(collisions) or 'none'}); "
        f"{'OK' if total_errors == 0 else str(total_errors) + ' error(s)'}."
    )
    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    # Sibling import: running this as a script puts validators/ on sys.path[0], so
    # `from validate_property_catalog import ...` resolves. The tests load this module by path and do the
    # same insertion explicitly.
    sys.exit(_main())
