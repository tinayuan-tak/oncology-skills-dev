"""INV-6 for prose — narrative->claim-ID grounding + polarity/strength non-exceedance.

Pins the two teeth the #1609 deliverable requires: the guard MUST fail (a) when a material statement's
polarity/strength EXCEEDS its cited claim, and (b) when a material statement cites nothing. Plus the
grounded case (no findings) and the immaterial-statement exemption, so the guard cannot go vacuous.
"""

from __future__ import annotations

import sys
from pathlib import Path

COMMON_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMMON_DIR.parent))  # skills/

from _skills_common.narrative_grounding import (  # noqa: E402
    POLARITY_EXCEEDS,
    STRENGTH_EXCEEDS,
    UNCITED,
    UNKNOWN_CLAIM,
    check_grounding,
    is_material,
)

# The motivating registry: a claim whose signal is WEAK and corroboration is a single unopposed arm.
CLAIMS = {
    "presence.A": {"signal": "weak", "corroboration": "single_arm"},
    "presence.B": {"signal": "moderate", "corroboration": "moderate"},
    "concordance.mixed": {"signal": "unmeasured", "corroboration": "low"},  # off-scale signal (a gap)
}


def test_material_statement_that_cites_nothing_fails():
    """(b) A material statement (asserts a polarity) with an empty supported_by is UNCITED."""
    stmts = [{"text": "the target is broadly expressed", "polarity": "moderate", "supported_by": []}]
    findings = check_grounding(stmts, CLAIMS)
    assert [f["kind"] for f in findings] == [UNCITED]


def test_polarity_exceedance_fails():
    """(a) Prose asserting a STRONGER polarity than its cited claim supports is caught. The motivating
    case: cite `concordance.mixed` (off-scale signal) then write "strongly supports"."""
    stmts = [
        {
            "text": "overall, evidence strongly supports broad expression",
            "polarity": "strong",
            "supported_by": ["concordance.mixed"],
        }
    ]
    findings = check_grounding(stmts, CLAIMS)
    assert any(f["kind"] == POLARITY_EXCEEDS for f in findings)

    # Also over a MEASURED but weaker claim: "strong" over a "weak" claim exceeds.
    stmts2 = [{"text": "strong dependency", "polarity": "strong", "supported_by": ["presence.A"]}]
    assert any(f["kind"] == POLARITY_EXCEEDS for f in check_grounding(stmts2, CLAIMS))


def test_strength_exceedance_fails():
    """(a) Prose asserting a STRONGER corroboration than its cited claim supports is caught: claim rests
    on a single arm, prose reads "highly corroborated across channels"."""
    stmts = [
        {
            "text": "highly corroborated across independent channels",
            "strength": "high",
            "supported_by": ["presence.A"],  # single_arm
        }
    ]
    findings = check_grounding(stmts, CLAIMS)
    assert any(f["kind"] == STRENGTH_EXCEEDS for f in findings)


def test_grounded_non_exceeding_statement_passes():
    """A material statement whose asserted polarity/strength does NOT exceed the peak cited claim is
    clean — the guard is not merely always-red."""
    stmts = [
        {
            "text": "moderate support, moderately corroborated",
            "polarity": "moderate",
            "strength": "moderate",
            "supported_by": ["presence.B"],
        },
        # non-exceedance is <=, and peak is across the SET of cited claims (the most-favorable one).
        {
            "text": "weak but real",
            "polarity": "weak",
            "strength": "single_arm",
            "supported_by": ["presence.A", "presence.B"],
        },
    ]
    assert check_grounding(stmts, CLAIMS) == []


def test_immaterial_statement_is_exempt():
    """A statement asserting neither polarity nor strength (framing / a stated gap) needs no citation."""
    stmts = [{"text": "this axis was not measured in the available cohorts"}]
    assert not is_material(stmts[0])
    assert check_grounding(stmts, CLAIMS) == []


def test_unknown_claim_id_is_flagged():
    """A citation naming a claim absent from the registry is surfaced — grounding must resolve."""
    stmts = [{"text": "supported", "polarity": "moderate", "supported_by": ["does.not.exist"]}]
    findings = check_grounding(stmts, CLAIMS)
    assert [f["kind"] for f in findings] == [UNKNOWN_CLAIM]
