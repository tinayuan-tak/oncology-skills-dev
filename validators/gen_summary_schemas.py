#!/usr/bin/env python3
"""gen_summary_schemas.py — generate per-card summary output schemas (T5, 2026-08-11 review).

DEVELOPMENT_GUIDELINES.md (analysis-methods) promised every method output "validates against the
method's per-method output schema in target-contracts/schemas/methods/" and "Drift fails compose-
time validation." That directory and those schemas did not exist. This generator creates them.

Design (per the T5 investigation):
  - Granularity is PER-CARD-SUMMARY, keyed by card_id (NOT per-method: one method can back up to 4
    cards with different summary shapes; the stale schemas/products/*.result.schema.json describe a
    different artifact and are NOT reused).
  - For each card_spec, the schema's field SET comes from outputs.summary_fields (declared contract,
    present on all cards); enums from outputs.summary_fields_vocabulary; list-record shapes from
    outputs.summary_fields_record_schemas when present. Value TYPES are widened using observed
    values harvested from the stub fixtures (skills/compose-dashboard/tests/fixtures/stubs/*.yaml).
  - `additionalProperties: true` (MANDATORY v1): real emitted summaries carry undeclared internal
    `_`-prefixed keys, retired-but-emitted fields, and computed extras — a strict schema would break
    every wired card.
  - `required: []` by default (the primary categorical `*_class` field only, when present, since
    data_unavailable stubs emit just that one key). Tighten per-card later once green.

Opt-in rollout: compose-dashboard validates a card's summary ONLY when
schemas/methods/<card_id>.summary.schema.json exists, so partial coverage never breaks the suite.

Usage:
  python validators/gen_summary_schemas.py --cards cards/ --out schemas/methods/ \\
      [--fixtures <skills>/skills/compose-dashboard/tests/fixtures/stubs/] \\
      [--only card-id-1 --only card-id-2]   # default: all cards
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
DEFAULT_CARDS = REPO / "cards"
DEFAULT_OUT = REPO / "schemas" / "methods"
# Best-effort default fixtures location (sibling skills repo); harvesting is optional.
DEFAULT_FIXTURES = (
    REPO.parent
    / "rnd-computational-biology-oncology-claude-oncology-skills"
    / "skills"
    / "compose-dashboard"
    / "tests"
    / "fixtures"
    / "stubs"
)

_ID_BASE = "https://schemas.onetakeda.oncology/target-contracts/methods"


def _json_type(value) -> str | list[str]:
    """Infer a JSON-Schema type token from an observed Python value."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if value is None:
        return "null"
    return "string"


def _harvest_observed(fixtures_dir: Path, allow_missing: bool = False) -> dict[str, dict[str, set]]:
    """{card_id -> {field -> set(observed json-type tokens)}} across all stub fixtures.

    FAILS LOUDLY when the fixtures directory is absent (2026-09-12). This used to return {}
    silently, and the widening source is now GONE — skills/compose-dashboard/tests/fixtures/stubs/
    does not exist in the sibling skills repo any more. The silent path made a full regeneration
    DESTRUCTIVE and plausible-looking at the same time: every non-enum, non-record property
    collapsed from e.g. ["integer","null","number"] to ["null"], i.e. the committed schema started
    asserting that a real integer field must be null, with no error and a normal-looking summary
    line. Callers that genuinely have no fixtures must say so with --allow-missing-fixtures and
    accept that only cards whose committed schema carries no observed types can be safely rewritten.
    """
    observed: dict[str, dict[str, set]] = {}
    if not fixtures_dir or not fixtures_dir.is_dir():
        if allow_missing:
            return observed
        raise SystemExit(
            f"gen_summary_schemas: fixtures dir not found: {fixtures_dir}\n"
            "  Observed-type widening is the ONLY source of non-enum property types; without it every\n"
            "  such property regenerates as {'type': ['null']}, silently DEGRADING any committed\n"
            "  schema that has real types. Point --fixtures at a stub directory, or pass\n"
            "  --allow-missing-fixtures if you have verified the cards you are regenerating carry no\n"
            "  observed-derived types (diff the result before committing)."
        )
    for fx in sorted(fixtures_dir.glob("*.yaml")):
        try:
            doc = yaml.safe_load(fx.read_text()) or {}
        except yaml.YAMLError:
            continue
        for card_id, summary in doc.items():
            if not isinstance(summary, dict):
                continue
            per_field = observed.setdefault(card_id, {})
            for field, value in summary.items():
                if field.startswith("_"):
                    continue  # internal keys are not part of the declared contract
                per_field.setdefault(field, set()).add(_json_type(value))
    return observed


