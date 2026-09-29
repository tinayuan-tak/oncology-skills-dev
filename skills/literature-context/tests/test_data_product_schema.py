"""Emitted data-product contract guard for literature-context (15th target-profile fan-out member).

Pins the emitted shape against the SELF-CONTAINED generated schema
`target-contracts/schemas/skills/literature-context.decision.schema.json`. Shared helpers in
`_skills_common.data_product_contract`. Gateless-descriptive (verdict_fn=None → skill_report.call null).
No replay harness → the load-bearing conformance target is a FROZEN FULL emit
`fixtures/literature_context_full_emit.json` (a real KRAS·COADREAD run). CI-liveness: schema unresolvable
→ SKIP locally, FAIL in CI.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import check_schema_wellformed, check_static_golden_conforms

SKILL = "literature-context"
FULL_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "literature_context_full_emit.json"


def test_schema_is_wellformed():
    check_schema_wellformed(SKILL)


def test_full_emit_conforms():
    check_static_golden_conforms(SKILL, FULL_GOLDEN, require_full_emit=True)
