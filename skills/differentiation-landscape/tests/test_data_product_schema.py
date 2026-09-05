"""Emitted data-product contract guard for differentiation-landscape.

Pins the emitted shape against the SELF-CONTAINED generated schema
`target-contracts/schemas/skills/differentiation-landscape.decision.schema.json`. Shared helpers in
`_skills_common.data_product_contract`. Static golden trimmed → static check skips; load-bearing
conformance is the FRESH replay emit (test_differentiation_replay.py). CI-liveness: schema unresolvable
→ SKIP locally, FAIL in CI.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

SKILL = "differentiation-landscape"
SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
GOLDEN = SKILL_DIR / "tests" / "fixtures" / "kras_coadread_decision.json"

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


def test_static_golden_conforms():
    jsonschema = pytest.importorskip("jsonschema")
    schema = _schema_or_gate()
    if not GOLDEN.exists():
        pytest.skip(f"no golden at {GOLDEN}")
    decision = json.loads(GOLDEN.read_text())
    if not is_full_decision(decision):
        pytest.skip("golden is a trimmed fixture (not a full decision) — see the replay conformance test")
    errors = conformance_errors(schema, decision)
    assert not errors, "static golden violates the data-product schema:\n  " + "\n  ".join(
        f"{list(e.path)}: {e.message}" for e in errors[:15])
