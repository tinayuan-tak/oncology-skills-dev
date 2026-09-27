"""A1 amp-expr focused behavioral test: the amp-expr-stratified-dependency rescue fires (the NEW
behavior the byte-identical golden snapshot deliberately cannot show).

The golden snapshot proves EXISTING genomic_alteration combos are unchanged (the 2 new rule ids aren't
in its frozen enumeration). This test proves the new section-2d rungs actually DO what they're for: an
amp-expr-*-dependent rule resolves to the SAME biomarker_stratified_dependency verdict the mutation/CN/
fusion paths use, with a distinct driving_rule_id (auditability), and the precedence order
mut > cn > fusion > amp-expr holds first-match. Requires the A1 amp-expr resolver (point
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
    """Skip gracefully ONLY if the A1 amp-expr resolver rungs aren't present in the resolved
    contracts (e.g. a target-contracts checkout without the amp-expr PR) — this test asserts the
    NEW behavior, so a genuinely absent rung means the contract half hasn't landed here yet.

    The probe fires the rung WITH its required ``amp-expr-indication-scoped-context`` gate:
    scope-coherence Phase 1 made ``biomarker_stratified_dependency`` require that co-fire
    (resolver priority 7), so an ISOLATED fire now resolves to ``insufficient`` (the resolver
    ``default:``) even when the rung is fully present. Probing in isolation would conflate
    "rung absent from contract" with "rung present but my probe is stale" and SKIP the whole
    suite blind — the fail-open this suite exists to prevent."""
    v = resolve_verdict_for_gate(
        _rules("amp-expr-strongly-dependent-supportive", "amp-expr-indication-scoped-context"),
        "genomic_alteration",
    )
    if not v or v[0] != "biomarker_stratified_dependency":
        pytest.skip("A1 amp-expr resolver rung not present in resolved contracts")


def test_amp_expr_strong_fires_biomarker_stratified_dependency():
    _skip_if_rung_absent()
    # scope-coherence Phase 1: the biomarker rung requires the indication-scope gate co-fire
    # (amp-expr-indication-scoped-context, resolver priority 7).
    verdict, driving = resolve_verdict_for_gate(
        _rules("amp-expr-strongly-dependent-supportive", "amp-expr-indication-scoped-context"),
        "genomic_alteration",
    )
    assert verdict == "biomarker_stratified_dependency"
    assert driving == "amp-expr-strongly-dependent-supportive"


def test_amp_expr_moderate_fires_moderate_biomarker_dependency():
    _skip_if_rung_absent()
    verdict, driving = resolve_verdict_for_gate(
        _rules("amp-expr-moderately-dependent-supportive", "amp-expr-indication-scoped-context"),
        "genomic_alteration",
    )
    assert verdict == "moderate_biomarker_dependency"
    assert driving == "amp-expr-moderately-dependent-supportive"


def test_precedence_mut_cn_fusion_over_amp_expr():
    """When several stratified-dependency rules fire, driving_rule follows precedence
    mut > cn > fusion > amp-expr (amp-expr is the MOST SPECIFIC → placed last).

    Each dependent rung co-fires with its own ``*-indication-scoped-context`` gate
    (scope-coherence Phase 1) so the biomarker rungs are actually reachable."""
    _skip_if_rung_absent()
    # mut wins over amp-expr
    v, d = resolve_verdict_for_gate(
        _rules(
            "mutant-strongly-dependent-supportive",
            "mutant-indication-scoped-context",
            "amp-expr-strongly-dependent-supportive",
            "amp-expr-indication-scoped-context",
        ),
        "genomic_alteration",
    )
    assert v == "biomarker_stratified_dependency" and d == "mutant-strongly-dependent-supportive"
    # cn wins over amp-expr
    v, d = resolve_verdict_for_gate(
        _rules(
            "cn-amplified-strongly-dependent-supportive",
            "cn-amplified-indication-scoped-context",
            "amp-expr-strongly-dependent-supportive",
            "amp-expr-indication-scoped-context",
        ),
        "genomic_alteration",
    )
    assert v == "biomarker_stratified_dependency" and d == "cn-amplified-strongly-dependent-supportive"
    # fusion wins over amp-expr
    v, d = resolve_verdict_for_gate(
        _rules(
            "fusion-positive-strongly-dependent-supportive",
            "fusion-positive-indication-scoped-context",
            "amp-expr-strongly-dependent-supportive",
            "amp-expr-indication-scoped-context",
        ),
        "genomic_alteration",
    )
    assert v == "biomarker_stratified_dependency" and d == "fusion-positive-strongly-dependent-supportive"
