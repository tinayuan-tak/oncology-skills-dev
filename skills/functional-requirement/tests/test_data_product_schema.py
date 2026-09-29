"""Emitted data-product contract guard for functional-requirement.

Pins the emitted shape against the SELF-CONTAINED generated per-skill schema
`target-contracts/schemas/skills/functional-requirement.decision.schema.json`. Shared load/validate
helpers live in `_skills_common.data_product_contract`. The static golden is trimmed, so the
static-golden check skips it; the load-bearing conformance is the FRESH replay emit
(test_functional_requirement_replay.py::test_replay_conforms_to_data_product_schema).

CI-liveness: schema unresolvable → SKIP locally, FAIL in CI (env CI set).
"""

from __future__ import annotations

from pathlib import Path

from _test_support import check_schema_wellformed, check_static_golden_conforms

SKILL = "functional-requirement"
GOLDEN = Path(__file__).resolve().parent / "fixtures" / "kras_coadread_decision.json"


def test_schema_is_wellformed():
    check_schema_wellformed(SKILL)


def test_static_golden_conforms():
    check_static_golden_conforms(SKILL, GOLDEN)
