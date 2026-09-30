#!/usr/bin/env python3
"""
validate_expression_property_enum.py — referential-integrity validator for
vocabularies/expression_property.enum.yaml. Issue #2233; epic #1507.

WHY THIS EXISTS. `magnitude.resolves_from.measurements` named `control_target_percentile`, a field
no card declares — the correct name is `allgene_percentile` (the card deliberately reverted the
former as a redundant echo; see cellline-rna-distribution.card.yaml). Nothing machine-read
`resolves_from`, so the rot went unnoticed. This is the class of defect
`validate_property_catalog.py`'s referential clause (clause 2 there) already prevents for
vocabularies/property_catalog/ — a `card_id`/field that does not resolve is RED there. This file
extends that same clause to expression_property.enum.yaml, the one governed vocabulary that still
lacked it. `validate_concordance_enum.py` clause 7 is the structural analogue for a different
reference kind (a `builder` path + `builder_function` must exist) — same shape, different subject.

WHAT THIS ENFORCES:

  1. SHAPE / STRICT KEYS. Required top-level keys; `enum_id` equals the filename stem (minus
     `.enum.yaml`); semver `version`; `properties` a non-empty list of property entries, each with a
     closed key set, a snake_case `id`, and `status` in {resolvable, fleet_deferred}.

  2. DECLARATION-VS-STATUS. A `resolvable` property MUST carry `resolves_from` (with at least one
     `card` and a non-empty `measurements` list) and a non-empty `values` list; a `fleet_deferred`
     property MUST NOT carry `resolves_from` — it reserves the name without committing to a
     measurement path (see the file's own SCOPE header comment).

  3. REFERENTIAL INTEGRITY AGAINST CARDS — the load-bearing clause, reusing
     `validate_property_catalog.card_field_index()` rather than growing a third copy of it. Every
     `resolves_from.card` must exist in cards/*.card.yaml, and every name in
     `resolves_from.measurements` must appear in that card's `outputs.summary_fields`. A name that
     does not resolve is a claim of traceability to a measurement that does not exist.

WHAT IT DELIBERATELY DOES NOT DO. It does not enforce full vocabulary governance parity with
`validate_concordance_enum.py` / `validate_comparability_state.py` (no additivity clause, no
per-value SIGNAL_ORD cross-check) — this file's scope is the referential defect #2233 named plus the
minimal shape needed to iterate safely. Broader governance parity is a separate, larger change if
ever wanted.

Usage:
  python validators/validate_expression_property_enum.py
  python validators/validate_expression_property_enum.py --enum vocabularies/expression_property.enum.yaml --cards cards/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

# Reuse, do not re-implement (per the issue's own instruction): `card_field_index()` already builds
# exactly the index this file's load-bearing clause needs.
from validate_property_catalog import (  # noqa: E402  (path-relative sibling import, see __main__)
    _SEMVER,
    _SNAKE,
    CONTRACTS_ROOT,
    Report,
    _nonempty_str,
    _strict_keys,
    card_field_index,
)

TOP_KEYS = {"enum_id", "version", "description", "signal_ord_reference", "governance", "properties"}
REQUIRED_TOP_KEYS = ("enum_id", "version", "description", "properties")

PROPERTY_KEYS = {
    "id",
    "label",
    "status",
    "polarity",
    "description",
    "resolves_from",
    "values",
}
REQUIRED_PROPERTY_KEYS = ("id", "label", "status", "polarity", "description", "values")
VALID_STATUS = {"resolvable", "fleet_deferred"}

RESOLVES_FROM_KEYS = {"card", "measurements"}


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
    ver = doc.get("version")
    if not isinstance(ver, str) or not _SEMVER.match(ver):
        r.err(f"{where}: `version` must be semver MAJOR.MINOR.PATCH, got {ver!r}")
    _nonempty_str(r, where, doc, "description")


def _check_resolves_from(
    r: Report, where: str, prop_id: str, resolves_from: dict, cards: "dict[str, set[str]] | None"
) -> None:
    """Clause 3 — the load-bearing referential clause. Deliberately NOT skipped when `cards` is
    None (cards/ missing/unreadable): a missing corpus makes this clause RED, because silently
    dropping the only referential check would make a green run meaningless (mirrors
    validate_property_catalog.py clause 2)."""
    w = f"{where}.properties[{prop_id}].resolves_from"
    if not isinstance(resolves_from, dict):
        r.err(f"{w}: must be a mapping with {sorted(RESOLVES_FROM_KEYS)}")
        return
    _strict_keys(r, w, resolves_from, RESOLVES_FROM_KEYS)
    card_id = resolves_from.get("card")
    if not isinstance(card_id, str) or not card_id:
        r.err(f"{w}: missing `card`")
        card_id = None
    measurements = resolves_from.get("measurements")
    if not isinstance(measurements, list) or not measurements:
        r.err(f"{w}: `measurements` must be a non-empty list")
        measurements = []

    if cards is None:
        r.err(
            f"{w}: could not read the card index from cards/*.card.yaml — the referential clause "
            f"is this validator's load-bearing check and must not be skipped"
        )
        return
    if card_id is None:
        return
    if card_id not in cards:
        r.err(f"{w}: card `{card_id}` has no cards/{card_id}.card.yaml — dangling reference")
        return
    unknown = sorted(m for m in measurements if isinstance(m, str) and m not in cards[card_id])
    if unknown:
        r.err(
            f"{w}: measurement(s) {unknown} are not declared by `{card_id}` "
            f"(outputs.summary_fields) — the property cannot be traced to this measurement. "
            f"Declared fields on this card: {sorted(cards[card_id])}"
        )


def _check_properties(r: Report, where: str, doc: dict, cards: "dict[str, set[str]] | None") -> list:
    """Clauses 1 (per-entry shape) and 2 (declaration-vs-status). Returns the parsed property list."""
    props = doc.get("properties")
    if not isinstance(props, list) or not props:
        r.err(f"{where}: `properties` must be a non-empty list")
        return []
    seen: set = set()
    for i, entry in enumerate(props):
        w = f"{where}.properties[{i}]"
        if not isinstance(entry, dict):
            r.err(f"{w}: must be a mapping")
            continue
        _strict_keys(r, w, entry, PROPERTY_KEYS)
        for k in REQUIRED_PROPERTY_KEYS:
            if k not in entry:
                r.err(f"{w}: missing required key `{k}`")
        pid = entry.get("id")
        if not isinstance(pid, str) or not _SNAKE.match(pid or ""):
            r.err(f"{w}: `id` must be a snake_case token, got {pid!r}")
            continue
        w = f"{where}.properties[{pid}]"
        if pid in seen:
            r.err(f"{w}: duplicate property id `{pid}`")
        seen.add(pid)

        status = entry.get("status")
        if status not in VALID_STATUS:
            r.err(f"{w}: `status` must be one of {sorted(VALID_STATUS)}, got {status!r}")

        resolves_from = entry.get("resolves_from")
        values = entry.get("values")
        if not isinstance(values, list) or not values:
            r.err(f"{w}: `values` must be a non-empty list")

        # CLAUSE 2 — declaration is not emission, restated for status: a `resolvable` property
        # claims a measurement path exists; a `fleet_deferred` property explicitly has none yet
        # (the file's own header: "reserves the names without committing to a value set/measurement
        # path"). Asserting BOTH directions catches either a resolvable property with no traceable
        # path, or a deferred property silently claiming one it should not have.
        if status == "resolvable":
            if resolves_from is None:
                r.err(
                    f"{w}: `status: resolvable` requires `resolves_from` — a resolvable property "
                    f"must declare how it is traced to a measurement"
                )
            else:
                _check_resolves_from(r, where, pid, resolves_from, cards)
        elif status == "fleet_deferred" and resolves_from is not None:
            r.err(
                f"{w}: `status: fleet_deferred` may NOT carry `resolves_from` — a deferred property "
                f"reserves the name without claiming a measurement path that does not exist yet"
            )
    return props


def validate_file(enum_path: Path, cards: "dict[str, set[str]] | None") -> Report:
    r = Report()
    try:
        doc = yaml.safe_load(enum_path.read_text()) or {}
    except (OSError, yaml.YAMLError) as exc:
        r.err(f"{enum_path}: could not be read as YAML: {exc}")
        return r
    if not isinstance(doc, dict):
        r.err(f"{enum_path}: top level must be a mapping")
        return r

    _check_shape(r, enum_path, doc)
    _check_properties(r, enum_path.name, doc, cards)
    return r


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument(
        "--enum",
        type=Path,
        default=CONTRACTS_ROOT / "vocabularies" / "expression_property.enum.yaml",
    )
    ap.add_argument("--cards", type=Path, default=CONTRACTS_ROOT / "cards")
    args = ap.parse_args(argv)

    print("validate_expression_property_enum.py results:")
    if not args.enum.is_file():
        print(f"  [ERROR]   enum file {args.enum} does not exist")
        return 1

    cards = card_field_index(args.cards)
    if cards is None:
        print(
            f"  [ERROR]   {args.cards} not found/unreadable — the referential clause against card "
            f"summary fields is this validator's load-bearing check and must not be skipped"
        )

    r = validate_file(args.enum, cards)
    for e in r.errors:
        print(f"  [ERROR]   {e}")
    for w in r.warnings:
        print(f"  [WARNING] {w}")

    try:
        doc = yaml.safe_load(args.enum.read_text()) or {}
    except yaml.YAMLError:
        doc = {}
    props = doc.get("properties") if isinstance(doc, dict) and isinstance(doc.get("properties"), list) else []
    resolvable = [p for p in props if isinstance(p, dict) and p.get("status") == "resolvable"]
    print(
        f"\nSummary: {len(props)} propert(ies), {len(resolvable)} resolvable; "
        f"{'OK' if r.ok else str(len(r.errors)) + ' error(s)'}."
    )
    return 0 if r.ok else 1


if __name__ == "__main__":
    # Sibling import: running this as a script puts validators/ on sys.path[0], so
    # `from validate_property_catalog import ...` resolves. The tests load this module by path and do
    # the same insertion explicitly.
    sys.exit(_main())