def _prop_schema(field: str, vocab: dict, records: dict, observed_types: set[str]) -> dict:
    """Build the property schema for one summary field."""
    # Enum fields (categorical) — from summary_fields_vocabulary.
    if field in vocab and isinstance(vocab[field], list):
        return {"type": ["string", "null"], "enum": list(vocab[field]) + [None]}
    # List-of-record fields — from summary_fields_record_schemas (key -> value spec).
    if field in records and isinstance(records[field], dict):
        item_props = {k: _record_key_schema(v) for k, v in records[field].items()}
        return {"type": "array", "items": {"type": "object", "properties": item_props}}
    # Otherwise widen from observed types (+ null, which summaries use liberally for "n/a").
    types = set(observed_types) if observed_types else set()
    # integers and numbers commonly co-occur across fixtures; keep both if either seen.
    if "integer" in types or "number" in types:
        types |= {"integer", "number"}
    types.add("null")
    return {"type": sorted(types)}


def _record_key_schema(decl) -> dict:
    """Property schema for ONE key of a record in summary_fields_record_schemas.

    card.schema.json permits three value-spec forms per key, and the generator honoured only the
    first (2026-09-12 fix). `_map_declared_type` coerces via `str(decl)`, so a dict spec stringified
    to its repr, missed every mapping entry, and fell through to the "string" default — SILENTLY
    discarding the declared enum AND mistyping the key. 13 of the 15 record-schema-bearing cards use
    the dict form (every subgroup-stratified-* `class`/`evidence_state`, genomic-event-model-match
    `model_state`/`screen_role`, ...), so every record-key enum in this directory was being dropped.

      1. bare type string            'string' | 'number' | 'integer' | 'boolean' | 'int' | ...
      2. bare enum list              [strong, partial, none]
      3. object                      {enum: [...], type: string}   <- was lost

    Nullability: record keys are nullable in practice (a subgroup with evidence_state=absent emits
    null metrics; an unmeasured paralog partner emits a null delta), and the declaration has no way
    to say otherwise, so every key is widened with null — matching how scalar enum fields are
    already widened on line 100. Without this a schema built from a correct declaration would REJECT
    correctly-emitted data.
    """
    if isinstance(decl, dict):
        enum = decl.get("enum")
        jtype = _map_declared_type(decl.get("type", "string"))
        if isinstance(enum, list) and enum:
            return {"type": [jtype, "null"], "enum": list(enum) + [None]}
        return {"type": [jtype, "null"]}
    if isinstance(decl, list) and decl:
        return {"type": ["string", "null"], "enum": list(decl) + [None]}
    return {"type": [_map_declared_type(decl), "null"]}


_JSON_TYPES = frozenset({"string", "number", "integer", "boolean", "array", "object", "null"})


def _map_declared_type(decl: str) -> str:
    """Card-declared type token -> JSON-schema type name.

    The alias map covers PYTHON spellings only. card.schema.json's bare-type enum for a record key
    is the JSON-SCHEMA spelling — ["integer", "boolean", "string", "number"] — and none of those
    four were in the map, so `number` and `boolean` fell through to the "string" default and every
    bare-typed record key in every card was generated as a string (2026-09-12 fix). Pass the native
    names through unchanged; keep the aliases for cards that use them.
    """
    token = str(decl)
    if token in _JSON_TYPES:
        return token
    return {
        "int": "integer",
        "float": "number",
        "str": "string",
        "bool": "boolean",
        "list": "array",
        "dict": "object",
    }.get(token, "string")


