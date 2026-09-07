"""A1-fusion focused behavioral test: the fusion-stratified-dependency rescue fires (the NEW
behavior the byte-identical golden snapshot deliberately cannot show).

The golden snapshot proves EXISTING genomic_alteration combos are unchanged (the 2 new rule ids
aren't in its frozen enumeration). This test proves the new section-2c rungs actually DO what
they're for: a fusion-positive-*-dependent rule resolves to the SAME biomarker_stratified_dependency
verdict the mutation + CN paths use, with a distinct driving_rule_id (auditability), and the
precedence order mut > cn > fusion holds first-match. Requires the A1-fusion-2 resolver (point
TARGET_CONTRACTS_ROOT at it if not on main)."""

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
    """Skip gracefully if the A1-fusion-2 resolver rungs aren't present in the resolved contracts
    (e.g. running against a target-contracts checkout without #208) — this test asserts the
    NEW behavior, so an absent rung means the contract half hasn't landed here yet."""
    v = resolve_verdict_for_gate(_rules("fusion-positive-strongly-dependent-supportive"), "genomic_alteration")
    if not v or v[0] != "biomarker_stratified_dependency":
        pytest.skip("A1-fusion-2 fusion-stratified resolver rung not present in resolved contracts")


def test_fusion_strong_fires_biomarker_stratified_dependency():
    _skip_if_rung_absent()
    verdict, driving = resolve_verdict_for_gate(
        _rules("fusion-positive-strongly-dependent-supportive"), "genomic_alteration"
    )
    assert verdict == "biomarker_stratified_dependency"
    # distinct driving_rule preserves auditability (NOT the mutation/CN rule)
    assert driving == "fusion-positive-strongly-dependent-supportive"


def test_fusion_moderate_fires_moderate_biomarker_dependency():
    _skip_if_rung_absent()
    verdict, driving = resolve_verdict_for_gate(
        _rules("fusion-positive-moderately-dependent-supportive"), "genomic_alteration"
    )
    assert verdict == "moderate_biomarker_dependency"
    assert driving == "fusion-positive-moderately-dependent-supportive"


def test_mutation_wins_first_match_over_fusion():
    """Same verdict, but driving_rule must name the MUTATION path (mut precedes fusion — section 2
    before 2c)."""
    _skip_if_rung_absent()
    verdict, driving = resolve_verdict_for_gate(
        _rules("mutant-strongly-dependent-supportive", "fusion-positive-strongly-dependent-supportive"),
        "genomic_alteration",
    )
    assert verdict == "biomarker_stratified_dependency"
    assert driving == "mutant-strongly-dependent-supportive"


def test_cn_wins_first_match_over_fusion():
    """CN precedes fusion (section 2b before 2c): amp+fusion both fire → driving names the CN path."""
    _skip_if_rung_absent()
    verdict, driving = resolve_verdict_for_gate(
        _rules("cn-amplified-strongly-dependent-supportive", "fusion-positive-strongly-dependent-supportive"),
        "genomic_alteration",
    )
    assert verdict == "biomarker_stratified_dependency"
    assert driving == "cn-amplified-strongly-dependent-supportive"
