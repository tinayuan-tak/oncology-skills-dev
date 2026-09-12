"""gen_summary_schemas must not silently downgrade a declared record-key spec (2026-09-12).

`summary_fields_record_schemas` is the ONLY place a card can declare the shape of a list-of-record
summary field, and card.schema.json permits three per-key value-spec forms: a bare JSON-schema type
name, a bare enum list, and an object `{enum: [...], type: string}`. The generator honoured none of
them faithfully:

  1. `_map_declared_type` coerced with `str(decl)`, so the OBJECT form stringified to its repr,
     missed every alias-map entry, and fell through to the "string" default — the declared enum was
     discarded outright. 13 of the 15 record-schema-bearing cards use that form.
  2. The alias map held PYTHON spellings only (int/float/str/bool). card.schema.json's bare-type
     enum is the JSON-SCHEMA spelling (integer/boolean/string/number), so `number` and `boolean`
     ALSO fell through to "string" — every bare-typed record key in every card was mistyped.

Both failures are invisible in the generator's output: it prints a normal per-card line and writes a
well-formed schema that simply asserts less (or the wrong thing) than the card declared. These tests
pin each spec form to what it must produce, so a regression is a failing assert rather than a quietly
weaker contract.

Also pinned: the fixtures-missing path must RAISE. skills/compose-dashboard/tests/fixtures/stubs/ no
longer exists, and observed-type widening is the only source of non-enum property types — the old
silent `return {}` turned a full regeneration into a destructive no-warning rewrite that collapsed
every such property to {"type": ["null"]}.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load(mod_name: str):
    spec = importlib.util.spec_from_file_location(mod_name, REPO / "validators" / f"{mod_name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


GEN = _load("gen_summary_schemas")


# --- (1) the object form must keep its enum ---------------------------------------------------


def test_object_form_record_key_keeps_its_enum():
    got = GEN._record_key_schema({"enum": ["measured", "underpowered", "absent"], "type": "string"})
    assert got.get("enum") == ["measured", "underpowered", "absent", None], (
        "the {enum: [...], type: string} record-key form lost its enum — this is the form 13 of the "
        f"15 record-schema-bearing cards use for `class`/`evidence_state`. got={got}"
    )
    assert got["type"] == ["string", "null"]


def test_bare_enum_list_record_key_keeps_its_enum():
    got = GEN._record_key_schema(["strong", "partial", "none", "unmeasured"])
    assert got.get("enum") == ["strong", "partial", "none", "unmeasured", None], got


# --- (2) JSON-schema-native type names must survive -------------------------------------------


@pytest.mark.parametrize("token", ["string", "number", "integer", "boolean", "array", "object"])
def test_json_schema_native_type_names_pass_through(token):
    assert GEN._map_declared_type(token) == token, (
        f"declared record-key type {token!r} was rewritten to {GEN._map_declared_type(token)!r}. "
        "card.schema.json's bare-type enum is the JSON-schema spelling, so a pass-through is the "
        "whole contract — mapping `number` to `string` mistypes every numeric record key."
    )


@pytest.mark.parametrize(
    ("alias", "expected"),
    [("int", "integer"), ("float", "number"), ("str", "string"), ("bool", "boolean")],
)
def test_python_aliases_still_map(alias, expected):
    """The alias map predates the native names; cards using it must not break."""
    assert GEN._map_declared_type(alias) == expected


def test_bare_type_record_key_is_nullable():
    """Record keys ARE null in practice (evidence_state=absent emits null metrics; an unmeasured
    paralog partner emits a null delta) and the declaration cannot say so, so the generated property
    must accept null or it would reject correctly-emitted data."""
    assert GEN._record_key_schema("number") == {"type": ["number", "null"]}


def test_unknown_token_still_degrades_to_string():
    """Unchanged fallback — an unrecognised token is a string, not a crash."""
    assert GEN._map_declared_type("gene_symbol") == "string"


# --- (3) missing fixtures must be loud, not silent --------------------------------------------


def test_missing_fixtures_dir_raises_by_default(tmp_path):
    with pytest.raises(SystemExit) as exc:
        GEN._harvest_observed(tmp_path / "does-not-exist")
    assert "fixtures dir not found" in str(exc.value)


def test_missing_fixtures_dir_is_opt_out_able(tmp_path):
    assert GEN._harvest_observed(tmp_path / "does-not-exist", allow_missing=True) == {}


def test_present_fixtures_dir_still_harvests(tmp_path):
    """Anti-vacuous: the guard must not have broken the happy path."""
    fx = tmp_path / "stubs"
    fx.mkdir()
    (fx / "a.yaml").write_text("some-card:\n  n_things: 3\n  label: hi\n  _internal: 1\n")
    observed = GEN._harvest_observed(fx)
    assert observed["some-card"]["n_things"] == {"integer"}
    assert observed["some-card"]["label"] == {"string"}
    assert "_internal" not in observed["some-card"], "underscore keys are not part of the contract"


# --- (4) end-to-end on the real card that exposed all of this ---------------------------------


def test_paralog_buffering_schema_matches_its_card():
    """The committed artifact must agree with the card it is generated from."""
    import json

    import yaml

    card = yaml.safe_load((REPO / "cards" / "paralog-buffering.card.yaml").read_text())
    schema = json.loads((REPO / "schemas" / "methods" / "paralog-buffering.summary.schema.json").read_text())

    declared = card["outputs"]["summary_fields_vocabulary"]["paralog_buffering_class"]
    assert schema["properties"]["paralog_buffering_class"]["enum"] == list(declared) + [None]

    rec = card["outputs"]["summary_fields_record_schemas"]["functional_paralogs"]
    props = schema["properties"]["functional_paralogs"]["items"]["properties"]
    assert set(props) == set(rec), f"record keys drifted: schema={sorted(props)} card={sorted(rec)}"
    assert props["buffering_class"]["enum"] == list(rec["buffering_class"]["enum"]) + [None]
    assert props["ohnolog"]["type"] == ["boolean", "null"]
    assert props["dep_delta_paired_vs_max_single"]["type"] == ["number", "null"]
