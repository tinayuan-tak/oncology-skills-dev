"""Emitted data-product contract guard for immune-context.

Pins the emitted shape against the SELF-CONTAINED generated schema
`target-contracts/schemas/skills/immune-context.decision.schema.json`. Shared helpers in
`_skills_common.data_product_contract`.

immune-context has no card-replay harness (its verdict card is indication-level / target-independent), so
the load-bearing conformance target is a FULL emit frozen from a real run —
`fixtures/immune_full_emit.json` (CD8A·COADREAD → immune_intermediate; full envelope +
skill_report). The legacy `kras_coadread_decision.json` is a trimmed evidence-graph fixture and is not a
full-decision target (skipped). CI-liveness: schema unresolvable → SKIP locally, FAIL in CI.

A second full emit, `fixtures/immune_lymphoid_full_emit.json` (MS4A1·DLBC →
lymphoid_denominator_unreliable, frozen live from run.py v1.10.0), exercises the 5th verdict token.
Without it the schema's 4-vs-5 enum drift (#1838) was invisible: the only other fixture never reaches a
lymphoid indication, so the closed-set pin stayed GREEN **while structurally blind** to a token the skill
has emitted since v1.9.0 (2026-09-12). The fixture RED'd against the pre-fix 4-value
`immune_context_verdict` enum on both `headline.immune_context_verdict` and `headline.skill_report.call`,
and only GREENs once target-contracts#975 (`12d16e4`, merged) extends the enum to 5 values.
"""

from __future__ import annotations

import json
from pathlib import Path

from _test_support import check_schema_wellformed, check_static_golden_conforms

SKILL = "immune-context"
FULL_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "immune_full_emit.json"
LYMPHOID_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "immune_lymphoid_full_emit.json"


def test_schema_is_wellformed():
    check_schema_wellformed(SKILL)


def test_full_emit_conforms():
    check_static_golden_conforms(SKILL, FULL_GOLDEN, require_full_emit=True)


def test_lymphoid_emit_conforms():
    """The 5th verdict token, `lymphoid_denominator_unreliable` (skill v1.9.0), fires for lymphoid-lineage
    indications (DLBC/LAML/THYM) whose CIBERSORT leukocyte-fraction denominator is itself the malignant
    clone. Before target-contracts#975 this exact fixture violated the pinned enum on both
    `headline.immune_context_verdict` and `headline.skill_report.call` — which is what makes it evidence
    the guard was BLIND on this path, not merely untested.
    """
    # Bespoke identity assertion, kept per-skill deliberately: `check_static_golden_conforms` validates
    # the fixture against the schema, but a fixture that drifted off the 5th token would still CONFORM
    # (the other four are legal values) and this guard would go quietly vacuous — green while no longer
    # covering the one token it exists for. Assert the token BEFORE delegating.
    decision = json.loads(LYMPHOID_GOLDEN.read_text())
    assert decision["headline"]["immune_context_verdict"] == "lymphoid_denominator_unreliable", (
        "lymphoid fixture drifted off the 5th verdict token it exists to conformance-guard — refreeze "
        "from a real lymphoid run.py emit rather than relaxing this assertion"
    )
    assert decision["headline"]["skill_report"]["call"] == "lymphoid_denominator_unreliable", (
        "the lymphoid fixture's skill_report.call no longer mirrors the verdict — both were enum "
        "violations pre-#975, so both are load-bearing here"
    )
    check_static_golden_conforms(SKILL, LYMPHOID_GOLDEN, require_full_emit=True)