def build_schema(card_id: str, card_spec: dict, observed: dict[str, set]) -> dict:
    outputs = card_spec.get("outputs", {}) or {}
    # summary_fields entries are usually plain strings, but a card may use the richer dict form
    # {name, lens_conditional_on, description, ...} (e.g. adc-tce-modality-fit's modality-conditional
    # grade fields). Normalize either form to the field NAME (vocab/record_schemas are name-keyed).
    fields = [f["name"] if isinstance(f, dict) else f for f in (outputs.get("summary_fields", []) or [])]
    fields = [f for f in fields if isinstance(f, str)]
    vocab = outputs.get("summary_fields_vocabulary", {}) or {}
    records = outputs.get("summary_fields_record_schemas", {}) or {}

    # Union of declared fields + any observed-in-fixtures fields (declared is the contract; observed
    # catches emitted fields a card_spec forgot to declare — surfaced as properties, not required).
    all_fields = list(dict.fromkeys(fields + list(observed.keys())))

    properties = {f: _prop_schema(f, vocab, records, observed.get(f, set())) for f in all_fields}

    # required: EMPTY in v1. Empirically (validated against the stub fixtures) real summaries do
    # NOT reliably emit even the primary *_class field — the declared summary_fields set is a
    # superset of what any single run emits, and data_unavailable/partial summaries emit arbitrary
    # subsets. Requiring any field breaks legitimate cards on the opt-in gate. The schema's value is
    # TYPE/enum checking of the fields that ARE present; tighten `required` per-card later, only
    # after confirming the field is truly always emitted for that card.
    required: list[str] = []

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{_ID_BASE}/{card_id}.summary.schema.json",
        "title": f"summary output schema for card {card_id}",
        "description": (
            f"Per-card summary-dict contract for '{card_id}', generated by gen_summary_schemas.py "
            "from outputs.summary_fields (+ vocabulary/record schemas) and observed stub fixtures. "
            "additionalProperties:true by design (real summaries carry internal _-keys + computed "
            "extras); required is limited to the primary class field. Tighten per-card as coverage "
            "matures. compose-dashboard validates a summary against this schema ONLY if it exists "
            "(opt-in rollout)."
        ),
        "type": "object",
        "additionalProperties": True,
        "required": required,
        "properties": properties,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cards", type=Path, default=DEFAULT_CARDS)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    ap.add_argument(
        "--only",
        action="append",
        default=None,
        help="Restrict generation to these card_ids (repeatable). Default: all cards.",
    )
    ap.add_argument(
        "--allow-missing-fixtures",
        action="store_true",
        help="Proceed with NO observed-type widening. Only safe for cards whose committed schema "
        "already carries no observed-derived types — diff before committing.",
    )
    ap.add_argument(
        "--allow-new",
        action="store_true",
        help="Also create schemas for cards that have none committed yet (default: refresh only "
        "existing files, so a full run does not emit ~100 untracked files).",
    )
    args = ap.parse_args()

    observed_all = _harvest_observed(args.fixtures, allow_missing=args.allow_missing_fixtures)
    args.out.mkdir(parents=True, exist_ok=True)

    card_files = sorted(args.cards.glob("*.card.yaml"))
    only = set(args.only) if args.only else None
    n_written = 0
    n_skipped_new = 0
    for cf in card_files:
        card_id = cf.name[: -len(".card.yaml")]
        if only and card_id not in only:
            continue
        try:
            card_spec = yaml.safe_load(cf.read_text()) or {}
        except yaml.YAMLError as e:
            print(f"[gen] SKIP {card_id}: YAML error {e}")
            continue
        out_path = args.out / f"{card_id}.summary.schema.json"
        # The committed set is the VERDICT-BEARING subset (the validate_cards ratchet requires a
        # schema only for resolver-consumed cards), but this loop walks all ~148 cards. Writing them
        # all buries the intended diff under ~100 untracked new files. Default to refreshing what is
        # already committed; --allow-new is the deliberate way to extend coverage.
        if not out_path.exists() and not args.allow_new:
            n_skipped_new += 1
            continue
        schema = build_schema(card_id, card_spec, observed_all.get(card_id, {}))
        out_path.write_text(json.dumps(schema, indent=2) + "\n")
        n_written += 1
        print(
            f"[gen] {card_id}: {len(schema['properties'])} fields, "
            f"required={schema['required']}, observed={'yes' if card_id in observed_all else 'no'}"
        )
    print(f"\nWrote {n_written} summary schema(s) → {args.out}")
    if n_skipped_new:
        print(f"Skipped {n_skipped_new} card(s) with no committed schema (pass --allow-new to create them).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
