"""Guards for the skill emitted-output contract schemas (repo-local).

The finalized target-profile skill data products pin their EMITTED decision.json against:
  - schemas/skill_report.schema.json    — SHARED spine SOURCE (canonical, strict)
  - schemas/skill_decision.schema.json  — SHARED envelope SOURCE (canonical)
  - schemas/_skill_output/pins/<skill>.pins.json  — per-skill thin pins SOURCE
  - schemas/skills/<skill>.decision.schema.json   — GENERATED, self-contained, committed

This test guards the SCHEMAS THEMSELVES: sources + generated files are valid Draft 2020-12 schemas,
every generated per-skill schema is SELF-CONTAINED (no cross-file/network $ref — house style, and it
lets a naive validator work with no registry), and the committed generated files are IN SYNC with the
generator (a hand-edit or an un-regenerated source edit fails here). Glob-based, so each new per-skill
schema is auto-covered. (Instance conformance — a skill's emitted decision.json against its schema — is
ratcheted in the skills repo, where the goldens/replays live.)
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCHEMAS = REPO / "schemas"
SHARED = [SCHEMAS / "skill_report.schema.json", SCHEMAS / "skill_decision.schema.json"]
GENERATED = sorted((SCHEMAS / "skills").glob("*.decision.schema.json"))
# Hand-authored bespoke per-skill emit schemas for AUX skills whose output is NOT the fan-out
# skill_decision envelope (no run_health / headline.skill_report). These have NO pin and are NOT
# produced by the generator, so they are exempt from the in-sync ratchet — but they must still be
# valid, self-contained Draft 2020-12 schemas. Glob-based, so each new bespoke schema is auto-covered.
BESPOKE = sorted((SCHEMAS / "skills").glob("*.emit.schema.json"))
GEN_SCRIPT = REPO / "validators" / "gen_skill_output_schemas.py"


def _load(p: Path) -> dict:
    return json.loads(p.read_text())


def _external_refs(node, out: list):
    """Collect any $ref that is not an internal JSON-pointer (`#/...`)."""
    if isinstance(node, dict):
        r = node.get("$ref")
        if isinstance(r, str) and not r.startswith("#"):
            out.append(r)
        for v in node.values():
            _external_refs(v, out)
    elif isinstance(node, list):
        for v in node:
            _external_refs(v, out)
    return out


@pytest.mark.parametrize("path", SHARED + GENERATED + BESPOKE, ids=lambda p: p.name)
def test_schema_valid_json_and_draft(path: Path):
    assert path.exists(), f"missing schema {path}"
    doc = _load(path)
    assert doc.get("$schema", "").endswith("2020-12/schema"), f"{path.name}: expected Draft 2020-12"


@pytest.mark.parametrize("path", SHARED + GENERATED + BESPOKE, ids=lambda p: p.name)
def test_schema_meta_valid(path: Path):
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(_load(path))  # raises SchemaError if invalid


def test_shared_sources_present():
    for p in SHARED:
        assert p.exists(), f"shared contract source missing: {p}"


@pytest.mark.skipif(not (GENERATED or BESPOKE), reason="no per-skill schemas yet")
@pytest.mark.parametrize("path", GENERATED + BESPOKE, ids=lambda p: p.name)
def test_generated_is_self_contained(path: Path):
    """No cross-file/network $ref — a naive validator must work with no registry (house style)."""
    ext = _external_refs(_load(path), [])
    assert not ext, f"{path.name} has non-internal $ref(s): {ext} (spine/envelope must be embedded)"


def test_generated_schemas_in_sync():
    """The committed generated files == generator output. A hand-edit or an un-regenerated source
    edit (spine/envelope/pins) fails here — the in-sync ratchet."""
    spec = importlib.util.spec_from_file_location("_gen_skill_output", GEN_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.generate_all(check=True) == 0, (
        "generated per-skill schemas are OUT OF SYNC — run: python validators/gen_skill_output_schemas.py")
