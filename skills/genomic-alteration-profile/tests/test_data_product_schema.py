"""Emitted data-product contract guard for genomic-alteration-profile.

Pins the emitted shape against the SELF-CONTAINED generated schema
`target-contracts/schemas/skills/genomic-alteration-profile.decision.schema.json`. Shared helpers in
`_skills_common.data_product_contract`. The static golden is trimmed → static check skips; the
load-bearing conformance is the FRESH replay emit (test_genomic_replay.py).

NOTE: this skill hand-rolls main() (no run_wired_skill); its emitter now builds the envelope-required
run_health + provenance so the fresh emit is a full decision (this file's sibling change).

CI-liveness: schema unresolvable → SKIP locally, FAIL in CI.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import check_schema_wellformed, check_static_golden_conforms

SKILL = "genomic-alteration-profile"
GOLDEN = Path(__file__).resolve().parent / "fixtures" / "kras_coadread_decision.json"


def test_schema_is_wellformed():
    check_schema_wellformed(SKILL)


def test_static_golden_conforms():
    check_static_golden_conforms(SKILL, GOLDEN)
