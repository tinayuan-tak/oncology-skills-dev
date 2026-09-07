"""Emitted data-product contract guard for immune-context.

Pins the emitted shape against the SELF-CONTAINED generated schema
`target-contracts/schemas/skills/immune-context.decision.schema.json`. Shared helpers in
`_skills_common.data_product_contract`.

immune-context has no card-replay harness (its verdict card is indication-level / target-independent), so
the load-bearing conformance target is a FULL emit frozen from a real run —
`fixtures/immune_full_emit.json` (CD8A·COADREAD → immune_intermediate; full envelope +
skill_report). The legacy `kras_coadread_decision.json` is a trimmed evidence-graph fixture and is not a
full-decision target (skipped). CI-liveness: schema unresolvable → SKIP locally, FAIL in CI.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

SKILL = "immune-context"
SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
FULL_GOLDEN = SKILL_DIR / "tests" / "fixtures" / "immune_full_emit.json"

if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))
from _skills_common.data_product_contract import (  # noqa: E402
    conformance_errors,
    is_full_decision,
    load_schema,
    schema_path,
)


def _schema_or_gate() -> dict:
    schema = load_schema(SKILL)
    if schema is not None:
        return schema
    reason = (
        f"data-product schema not found at {schema_path(SKILL)} — set TARGET_CONTRACTS_ROOT / "
        f"land the contracts schema PR first"
    )
    if os.environ.get("CI"):
        pytest.fail(reason + " [CI: the ratchet must be live, not skipped]")
    pytest.skip(reason)


def test_schema_is_wellformed():
    jsonschema = pytest.importorskip("jsonschema")
    schema = _schema_or_gate()
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema.get("version"), "data-product schema must carry a contract `version`"


def test_full_emit_conforms():
    """The frozen FULL emit (a real CD8A·COADREAD run) must validate — the load-bearing conformance target
    (immune-context has no replay harness). If this ever regresses to a trimmed fixture, fail loudly."""
    schema = _schema_or_gate()
    assert FULL_GOLDEN.exists(), f"missing full-emit conformance fixture {FULL_GOLDEN}"
    decision = json.loads(FULL_GOLDEN.read_text())
    assert is_full_decision(decision), (
        "immune_full_emit.json is not a full decision (envelope + skill_report) — refreeze from a real run.py emit"
    )
    errors = conformance_errors(schema, decision)
    assert not errors, "full emit violates the data-product schema:\n  " + "\n  ".join(
        f"{list(e.path)}: {e.message}" for e in errors[:15]
    )
