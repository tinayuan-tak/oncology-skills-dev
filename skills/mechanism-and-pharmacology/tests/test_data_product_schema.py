"""Emitted data-product contract guard for mechanism-and-pharmacology.

Pins the emitted shape against the SELF-CONTAINED generated schema
`target-contracts/schemas/skills/mechanism-and-pharmacology.decision.schema.json`. Shared helpers in
`_skills_common.data_product_contract`. The static golden is trimmed → static check skips; the
load-bearing conformance is the FRESH replay emit (test_mechanism_replay.py).

CI-liveness: schema unresolvable → SKIP locally, FAIL in CI.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import check_schema_wellformed, check_static_golden_conforms

SKILL = "mechanism-and-pharmacology"
GOLDEN = Path(__file__).resolve().parent / "fixtures" / "kras_coadread_decision.json"


def test_schema_is_wellformed():
    check_schema_wellformed(SKILL)


def test_static_golden_conforms():
    check_static_golden_conforms(SKILL, GOLDEN)
