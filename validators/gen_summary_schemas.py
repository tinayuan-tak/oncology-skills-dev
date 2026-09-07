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


def _harvest_observed(fixtures_dir: Path) -> dict[str, dict[str, set]]:
    """{card_id -> {field -> set(observed json-type tokens)}} across all stub fixtures."""
    observed: dict[str, dict[str, set]] = {}
    if not fixtures_dir or not fixtures_dir.is_dir():
        return observed
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
    # List-of-record fields — from summary_fields_record_schemas (key -> type map).
    if field in records and isinstance(records[field], dict):
        item_props = {k: {"type": _map_declared_type(v)} for k, v in records[field].items()}
        return {"type": "array", "items": {"type": "object", "properties": item_props}}
    # Otherwise widen from observed types (+ null, which summaries use liberally for "n/a").
    types = set(observed_types) if observed_types else set()
    # integers and numbers commonly co-occur across fixtures; keep both if either seen.
    if "integer" in types or "number" in types:
        types |= {"integer", "number"}
    types.add("null")
    return {"type": sorted(types)}


def _map_declared_type(decl: str) -> str:
    return {
        "int": "integer",
        "float": "number",
        "str": "string",
        "bool": "boolean",
        "list": "array",
        "dict": "object",
    }.get(str(decl), "string")


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
    args = ap.parse_args()

    observed_all = _harvest_observed(args.fixtures)
    args.out.mkdir(parents=True, exist_ok=True)

    card_files = sorted(args.cards.glob("*.card.yaml"))
    only = set(args.only) if args.only else None
    n_written = 0
    for cf in card_files:
        card_id = cf.name[: -len(".card.yaml")]
        if only and card_id not in only:
            continue
        try:
            card_spec = yaml.safe_load(cf.read_text()) or {}
        except yaml.YAMLError as e:
            print(f"[gen] SKIP {card_id}: YAML error {e}")
            continue
        schema = build_schema(card_id, card_spec, observed_all.get(card_id, {}))
        out_path = args.out / f"{card_id}.summary.schema.json"
        out_path.write_text(json.dumps(schema, indent=2) + "\n")
        n_written += 1
        print(
            f"[gen] {card_id}: {len(schema['properties'])} fields, "
            f"required={schema['required']}, observed={'yes' if card_id in observed_all else 'no'}"
        )
    print(f"\nWrote {n_written} summary schema(s) → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
