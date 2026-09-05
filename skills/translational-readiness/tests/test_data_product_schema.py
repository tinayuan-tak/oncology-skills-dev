"""Emitted data-product contract guard for translational-readiness.

Pins the emitted shape against the SELF-CONTAINED generated schema
`target-contracts/schemas/skills/translational-readiness.decision.schema.json`. Shared helpers in
`_skills_common.data_product_contract`.

Gateless multi-vector (verdict_fn=None → skill_report.call is null). No replay harness, so the
load-bearing conformance target is a FROZEN FULL emit `fixtures/translational_full_emit.json`
(a real KRAS·COADREAD run). CI-liveness: schema unresolvable → SKIP locally, FAIL in CI.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

SKILL = "translational-readiness"
SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
FULL_GOLDEN = SKILL_DIR / "tests" / "fixtures" / "translational_full_emit.json"

if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))
from _skills_common.data_product_contract import (  # noqa: E402
    conformance_errors, is_full_decision, load_schema, schema_path)


def _schema_or_gate() -> dict:
    schema = load_schema(SKILL)
    if schema is not None:
        return schema
    reason = (f"data-product schema not found at {schema_path(SKILL)} — set TARGET_CONTRACTS_ROOT / "
              f"land the contracts schema PR first")
    if os.environ.get("CI"):
        pytest.fail(reason + " [CI: the ratchet must be live, not skipped]")
    pytest.skip(reason)


def test_schema_is_wellformed():
    jsonschema = pytest.importorskip("jsonschema")
    schema = _schema_or_gate()
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema.get("version"), "data-product schema must carry a contract `version`"


def test_full_emit_conforms():
    """The frozen FULL emit (a real KRAS·COADREAD run) must validate — the load-bearing conformance target
    (translational-readiness is gateless/multi-vector with no replay harness). Confirms skill_report.call
    is null + role descriptive."""
    schema = _schema_or_gate()
    assert FULL_GOLDEN.exists(), f"missing full-emit conformance fixture {FULL_GOLDEN}"
    decision = json.loads(FULL_GOLDEN.read_text())
    assert is_full_decision(decision), "fixture is not a full decision — refreeze from a real run.py emit"
    errors = conformance_errors(schema, decision)
    assert not errors, "full emit violates the data-product schema:\n  " + "\n  ".join(
        f"{list(e.path)}: {e.message}" for e in errors[:15])
