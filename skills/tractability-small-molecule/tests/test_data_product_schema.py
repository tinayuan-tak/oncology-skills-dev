"""Emitted data-product contract guard for tractability-small-molecule.

Pins the emitted shape against the SELF-CONTAINED generated schema
`target-contracts/schemas/skills/tractability-small-molecule.decision.schema.json`. Shared helpers in
`_skills_common.data_product_contract`. A trimmed golden skips the static check; the load-bearing
conformance is the FRESH replay emit (test_tractability_sm_replay.py). CI-liveness: schema unresolvable
→ SKIP locally, FAIL in CI.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import check_schema_wellformed, check_static_golden_conforms

SKILL = "tractability-small-molecule"
GOLDEN = Path(__file__).resolve().parent / "fixtures" / "egfr_coadread_decision.json"


def test_schema_is_wellformed():
    check_schema_wellformed(SKILL)


def test_static_golden_conforms():
    check_static_golden_conforms(SKILL, GOLDEN)
