#!/usr/bin/env python3
"""
validate_property_catalog.py — governance validator for vocabularies/property_catalog/.

Epic #1507's thesis is that measurements resolve SHARED BIOLOGICAL PROPERTIES rather than
per-card classifiers. vocabularies/property_catalog/ is the register that makes that thesis
inspectable; this validator is what stops it rotting into prose. See the directory's README.md for
the entry shape and the identifiability test.

WHAT THIS ENFORCES (and why each clause exists rather than being a style rule):

  1. SHAPE / STRICT KEYS. Required top-level keys; `catalog_id` equals the filename stem; semver
     `version`; a `governance` block with all four clauses non-empty. Entry keys are checked against
     a CLOSED allowlist — a misspelled `determinats:` would otherwise be silently ignored, which is
     a fail-open on the exact discipline this file exists to enforce.

  2. REFERENTIAL INTEGRITY AGAINST CARDS. Every observable's / arm's `card_id` must exist in
     cards/*.card.yaml and its `field` must appear in that card's `outputs.summary_fields`. This is
     the reconstructability contract: an entry naming a field that does not exist is a claim that
     the property can be traced to a measurement when it cannot. Deliberately NOT skipped when
     cards/ is missing — a missing corpus makes this validator RED, because silently dropping the
     only referential clause would make a green run meaningless.

  3. THE IDENTIFIABILITY TEST, MECHANISED. `role: estimator | coupled` is mandatory on every
     observable; a `resolvable` property needs at least one `estimator` (a property with only
     `coupled` observables has not admitted the thing that measures it); a `coupled` observable MUST
     name what it actually estimates via `estimates_property`, and that ID must resolve somewhere in
     the catalog. `fleet_deferred` properties must carry ZERO observables and an explicit
     `deferred_pending` — so "declared but unresolvable" is a stated position, not an empty entry.

  4. DEPENDENCE GROUPS. Mandatory on every observable and arm. For an l2b_family, the arms must span
     >= 2 distinct groups OR the family must carry an explicit `independence_waiver`. A family that
     folds same-modality siblings without saying so asserts independence it does not have (#1667:
     CPTAC + TPHP are one mass-spec arm measured twice).

  5. DETERMINANT DISCIPLINE. Every determinant needs `name`, `value`, `unit`, `source`, `rationale`
     and a `calibration` block. `unit` is load-bearing: two thresholds that share a numeral in
     different units reconcile to a confident wrong answer. The `source` PATH must exist on disk
     (the `:line` suffix is not checked — line numbers drift, moved modules do not). A rationale
     containing UNKNOWN requires `calibration.adjudication` — an honest hole must be TRACKED, or it
     becomes permanent.

  6. KIND DISJOINTNESS. `l2a_property` entries carry `observables` and no `integration`;
     `l2b_family` entries carry `arms` (>= 2) and a full `integration` block whose `relations` are a
     non-empty subset of the closed dependence_edges.py vocabulary.

  7. ADDITIVITY (opt-in, `--additive-against <git-ref>`). No entry removed, no entry's `grain`
     changed, and any entry addition accompanied by a version bump. Opt-in because it needs git; when
     the flag IS passed and the ref cannot be resolved the run is RED, never a silent skip — the
     caller asked for the clause and must not get a green without it.

WHAT IT DELIBERATELY DOES NOT DO: it does not compare `consumers:` against skills' HeadlineSpec
declarations. The dependency direction is skills/ -> contracts/, never the reverse, so the
contracts side may only check that a named skill DIRECTORY exists; the real cross-check belongs to a
skills-side test (#2228). And per SK#2091 nothing here is a verdict gate.

Usage:
  python validators/validate_property_catalog.py
  python validators/validate_property_catalog.py --catalog vocabularies/property_catalog --cards cards/
  python validators/validate_property_catalog.py --additive-against origin/main
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_ROOT = Path(__file__).resolve().parents[1]

VALID_KINDS = {"l2a_property", "l2b_family"}
VALID_STATUS = {"resolvable", "fleet_deferred"}
VALID_ROLES = {"estimator", "coupled"}
VALID_EMISSIONS = {"class_token", "anchor"}
VALID_LIFTS = {"card_summary", "headline"}
# The closed relation vocabulary, mirrored from skills/_skills_common/dependence_edges.py.
VALID_RELATIONS = {"corroborates", "contradicts", "qualifies"}

REQUIRED_TOP_KEYS = ("catalog_id", "kind", "version", "description", "governance")
GOVERNANCE_CLAUSES = ("role", "versioning", "ownership", "change_discipline")

# CLOSED allowlists. A key outside these is an ERROR, not a warning — see clause 1.
ENTRY_KEYS = {
    "status",
    "definition",
    "grain",
    "observables",
    "arms",
    "determinants",
    "integration",
    "consumers",
    "deferred_pending",
    "dependence_note",
    "integration_note",
    "note",
}
GRAIN_KEYS = {"measurement_type", "sample_context", "entity_grain"}
OBSERVABLE_KEYS = {"card_id", "field", "role", "dependence_group", "estimates_property", "lift", "emission", "note"}
ARM_KEYS = {"card_id", "field", "dependence_group", "property_id", "lift", "note"}
DETERMINANT_KEYS = {"name", "value", "unit", "source", "rationale", "calibration"}
CALIBRATION_KEYS = {"controls", "flip_matrix", "adjudication"}
INTEGRATION_KEYS = {
    "island_key",
    "builder",
    "builder_function",
    "comparability",
    "relations",
    "independence_waiver",
    "note",
    "grain_note",
}
CONSUMER_KEYS = {"skill", "axis_key", "surface", "note"}

_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
_SNAKE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass
class Report:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def err(self, m: str) -> None:
        self.errors.append(m)

    def warn(self, m: str) -> None:
        self.warnings.append(m)


def card_field_index(cards_dir: Path) -> "dict[str, set[str]] | None":
    """{card_id: {summary_field, ...}} from cards/*.card.yaml. None when the directory is absent."""
    if not cards_dir.is_dir():
        return None
    index: dict[str, set[str]] = {}
    for path in sorted(cards_dir.glob("*.card.yaml")):
        try:
            doc = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError:
            continue
        card_id = doc.get("card_id") or path.name.removesuffix(".card.yaml")
        fields = ((doc.get("outputs") or {}) or {}).get("summary_fields") or []
        # summary_fields may carry non-string members; only strings are addressable names.
        index[card_id] = {f for f in fields if isinstance(f, str)}
    return index


def _strict_keys(r: Report, where: str, obj: dict, allowed: set) -> None:
    for k in obj:
        if k not in allowed:
            r.err(f"{where}: unknown key `{k}` (allowed: {', '.join(sorted(allowed))})")


def _nonempty_str(r: Report, where: str, obj: dict, key: str, required: bool = True) -> None:
    v = obj.get(key)
    if v is None:
        if required:
            r.err(f"{where}: missing `{key}`")
        return
    if not isinstance(v, str) or not v.strip():
        r.err(f"{where}: `{key}` must be a non-empty string")


def _check_grain(r: Report, where: str, grain) -> None:
    if not isinstance(grain, dict):
        r.err(f"{where}: `grain` must be a mapping with {sorted(GRAIN_KEYS)}")
        return
    _strict_keys(r, f"{where}.grain", grain, GRAIN_KEYS)
    for k in sorted(GRAIN_KEYS):
        _nonempty_str(r, f"{where}.grain", grain, k)


def _check_card_ref(r: Report, where: str, obj: dict, cards: "dict[str, set[str]]") -> None:
    card_id = obj.get("card_id")
    field_name = obj.get("field")
    if not isinstance(card_id, str) or not card_id:
        r.err(f"{where}: missing `card_id`")
        return
    if not isinstance(field_name, str) or not field_name:
        r.err(f"{where}: missing `field`")
        return
    if card_id not in cards:
        r.err(f"{where}: card_id `{card_id}` has no cards/{card_id}.card.yaml — dangling reference")
        return
    if field_name not in cards[card_id]:
        r.err(
            f"{where}: `{card_id}` does not declare summary field `{field_name}` "
            f"(outputs.summary_fields) — the property cannot be traced to this measurement"
        )


def _check_determinants(r: Report, where: str, dets) -> None:
    if dets is None:
        r.err(f"{where}: missing `determinants` (use `[]` when none are recorded)")
        return
    if not isinstance(dets, list):
        r.err(f"{where}: `determinants` must be a list")
        return
    for i, d in enumerate(dets):
        w = f"{where}.determinants[{i}]"
        if not isinstance(d, dict):
            r.err(f"{w}: must be a mapping")
            continue
        _strict_keys(r, w, d, DETERMINANT_KEYS)
        _nonempty_str(r, w, d, "name")
        _nonempty_str(r, w, d, "unit")
        _nonempty_str(r, w, d, "source")
        _nonempty_str(r, w, d, "rationale")
        if "value" not in d or d["value"] is None:
            r.err(f"{w}: missing `value`")
        src = d.get("source")
        if isinstance(src, str) and src.strip():
            # `path` or `path:line` — verify the PATH only. Line numbers drift; a moved module is
            # the failure worth catching.
            path_part = src.split(":", 1)[0]
            if not (REPO_ROOT / path_part).exists():
                r.err(f"{w}: `source` path `{path_part}` does not exist (relative to the repo root)")
        cal = d.get("calibration")
        if not isinstance(cal, dict):
            r.err(f"{w}: missing `calibration` mapping ({sorted(CALIBRATION_KEYS)}; null values are fine)")
            continue
        _strict_keys(r, f"{w}.calibration", cal, CALIBRATION_KEYS)
        for k in sorted(CALIBRATION_KEYS):
            if k not in cal:
                r.err(f"{w}.calibration: missing `{k}` (write `null` when there is none)")
        rationale = d.get("rationale") or ""
        if "UNKNOWN" in rationale and not cal.get("adjudication"):
            r.err(
                f"{w}: rationale says UNKNOWN but `calibration.adjudication` is empty — an "
                f"unexplained threshold must be TRACKED to an issue or it becomes permanent"
            )


def _check_consumers(r: Report, where: str, consumers, skills_root: Path) -> None:
    if consumers is None:
        r.err(f"{where}: missing `consumers` (use `[]` when none)")
        return
    if not isinstance(consumers, list):
        r.err(f"{where}: `consumers` must be a list")
        return
    for i, c in enumerate(consumers):
        w = f"{where}.consumers[{i}]"
        if not isinstance(c, dict):
            r.err(f"{w}: must be a mapping")
            continue
        _strict_keys(r, w, c, CONSUMER_KEYS)
        _nonempty_str(r, w, c, "skill")
        if not (c.get("axis_key") or c.get("surface")):
            r.err(f"{w}: needs `axis_key` or `surface` — a consumer must say WHERE it reads the property")
        skill = c.get("skill")
        # Shape only: whether that skill's HeadlineSpec really declares the axis is a SKILLS-side
        # question (dependency direction is skills/ -> contracts/, never the reverse).
        if isinstance(skill, str) and skill and skills_root.is_dir() and not (skills_root / skill).is_dir():
            r.err(f"{w}: skill `{skill}` has no skills/{skill}/ directory")


def _check_l2a_entry(r: Report, where: str, entry: dict, cards: dict, all_ids: set) -> None:
    status = entry.get("status")
    obs = entry.get("observables")
    if obs is None or not isinstance(obs, list):
        r.err(f"{where}: `observables` must be a list (`[]` for a fleet_deferred property)")
        return
    if "arms" in entry or "integration" in entry:
        r.err(f"{where}: kind l2a_property must NOT carry `arms` or `integration`")
    if status == "fleet_deferred":
        if obs:
            r.err(f"{where}: status fleet_deferred must carry ZERO observables (got {len(obs)})")
        _nonempty_str(r, where, entry, "deferred_pending")
        return
    _nonempty_str(r, where, entry, "deferred_pending", required=False)
    if not obs:
        r.err(f"{where}: a resolvable property needs at least one observable")
    roles: list[str] = []
    for i, o in enumerate(obs):
        w = f"{where}.observables[{i}]"
        if not isinstance(o, dict):
            r.err(f"{w}: must be a mapping")
            continue
        _strict_keys(r, w, o, OBSERVABLE_KEYS)
        _check_card_ref(r, w, o, cards)
        role = o.get("role")
        if role not in VALID_ROLES:
            r.err(f"{w}: `role` must be one of {sorted(VALID_ROLES)} (got {role!r})")
        else:
            roles.append(role)
        _nonempty_str(r, w, o, "dependence_group")
        if o.get("emission") is not None and o["emission"] not in VALID_EMISSIONS:
            r.err(f"{w}: `emission` must be one of {sorted(VALID_EMISSIONS)} (got {o['emission']!r})")
        if o.get("lift") is not None and o["lift"] not in VALID_LIFTS:
            r.err(f"{w}: `lift` must be one of {sorted(VALID_LIFTS)} (got {o['lift']!r})")
        if role == "coupled":
            target = o.get("estimates_property")
            if not target:
                r.err(
                    f"{w}: role `coupled` MUST name `estimates_property` — the identifiability test "
                    f"says this observable measures a DIFFERENT property, so it must say which"
                )
            elif target not in all_ids:
                r.err(f"{w}: `estimates_property: {target}` does not resolve to any catalog entry")
        elif o.get("estimates_property"):
            r.err(f"{w}: `estimates_property` is only meaningful with role `coupled`")
    if obs and roles and "estimator" not in roles:
        r.err(
            f"{where}: every observable is `coupled` — a property with no estimator has not admitted "
            f"the measurement that resolves it (see README's identifiability test)"
        )


def _check_l2b_entry(r: Report, where: str, entry: dict, cards: dict) -> None:
    if "observables" in entry:
        r.err(f"{where}: kind l2b_family carries `arms`, not `observables`")
    arms = entry.get("arms")
    if not isinstance(arms, list):
        r.err(f"{where}: `arms` must be a list")
        return
    if len(arms) < 2:
        r.err(f"{where}: a family integrates >= 2 arms (got {len(arms)}) — one arm is not an integration")
    groups: set[str] = set()
    for i, a in enumerate(arms):
        w = f"{where}.arms[{i}]"
        if not isinstance(a, dict):
            r.err(f"{w}: must be a mapping")
            continue
        _strict_keys(r, w, a, ARM_KEYS)
        _check_card_ref(r, w, a, cards)
        _nonempty_str(r, w, a, "dependence_group")
        if isinstance(a.get("dependence_group"), str):
            groups.add(a["dependence_group"])
        if a.get("lift") is not None and a["lift"] not in VALID_LIFTS:
            r.err(f"{w}: `lift` must be one of {sorted(VALID_LIFTS)} (got {a['lift']!r})")

    integ = entry.get("integration")
    if not isinstance(integ, dict):
        r.err(f"{where}: kind l2b_family REQUIRES an `integration` mapping")
        return
    _strict_keys(r, f"{where}.integration", integ, INTEGRATION_KEYS)
    for k in ("island_key", "builder", "builder_function", "comparability"):
        _nonempty_str(r, f"{where}.integration", integ, k)
    builder = integ.get("builder")
    if isinstance(builder, str) and builder.strip() and not (REPO_ROOT / builder.split(":", 1)[0]).exists():
        r.err(f"{where}.integration: `builder` path `{builder}` does not exist")
    rels = integ.get("relations")
    if not isinstance(rels, list) or not rels:
        r.err(f"{where}.integration: `relations` must be a non-empty list")
    else:
        for rel in rels:
            if rel not in VALID_RELATIONS:
                r.err(
                    f"{where}.integration: relation `{rel}` is outside the closed vocabulary "
                    f"{sorted(VALID_RELATIONS)} (dependence_edges.py)"
                )
    if len(groups) < 2 and not integ.get("independence_waiver"):
        r.err(
            f"{where}: all arms share dependence_group(s) {sorted(groups)} — a family folding "
            f"same-supply siblings must carry an explicit `independence_waiver` saying why "
            f"(#1667: CPTAC + TPHP are one mass-spec arm measured twice, not two)"
        )


def validate_file(path: Path, cards: "dict[str, set[str]]", all_ids: set, skills_root: Path) -> Report:
    r = Report()
    try:
        doc = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        r.err(f"{path.name}: YAML parse error: {exc}")
        return r
    if not isinstance(doc, dict):
        r.err(f"{path.name}: top level must be a mapping")
        return r

    for k in REQUIRED_TOP_KEYS:
        if k not in doc:
            r.err(f"{path.name}: missing top-level `{k}`")
    stem = path.name.removesuffix(".yaml")
    if doc.get("catalog_id") != stem:
        r.err(f"{path.name}: `catalog_id` ({doc.get('catalog_id')!r}) must equal the filename stem ({stem!r})")
    kind = doc.get("kind")
    if kind not in VALID_KINDS:
        r.err(f"{path.name}: `kind` must be one of {sorted(VALID_KINDS)} (got {kind!r})")
    version = doc.get("version")
    if not isinstance(version, str) or not _SEMVER.match(version):
        r.err(f"{path.name}: `version` must be semver MAJOR.MINOR.PATCH (got {version!r})")
    _nonempty_str(r, path.name, doc, "description")
    gov = doc.get("governance")
    if not isinstance(gov, dict):
        r.err(f"{path.name}: `governance` must be a mapping with {list(GOVERNANCE_CLAUSES)}")
    else:
        _strict_keys(r, f"{path.name}.governance", gov, set(GOVERNANCE_CLAUSES))
        for k in GOVERNANCE_CLAUSES:
            _nonempty_str(r, f"{path.name}.governance", gov, k)

    section = "families" if kind == "l2b_family" else "properties"
    other = "properties" if kind == "l2b_family" else "families"
    if other in doc:
        r.err(f"{path.name}: kind {kind} uses `{section}:`, not `{other}:`")
    entries = doc.get(section)
    if not isinstance(entries, dict) or not entries:
        r.err(f"{path.name}: `{section}` must be a non-empty mapping")
        return r

    for entry_id, entry in entries.items():
        where = f"{path.name}::{entry_id}"
        if not _SNAKE.match(str(entry_id)):
            r.err(f"{where}: entry id must be snake_case")
        if not isinstance(entry, dict):
            r.err(f"{where}: must be a mapping")
            continue
        _strict_keys(r, where, entry, ENTRY_KEYS)
        if entry.get("status") not in VALID_STATUS:
            r.err(f"{where}: `status` must be one of {sorted(VALID_STATUS)} (got {entry.get('status')!r})")
        _nonempty_str(r, where, entry, "definition")
        _check_grain(r, where, entry.get("grain"))
        _check_determinants(r, where, entry.get("determinants"))
        _check_consumers(r, where, entry.get("consumers"), skills_root)
        if kind == "l2b_family":
            _check_l2b_entry(r, where, entry, cards)
        else:
            _check_l2a_entry(r, where, entry, cards, all_ids)
    return r


def collect_entry_ids(catalog_dir: Path) -> set:
    """Every entry id across the catalog — the namespace `estimates_property` resolves against."""
    ids: set = set()
    for path in sorted(catalog_dir.glob("*.yaml")):
        try:
            doc = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError:
            continue
        for section in ("properties", "families"):
            if isinstance(doc.get(section), dict):
                ids |= set(doc[section])
    return ids


def _git_show(ref: str, rel_path: str) -> "str | None":
    try:
        out = subprocess.run(
            ["git", "show", f"{ref}:{rel_path}"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    return out.stdout if out.returncode == 0 else None


def check_additivity(catalog_dir: Path, ref: str) -> Report:
    """No entry removed, no `grain` changed, and an addition requires a version bump.

    A ref that cannot be resolved is an ERROR, not a skip: the caller explicitly asked for this
    clause, and returning green without having run it is the fail-open this whole validator exists
    to prevent.
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

    for path in sorted(catalog_dir.glob("*.yaml")):
        # `relative_to` needs BOTH sides absolute. The catalog dir arrives from the command line and is
        # normally RELATIVE (preland.sh and CI both pass `vocabularies/property_catalog` from cwd
        # contracts/), so resolve() first: without it this raised ValueError and the clause CRASHED
        # instead of running. `git show` wants a path relative to the REPO root, not to contracts/.
        try:
            rel = path.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            r.err(f"{path}: resolves outside the repo root {REPO_ROOT} — cannot compare against {ref}")
            continue
        prior_text = _git_show(ref, rel)
        if prior_text is None:
            continue  # new file at this ref — nothing to be additive against
        try:
            prior = yaml.safe_load(prior_text) or {}
            current = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError as exc:
            r.err(f"{path.name}: could not compare against {ref}: {exc}")
            continue
        section = "families" if current.get("kind") == "l2b_family" else "properties"
        prior_entries = prior.get(section) or {}
        cur_entries = current.get(section) or {}
        if not isinstance(prior_entries, dict) or not isinstance(cur_entries, dict):
            continue
        removed = sorted(set(prior_entries) - set(cur_entries))
        if removed:
            r.err(
                f"{path.name}: entries removed vs {ref}: {removed} — property ids are PUBLISHED names; "
                f"migrate by add -> consume -> remove, and a removal needs a MAJOR bump"
            )
        for eid in sorted(set(prior_entries) & set(cur_entries)):
            p_grain = (prior_entries[eid] or {}).get("grain")
            c_grain = (cur_entries[eid] or {}).get("grain")
            if p_grain != c_grain:
                r.err(
                    f"{path.name}::{eid}: `grain` changed vs {ref} ({p_grain} -> {c_grain}) — grain is "
                    f"part of the property's IDENTITY; a different grain is a different property"
                )
        added = sorted(set(cur_entries) - set(prior_entries))
        if added and current.get("version") == prior.get("version"):
            r.err(
                f"{path.name}: added {added} without bumping `version` (still {current.get('version')!r}) — "
                f"an addition is at least a MINOR bump"
            )
    return r


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--catalog", type=Path, default=CONTRACTS_ROOT / "vocabularies" / "property_catalog")
    ap.add_argument("--cards", type=Path, default=CONTRACTS_ROOT / "cards")
    ap.add_argument("--skills", type=Path, default=REPO_ROOT / "skills")
    ap.add_argument(
        "--additive-against",
        metavar="GIT_REF",
        default=None,
        help="also enforce additivity against this git ref (RED if the ref does not resolve)",
    )
    args = ap.parse_args(argv)

    print("validate_property_catalog.py results:")
    if not args.catalog.is_dir():
        print(f"  [ERROR]   catalog directory {args.catalog} does not exist")
        return 1
    files = sorted(args.catalog.glob("*.yaml"))
    if not files:
        print(f"  [ERROR]   no *.yaml files in {args.catalog} — an empty catalog cannot pass vacuously")
        return 1

    cards = card_field_index(args.cards)
    if cards is None:
        print(
            f"  [ERROR]   cards directory {args.cards} not found — referential integrity is this "
            f"validator's load-bearing clause and must not be skipped"
        )
        return 1

    all_ids = collect_entry_ids(args.catalog)
    total_errors = 0
    total_entries = 0
    for path in files:
        r = validate_file(path, cards, all_ids, args.skills)
        for e in r.errors:
            print(f"  [ERROR]   {e}")
        for w in r.warnings:
            print(f"  [WARNING] {w}")
        total_errors += len(r.errors)
        doc = yaml.safe_load(path.read_text()) or {}
        total_entries += len((doc.get("properties") or doc.get("families") or {}))

    if args.additive_against:
        r = check_additivity(args.catalog, args.additive_against)
        for e in r.errors:
            print(f"  [ERROR]   {e}")
        total_errors += len(r.errors)

    print(
        f"\nSummary: {len(files)} catalog file(s), {total_entries} entr(ies), {len(cards)} card(s) indexed; "
        f"{'OK' if total_errors == 0 else str(total_errors) + ' error(s)'}."
    )
    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(_main())
