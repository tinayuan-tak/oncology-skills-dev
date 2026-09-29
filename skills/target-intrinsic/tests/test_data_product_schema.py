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
from pathlib import Path

import pytest
from _skills_common.data_product_contract import is_full_decision  # noqa: E402
from _test_support import check_schema_wellformed, conformance_or_fail, schema_or_gate  # noqa: E402

SKILL = "target-intrinsic"
SKILL_DIR = Path(__file__).resolve().parent.parent
_GOLDENS = sorted((SKILL_DIR / "tests" / "fixtures").glob("*_decision.json"))


def test_schema_is_wellformed():
    check_schema_wellformed(SKILL)


def test_golden_fixture_discovery_is_not_vacuous():
    """Anti-vacuity floor. ``_GOLDENS`` globs ``tests/fixtures/*_decision.json`` at import; the
    conformance test below iterates it and skips when it finds no FULL decision. If the
    glob matches NOTHING (fixtures relocated/renamed), that test skips silently rather than checking
    anything — a vacuous green. Pin the glob to require at least one committed decision fixture (2
    today); this is independent of whether any is a full decision (the load-bearing conformance is the
    replay emit)."""
    assert _GOLDENS, (
        "no *_decision.json fixtures discovered under tests/fixtures/ — the glob broke; "
        "test_static_golden_conforms_if_full would skip vacuously."
    )


def test_static_golden_conforms_if_full():
    """Validate any committed golden that is a FULL decision; a trimmed / pre-skill_report golden is
    skipped (the fresh replay emit is the load-bearing conformance target)."""
    schema = schema_or_gate(SKILL)
    validated = 0
    for g in _GOLDENS:
        decision = json.loads(g.read_text())
        if not is_full_decision(decision):
            continue
        conformance_or_fail(schema, decision, g.name)
        validated += 1
    if validated == 0:
        pytest.skip("no full-decision static golden — see the replay conformance test")
