"""Emitted data-product contract guard for cis-feature-coherence.

Pins the emitted shape against the SELF-CONTAINED generated schema
`target-contracts/schemas/skills/cis-feature-coherence.decision.schema.json`. Shared helpers in
`_skills_common.data_product_contract`.

INERT skill (role=inert): skill_report.call carries the verdict-SHAPED-but-not-a-call cis_coherence_verdict
string. No replay harness, so the load-bearing conformance target is a FROZEN FULL emit
`fixtures/cis_full_emit.json` (a real KRAS·COADREAD run → coherent_cis_driver). CI-liveness:
schema unresolvable → SKIP locally, FAIL in CI.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import check_schema_wellformed, check_static_golden_conforms

SKILL = "cis-feature-coherence"
FULL_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "cis_full_emit.json"


def test_schema_is_wellformed():
    check_schema_wellformed(SKILL)


def test_full_emit_conforms():
    check_static_golden_conforms(SKILL, FULL_GOLDEN, require_full_emit=True)
