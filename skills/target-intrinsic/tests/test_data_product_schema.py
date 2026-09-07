"""Emitted data-product contract guard for target-intrinsic.

Pins the emitted shape against the SELF-CONTAINED generated schema
`target-contracts/schemas/skills/target-intrinsic.decision.schema.json`. Shared helpers in
`_skills_common.data_product_contract`.

Gateless descriptive dossier (verdict_fn=None → skill_report.call is null; indication-independent →
indication emits the "PANCANCER" sentinel standalone). The load-bearing conformance is the FRESH replay
emit (test_target_intrinsic_replay.py::test_replay_conforms_to_data_product_schema); the committed
kras/egfr static golden predates skill_report and is a trimmed fixture (skipped here). CI-liveness: schema
unresolvable → SKIP locally, FAIL in CI.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

SKILL = "target-intrinsic"
SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent

if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))
from _skills_common.data_product_contract import (  # noqa: E402
    conformance_errors,
    is_full_decision,
    load_schema,
    schema_path,
)

_GOLDENS = sorted((SKILL_DIR / "tests" / "fixtures").glob("*_decision.json"))


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


def test_static_golden_conforms_if_full():
    """Validate any committed golden that is a FULL decision; a trimmed / pre-skill_report golden is
    skipped (the fresh replay emit is the load-bearing conformance target)."""
    schema = _schema_or_gate()
    validated = 0
    for g in _GOLDENS:
        decision = json.loads(g.read_text())
        if not is_full_decision(decision):
            continue
        errors = conformance_errors(schema, decision)
        assert not errors, f"{g.name} violates the data-product schema:\n  " + "\n  ".join(
            f"{list(e.path)}: {e.message}" for e in errors[:15]
        )
        validated += 1
    if validated == 0:
        pytest.skip("no full-decision static golden — see the replay conformance test")
