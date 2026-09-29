"""Emitted data-product contract guard for tumor-selectivity.

Pins the emitted shape against the SELF-CONTAINED, generated per-skill schema
`target-contracts/schemas/skills/tumor-selectivity.decision.schema.json`. Shared load/validate helpers
live in `_skills_common.data_product_contract`.

The static `kras_coadread_decision.json` golden is a TRIMMED fixture (no envelope/skill_report), so the
static-golden check is skipped for it; the load-bearing conformance is the FRESH replay emit
(test_selectivity_replay.py::test_replay_conforms_to_data_product_schema).

CI-liveness: when the schema is unresolvable, this SKIPS locally but FAILS in CI (env CI set).
"""

from __future__ import annotations

from pathlib import Path

from _test_support import check_schema_wellformed, check_static_golden_conforms

SKILL = "tumor-selectivity"
GOLDEN = Path(__file__).resolve().parent / "fixtures" / "kras_coadread_decision.json"


def test_schema_is_wellformed():
    check_schema_wellformed(SKILL)


def test_static_golden_conforms():
    check_static_golden_conforms(SKILL, GOLDEN)
