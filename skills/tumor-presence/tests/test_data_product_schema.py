"""Emitted data-product contract guard for tumor-presence.

The finalized data product is defined by skills/tumor-presence/DATA_PRODUCT.md; its EMITTED shape is
pinned by the SELF-CONTAINED, generated per-skill schema
`target-contracts/schemas/skills/tumor-presence.decision.schema.json` (embeds the shared spine +
envelope — no cross-file $ref, so validation needs no registry). Shared load/validate helpers live in
`_skills_common.data_product_contract`.

Two conformance targets:
  - the frozen static golden (this file), validated only when it is a FULL decision (some skills keep a
    trimmed golden — not a valid full-decision target); and
  - the FRESH replay emit (test_tumor_presence_replay.py::test_replay_conforms_to_data_product_schema),
    which runs the real run.py credential-less — the load-bearing check for LIVE emitted-shape drift.

CI-liveness: when the schema is unresolvable, this SKIPS locally but FAILS in CI (env CI set), so the
ratchet can never be a silent green no-op. The contracts schema PR must land before skills CI can
resolve the schema — that ordering is intentional.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

SKILL = "tumor-presence"
SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
GOLDEN = SKILL_DIR / "tests" / "fixtures" / "epcam_coadread_decision.json"

if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))
from _skills_common.data_product_contract import (  # noqa: E402
    conformance_errors,
    is_full_decision,
    load_schema,
    schema_path,
)


def _schema_or_gate() -> dict:
    """Load the schema; in CI its absence is a FAILURE (never a silent skip)."""
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


def test_static_golden_conforms():
    """Validate the static golden when it is a FULL decision; a trimmed golden is skipped (the fresh
    replay emit is the load-bearing conformance target)."""
    pytest.importorskip("jsonschema")
    schema = _schema_or_gate()
    decision = json.loads(GOLDEN.read_text())
    if not is_full_decision(decision):
        pytest.skip("golden is a trimmed fixture (not a full decision) — see the replay conformance test")
    errors = conformance_errors(schema, decision)
    assert not errors, "static golden violates the data-product schema:\n  " + "\n  ".join(
        f"{list(e.path)}: {e.message}" for e in errors[:15]
    )
