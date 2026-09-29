"""Emitted data-product contract guard for on-target-safety-liability.

Pins the emitted shape against the SELF-CONTAINED generated schema
`target-contracts/schemas/skills/on-target-safety-liability.decision.schema.json`. Shared helpers in
`_skills_common.data_product_contract`. A trimmed golden skips the static check; the load-bearing
conformance is the FRESH replay emit (test_safety_replay.py). CI-liveness: schema unresolvable → SKIP
locally, FAIL in CI.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import check_schema_wellformed, check_static_golden_conforms

SKILL = "on-target-safety-liability"
GOLDEN = Path(__file__).resolve().parent / "fixtures" / "braf_coadread_decision.json"


def test_schema_is_wellformed():
    check_schema_wellformed(SKILL)


def test_static_golden_conforms():
    check_static_golden_conforms(SKILL, GOLDEN)
