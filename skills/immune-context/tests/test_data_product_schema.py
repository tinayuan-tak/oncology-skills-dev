"""Emitted data-product contract guard for immune-context.

Pins the emitted shape against the SELF-CONTAINED generated schema
`target-contracts/schemas/skills/immune-context.decision.schema.json`. Shared helpers in
`_skills_common.data_product_contract`.

immune-context has no card-replay harness (its verdict card is indication-level / target-independent), so
the load-bearing conformance target is a FULL emit frozen from a real run —
`fixtures/immune_full_emit.json` (CD8A·COADREAD → immune_intermediate; full envelope +
skill_report). The legacy `kras_coadread_decision.json` is a trimmed evidence-graph fixture and is not a
full-decision target (skipped). CI-liveness: schema unresolvable → SKIP locally, FAIL in CI.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import check_schema_wellformed, check_static_golden_conforms

SKILL = "immune-context"
FULL_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "immune_full_emit.json"


def test_schema_is_wellformed():
    check_schema_wellformed(SKILL)


def test_full_emit_conforms():
    check_static_golden_conforms(SKILL, FULL_GOLDEN, require_full_emit=True)
