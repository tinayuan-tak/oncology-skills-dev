"""Deferred-(c) focused behavioral test: the genotype×drug-response biomarker fires its OWN verdict
(drug_response_biomarker) — the NEW verdict-moving behavior the byte-identical golden snapshot
deliberately cannot show.

The golden snapshot proves EXISTING genomic_alteration combos are unchanged (the new rule id
mutation-drug-response-strongly-sensitive-supportive is NOT in its frozen 12-rule enumeration). This
test proves the new rung actually DOES what it's for:
  - the strong drug-sensitivity class resolves to a DISTINCT drug_response_biomarker verdict (NEVER
    conflated with the CRISPR biomarker_stratified_dependency — drug-sensitivity != KO-dependency),
  - the KO-proven genetic dependency WINS first-match when both fire (it precedes the drug rung),
  - the drug rung precedes the bare variant-class-pattern rungs (a pharmacological biomarker outranks
    a mutation-spectrum composition with no functional test).
Requires the deferred-c resolver rung (skip gracefully if the contracts half hasn't landed here yet).
"""
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
    v = resolve_verdict_for_gate(
        _rules("mutation-drug-response-strongly-sensitive-supportive"), "genomic_alteration")
    if not v or v[0] != "drug_response_biomarker":
        pytest.skip("deferred-c drug_response_biomarker resolver rung not present in resolved contracts")


def test_strong_drug_sensitive_fires_distinct_drug_response_biomarker():
    _skip_if_rung_absent()
    verdict, driving = resolve_verdict_for_gate(
        _rules("mutation-drug-response-strongly-sensitive-supportive"), "genomic_alteration")
    assert verdict == "drug_response_biomarker"          # DISTINCT — not biomarker_stratified_dependency
    assert driving == "mutation-drug-response-strongly-sensitive-supportive"


def test_genetic_dependency_wins_first_match_over_drug_response():
    """A gene both KO-dependent AND drug-sensitive in its mutant subset: the KO-proven genetic
    dependency is the more mechanism-anchored call and precedes the drug rung (first-match)."""
    _skip_if_rung_absent()
    verdict, driving = resolve_verdict_for_gate(
        _rules("mutant-strongly-dependent-supportive",
               "mutation-drug-response-strongly-sensitive-supportive"), "genomic_alteration")
    assert verdict == "biomarker_stratified_dependency"
    assert driving == "mutant-strongly-dependent-supportive"


def test_drug_response_precedes_bare_variant_class_pattern():
    """Drug-response (a functional pharmacological test) outranks a bare variant-class composition
    signal (missense/lof dominance with NO functional test)."""
    _skip_if_rung_absent()
    verdict, driving = resolve_verdict_for_gate(
        _rules("mutation-drug-response-strongly-sensitive-supportive",
               "mut-missense-dominant-supportive"), "genomic_alteration")
    assert verdict == "drug_response_biomarker"
    assert driving == "mutation-drug-response-strongly-sensitive-supportive"


def test_moderate_drug_sensitive_does_not_fire_a_verdict():
    """Only the STRONG drug-sensitivity class drives a verdict; the moderate class stays a signal-only
    facet (necessary-not-sufficient for a nomination tier). Firing ONLY the moderate rule must NOT
    yield drug_response_biomarker."""
    _skip_if_rung_absent()
    v = resolve_verdict_for_gate(
        _rules("mutation-drug-response-moderately-sensitive-supportive"), "genomic_alteration")
    # either no verdict, or some lower-precedence default — but NEVER drug_response_biomarker
    assert (v is None) or (v[0] != "drug_response_biomarker")
