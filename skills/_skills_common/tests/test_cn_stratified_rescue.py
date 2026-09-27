"""A1a focused behavioral test: the copy-number-stratified-dependency rescue fires (the NEW
behavior the byte-identical golden snapshot deliberately cannot show).

The golden snapshot proves EXISTING genomic_alteration combos are unchanged (the 2 new rule ids
aren't in its frozen enumeration). This test proves the new rungs actually DO what they're for:
a cn-amplified-*-dependent rule resolves to the SAME biomarker_stratified_dependency verdict the
mutation path uses, with a distinct driving_rule_id (auditability), and mutation wins first-match
when both fire. Requires the A1a-2 resolver (point TARGET_CONTRACTS_ROOT at it if not on main)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

COMMON = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMMON.parent))  # skills/

from _skills_common.resolver import resolve_verdict_for_gate  # noqa: E402


def _rules(*ids):
    return [{"rule_id": i} for i in ids]


def _skip_if_rung_absent():
    """Skip gracefully ONLY if the A1a-2 resolver rungs aren't present in the resolved contracts
    (e.g. running against a target-contracts checkout without #197) — this test asserts the
    NEW behavior, so a genuinely absent rung means the contract half hasn't landed here yet.

    The probe fires the rung WITH its required ``cn-amplified-indication-scoped-context`` gate:
    scope-coherence Phase 1 made ``biomarker_stratified_dependency`` require that co-fire
    (resolver priority 5), so an ISOLATED fire now resolves to ``insufficient`` (the resolver
    ``default:``) even when the rung is fully present. Probing in isolation would conflate
    "rung absent from contract" with "rung present but my probe is stale" and SKIP the whole
    suite blind — the fail-open this suite exists to prevent."""
    v = resolve_verdict_for_gate(
        _rules("cn-amplified-strongly-dependent-supportive", "cn-amplified-indication-scoped-context"),
        "genomic_alteration",
    )
    if not v or v[0] != "biomarker_stratified_dependency":
        pytest.skip("A1a-2 CN-stratified resolver rung not present in resolved contracts")


def test_cn_strong_fires_biomarker_stratified_dependency():
    _skip_if_rung_absent()
    # scope-coherence Phase 1: the biomarker rung requires the indication-scope gate co-fire
    # (cn-amplified-indication-scoped-context, resolver priority 5).
    verdict, driving = resolve_verdict_for_gate(
        _rules("cn-amplified-strongly-dependent-supportive", "cn-amplified-indication-scoped-context"),
        "genomic_alteration",
    )
    assert verdict == "biomarker_stratified_dependency"
    # distinct driving_rule preserves auditability (NOT the mutation rule)
    assert driving == "cn-amplified-strongly-dependent-supportive"


def test_cn_moderate_fires_moderate_biomarker_dependency():
    _skip_if_rung_absent()
    verdict, driving = resolve_verdict_for_gate(
        _rules("cn-amplified-moderately-dependent-supportive", "cn-amplified-indication-scoped-context"),
        "genomic_alteration",
    )
    assert verdict == "moderate_biomarker_dependency"
    assert driving == "cn-amplified-moderately-dependent-supportive"


def test_mutation_wins_first_match_when_both_fire():
    """KRAS-like amp+mut: same verdict, but driving_rule must name the MUTATION path (precedence)."""
    _skip_if_rung_absent()
    verdict, driving = resolve_verdict_for_gate(
        _rules(
            "mutant-strongly-dependent-supportive",
            "mutant-indication-scoped-context",
            "cn-amplified-strongly-dependent-supportive",
            "cn-amplified-indication-scoped-context",
        ),
        "genomic_alteration",
    )
    assert verdict == "biomarker_stratified_dependency"
    assert driving == "mutant-strongly-dependent-supportive"  # mutation rung precedes CN (section 2 before 2b)
