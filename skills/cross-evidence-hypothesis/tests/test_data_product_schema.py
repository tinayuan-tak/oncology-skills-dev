"""Emitted data-product contract guard for cross-evidence-hypothesis (AUX, BESPOKE — LLM cross-skill
synthesis; NOT a target-profile fan-out member).

This skill's output is a bespoke `hypothesis.json` (a gated therapeutic hypothesis), NOT the fan-out
`skill_decision` envelope — there is no `run_health`, no `headline.skill_report`. So its emitted-output
contract is a HAND-AUTHORED schema (`.emit.` suffix, not the generated `.decision.`):
`target-contracts/schemas/skills/cross-evidence-hypothesis.emit.schema.json`. It pins the stable
top-level identity + the gated verdict OBJECT vocabulary (VERDICT_RANK; computed = min(proposed,
ceiling)) + evidence-grade / modality / edge-type enums + provenance presence, and leaves the
LLM-authored clause prose OPEN (prompt-hash nondeterministic).

Conformance target = the FRESH deterministic emit from the offline golden llm-replay harness: the real
run.py over the frozen KRAS-COADREAD evidence package, driven by the canned two-call `llm_replay.json`
via `run.replay_synthesize` (llm_mode="offline_replay") — exactly as tests/test_drift_guard.py does, so
NO Bedrock / NO S3 / NO credentials, yet the validated dict is exactly what a live run emits.
CI-liveness: schema unresolvable → SKIP locally, FAIL in CI.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from _test_support import load_run_py  # skills/ is on sys.path via skills/conftest.py

SKILL = "cross-evidence-hypothesis"
SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_DIR / "scripts"
GOLDEN = SKILL_DIR / "tests" / "fixtures" / "golden" / "KRAS-COADREAD"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import drift_golden as dg  # noqa: E402
from _skills_common.data_product_contract import (  # noqa: E402
    conformance_errors,
    load_schema,
    schema_path,
)


def _schema_or_gate() -> dict:
    """The self-contained hand-authored emit schema, or gate: SKIP locally / FAIL in CI when the
    contracts repo is not resolvable (the ratchet must be live in CI, never a vacuous skip)."""
    schema = load_schema(SKILL, "emit")
    if schema is not None:
        return schema
    reason = (
        f"data-product emit schema not found at {schema_path(SKILL, 'emit')} — set "
        f"TARGET_CONTRACTS_ROOT / land the contracts schema PR first"
    )
    if os.environ.get("CI"):
        pytest.fail(reason + " [CI: the data-product ratchet must be live, not skipped]")
    pytest.skip(reason)


def _fresh_emit() -> dict:
    """The FRESH deterministic emit: replay the frozen canned two-call LLM response through the real
    run.py deterministic spine for KRAS-COADREAD — no Bedrock (mirrors test_drift_guard._run_offline)."""
    if not (GOLDEN / "expected_spine.json").exists():
        pytest.skip(f"no frozen golden case at {GOLDEN} — run freeze_drift_golden.py")
    R = load_run_py(SKILL_DIR, "ce_run_data_product")
    case = dg.load_golden_case(GOLDEN)
    return R.run(
        case["pkg"],
        case["risk"],
        case["meta"]["objective"],
        case["meta"]["modality"],
        case["dossier"],
        synthesize_fn=R.replay_synthesize(case["replay"]),
        llm_mode="offline_replay",
    )


def test_schema_is_wellformed():
    """The hand-authored emit schema is itself a valid Draft 2020-12 schema and carries a contract
    `version` (append-only within major)."""
    jsonschema = pytest.importorskip("jsonschema")
    schema = _schema_or_gate()
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema.get("version"), "data-product emit schema must carry a contract `version`"


def test_fresh_emit_conforms():
    """The fresh deterministic replay emit must validate against the emit schema — the load-bearing
    conformance target. Asserts the BESPOKE identity inline (NOT the fan-out full-decision envelope):
    top-level `skill` const + the gated verdict is an OBJECT (not a scalar)."""
    pytest.importorskip("jsonschema")
    schema = _schema_or_gate()
    decision = _fresh_emit()
    # bespoke identity (this skill has no headline.skill_report / run_health — do NOT use is_full_decision)
    assert decision["skill"] == SKILL, f"emit skill identity regressed: {decision.get('skill')!r}"
    assert isinstance(decision["verdict"], dict), (
        "verdict must be the gated OBJECT (proposed_by_agent / computed / gate_ceiling), not a scalar"
    )
    errors = conformance_errors(schema, decision)
    assert not errors, "fresh emit violates the data-product emit schema:\n  " + "\n  ".join(
        f"{list(e.path)}: {e.message}" for e in errors[:15]
    )
