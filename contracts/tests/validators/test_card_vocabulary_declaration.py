"""Guards for `validate_cards._summary_vocabulary_declaration_check` — a vocabulary must have a field.

WHY THIS EXISTS. A `summary_fields_vocabulary` entry is a card's enumerated value set for one summary
field. If the field it keys is declared nowhere — absent from `outputs.summary_fields` AND not a key of
any declared `summary_fields_record_schemas` record — the enum is attached to nothing, and it is
silently DROPPED rather than rejected: `validators/gen_summary_schemas.py` builds `properties` from
`summary_fields` unioned with the observed keys, so an orphan key gets no property at all and its enum
never reaches the generated schema. Nothing downstream can notice, because that generator makes
`additionalProperties: true` mandatory in v1 — a strict schema "would break every wired card" (measured
independently on the skills side: 97 of 135 wired cards emit at least one undeclared summary key).

PROVEN ON A COMMITTED ARTIFACT, not argued. `prism-compound-activity` declares a 3-value enum for
`metric_source` (log2auc / single_dose_lfc / annotation_only), and
`schemas/methods/prism-compound-activity.summary.schema.json` carries 7 properties, none of them
`metric_source`. The enum is already gone on trunk. The other three orphans have no generated schema
yet — the summary-schema rollout is opt-in — so their loss is armed rather than shipped.

SCOPE, measured over every card: 289 vocabulary keys across 148 cards, of which 4 are orphans. All 136
vocabulary blocks in the repo live under `outputs`, so there is no per-lens block whose keys would need
matching against a different field list.

★ THE RECORD-SCHEMA ARM IS LOAD-BEARING, AND WITHOUT IT THIS CHECK HAS A 20% FALSE-POSITIVE RATE. The
naive invariant (`vocabulary ⊆ summary_fields`) flags FIVE cards, but
`tumor-vs-normal-percentile-crossing-by-subtype.percentile_crossing_class` is a legitimately declared
key of that card's `per_subgroup_metrics` record — a per-record class needs a vocabulary as much as a
scalar one does. `test_a_record_schema_key_is_a_legal_vocabulary_target` pins that, so the arm cannot be
removed as dead code.

★ IT ALSO CLOSES A COMPOSITION HOLE ON THE SKILLS SIDE. The live emission guard
(`skills/_skills_common/tests/test_card_output_emission.py`) relaxes its missing-field check for a WHOLE
card when any vocabulary field emits a data-unavailable marker, and that predicate iterates VOCABULARY
keys rather than declared field names — so an ORPHAN key's abstain value can today switch off the
presence check for a card's genuinely declared fields. Once every vocabulary key is a declared field,
that path is unreachable from an undeclared one.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
CARDS = REPO / "cards"


def _load_validator():
    spec = importlib.util.spec_from_file_location("_vc_vocab", REPO / "validators" / "validate_cards.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_vc_vocab"] = mod
    spec.loader.exec_module(mod)
    return mod


VC = _load_validator()


def _specs() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in sorted(CARDS.glob("*.yaml")):
        spec = yaml.safe_load(path.read_text())
        if isinstance(spec, dict):
            out[spec.get("card_id") or path.stem] = spec
    return out


def _errors(spec: dict) -> list[str]:
    report = VC.ValidationReport(card_path="<test>")
    VC._summary_vocabulary_declaration_check(spec, report)
    return report.errors


def test_no_card_has_an_unwaived_vocabulary_orphan():
    """Fleet-level: every shipped card is either clean or explicitly waived by name."""
    offenders = {cid: _errors(spec) for cid, spec in _specs().items() if _errors(spec)}
    assert not offenders, "cards with an unwaived summary_fields_vocabulary orphan:\n" + "\n".join(
        f"  {cid}: {errs}" for cid, errs in sorted(offenders.items())
    )


def test_the_waiver_list_is_exactly_the_orphan_set():
    """TWO-SIDED, which is what stops the waiver outliving the debt.

    A new orphan cannot join silently, and an entry that stops being an orphan (field declared at last,
    record schema added, or vocabulary entry dropped) fails until it is deleted. Compared as
    card -> field names, never as a count: a count cannot tell a fixed orphan from a fresh one.
    """
    measured = {cid: orphans for cid, spec in _specs().items() if (orphans := VC._vocabulary_orphans(spec))}
    assert measured == VC.KNOWN_VOCABULARY_ORPHANS, (
        f"measured orphans {measured!r} != KNOWN_VOCABULARY_ORPHANS {VC.KNOWN_VOCABULARY_ORPHANS!r}.\n"
        f"  newly orphaned (declare the field, or the record schema it belongs to): "
        f"{ {k: v - VC.KNOWN_VOCABULARY_ORPHANS.get(k, set()) for k, v in measured.items() if v - VC.KNOWN_VOCABULARY_ORPHANS.get(k, set())} }\n"
        f"  no longer orphaned (delete the waiver entry): "
        f"{ {k: v - measured.get(k, set()) for k, v in VC.KNOWN_VOCABULARY_ORPHANS.items() if v - measured.get(k, set())} }"
    )


def test_a_new_orphan_fails():
    """The check must actually fire — a vocabulary key naming no declared field is an error."""
    spec = {
        "card_id": "synthetic-card",
        "outputs": {
            "summary_fields": ["real_class"],
            "summary_fields_vocabulary": {"real_class": ["a", "b"], "ghost_class": ["x", "y"]},
        },
    }
    errors = _errors(spec)
    assert len(errors) == 1, errors
    assert "ghost_class" in errors[0] and "VOCABULARY_ORPHAN_FIELD" in errors[0]
    assert "real_class" not in errors[0], "the declared field must not be reported"


def test_a_record_schema_key_is_a_legal_vocabulary_target():
    """The false-positive guard. A per-record class carries a vocabulary too, so a key of a declared
    `summary_fields_record_schemas` record is a legal target — this is 1 of the 5 naive hits, i.e. the
    difference between 4 real findings and a 20% false-positive rate. Stripping the record schema must
    turn the SAME card red, which is what proves the arm is live rather than decorative."""
    spec = _specs()["tumor-vs-normal-percentile-crossing-by-subtype"]
    assert "percentile_crossing_class" in spec["outputs"]["summary_fields_vocabulary"], "fixture drifted"
    assert "percentile_crossing_class" not in VC._summary_field_names(spec), (
        "fixture drifted: the field is now a scalar summary_field, so this card no longer exercises the "
        "record-schema arm — repoint the test at another record-keyed vocabulary."
    )
    assert not _errors(spec), "a declared record-schema key must be accepted"

    stripped = copy.deepcopy(spec)
    stripped["outputs"].pop("summary_fields_record_schemas")
    errors = _errors(stripped)
    assert len(errors) == 1 and "percentile_crossing_class" in errors[0], (
        f"with its record schema removed the card must be an orphan, else the arm is untested: {errors}"
    )


def test_a_stale_waiver_fails(monkeypatch):
    """A waiver for a field that is no longer an orphan is itself an error."""
    monkeypatch.setitem(VC.KNOWN_VOCABULARY_ORPHANS, "synthetic-card", {"already_declared"})
    spec = {
        "card_id": "synthetic-card",
        "outputs": {"summary_fields": ["already_declared"], "summary_fields_vocabulary": {"already_declared": ["a"]}},
    }
    errors = _errors(spec)
    assert len(errors) == 1, errors
    assert "KNOWN_VOCABULARY_ORPHANS" in errors[0] and "already_declared" in errors[0]


def test_each_waived_orphan_is_absent_from_any_generated_summary_schema():
    """The waiver's JUSTIFICATION, kept checkable rather than asserted in a comment.

    The reason an orphan matters is that its enum never reaches the generated schema. Where a generated
    schema exists for a waived card, assert the loss is real. Only `prism-compound-activity` has one
    today (7 properties, no `metric_source`); the loop skips the other three, and skips any card whose
    waiver is deleted — so fixing a card reds exactly one test (the two-sided one), not two.
    """
    checked = []
    for card_id, fields in sorted(VC.KNOWN_VOCABULARY_ORPHANS.items()):
        schema_path = REPO / "schemas" / "methods" / f"{card_id}.summary.schema.json"
        if not schema_path.is_file():
            continue
        properties = json.loads(schema_path.read_text()).get("properties", {})
        for name in sorted(fields):
            assert name not in properties, (
                f"{card_id}: {name!r} IS a property of {schema_path.name}, so it is not costing an enum "
                f"— the waiver's stated justification no longer holds. Re-check whether it is an orphan."
            )
            checked.append(f"{card_id}.{name}")
    assert checked, (
        "no waived orphan has a generated summary schema, so this test asserted nothing — if the "
        "summary-schema rollout has moved on, that is fine; if the waiver list is empty, delete this test."
    )


# ── outputs.summary_fields_scalar_types (top-level scalar type declarations, added 2026-09-16) ──────────
# The card.schema.json `oneOf` already validates the type VALUE ('string'/'boolean'/… or enum). These pin
# the KEY: a scalar-type declaration must name a real declared field, mirroring the vocabulary-orphan arm.
def _scalar_type_orphans(spec: dict) -> list[str]:
    outputs = spec.get("outputs") or {}
    scalar_types = outputs.get("summary_fields_scalar_types") or {}
    if not scalar_types:
        return []
    declared = {f for f in (outputs.get("summary_fields") or []) if isinstance(f, str)}
    for record in (outputs.get("summary_fields_record_schemas") or {}).values():
        if isinstance(record, dict):
            declared |= set(record.keys())  # a per-record key is a legal target, same as vocabulary
    return sorted(k for k in scalar_types if k not in declared)


def test_no_card_declares_a_scalar_type_for_an_undeclared_field():
    """Fleet-level: every summary_fields_scalar_types key names a declared summary_field (or record key)."""
    offenders = {cid: orphans for cid, spec in _specs().items() if (orphans := _scalar_type_orphans(spec))}
    assert not offenders, "scalar-type keys naming no declared summary_field:\n" + "\n".join(
        f"  {cid}: {orphans}" for cid, orphans in sorted(offenders.items())
    )


def test_scalar_type_orphan_check_actually_fires():
    """The arm must be live — a scalar-type key naming no declared field is reported, a declared one is not."""
    spec = {
        "outputs": {
            "summary_fields": ["real_flag"],
            "summary_fields_scalar_types": {"real_flag": "boolean", "ghost_flag": "boolean"},
        }
    }
    assert _scalar_type_orphans(spec) == ["ghost_flag"]
