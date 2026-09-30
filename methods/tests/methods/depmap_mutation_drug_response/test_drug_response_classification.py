"""Pure classification-direction logic for the genotype × PRISM drug-response biomarker.

NO scipy / numpy: this file exercises ``classify_drug_response`` directly on synthetic
(delta, q, q_reverse, insufficient) tuples. The Mann-Whitney kernel that PRODUCES those numbers
needs scipy, but the boundary logic that turns them into a verdict class does not — and it used to
sit behind a module-level ``pytest.importorskip("scipy")`` in the sibling stratification test, so
every direction assertion was silently skipped whenever scipy was absent (green-for-the-wrong-
reason). Keeping these scipy-free means the verdict boundaries stay under test on a scipy-less runner.

Lower Log2AUC = more drug-sensitive; delta = mutant median minus WT median, so a NEGATIVE delta is
mutant-more-sensitive (forward) and a POSITIVE delta is mutant-more-resistant (reverse).
"""

from __future__ import annotations

from onc_methods.depmap_mutation_drug_response.cli import (
    MODERATE_EFFECT_DELTA,
    STRATIFICATION_ALPHA,
    STRONG_EFFECT_DELTA,
    classify_drug_response,
)


def test_insufficient_data_short_circuits_before_any_threshold():
    # insufficient wins even with a would-be-significant strong forward signal present.
    assert (
        classify_drug_response(delta=-0.9, q=1e-6, q_reverse=None, insufficient=True)
        == "insufficient_mutant_or_drug_data"
    )


def test_none_delta_is_not_stratified():
    assert (
        classify_drug_response(delta=None, q=None, q_reverse=None, insufficient=False) == "not_drug_response_stratified"
    )


def test_strong_forward_sensitive():
    assert (
        classify_drug_response(delta=-0.30, q=1e-4, q_reverse=0.9, insufficient=False)
        == "mutant_strongly_drug_sensitive"
    )


def test_moderate_forward_sensitive():
    assert (
        classify_drug_response(delta=-0.12, q=1e-3, q_reverse=0.9, insufficient=False)
        == "mutant_moderately_drug_sensitive"
    )


def test_significant_but_sub_moderate_effect_is_not_stratified():
    # q passes but |delta| below the moderate floor → no sensitivity class, and delta<0 blocks reverse.
    assert (
        classify_drug_response(delta=-0.04, q=1e-3, q_reverse=0.9, insufficient=False) == "not_drug_response_stratified"
    )


def test_forward_effect_without_significance_is_not_stratified():
    # a strong negative delta but non-significant forward q → not stratified (not a sensitivity call).
    assert (
        classify_drug_response(delta=-0.50, q=0.20, q_reverse=0.9, insufficient=False) == "not_drug_response_stratified"
    )


def test_reverse_resistant_requires_significance_and_positive_delta():
    assert classify_drug_response(delta=0.30, q=0.9, q_reverse=1e-4, insufficient=False) == "mutant_drug_resistant"


def test_reverse_not_called_when_reverse_q_nonsignificant():
    assert (
        classify_drug_response(delta=0.30, q=0.9, q_reverse=0.20, insufficient=False) == "not_drug_response_stratified"
    )


def test_reverse_not_called_when_delta_negative_even_if_reverse_q_significant():
    # reverse needs delta >= +strong (mutant genuinely more resistant); a negative delta must not
    # be labelled resistant just because the reverse test happens to trip.
    assert (
        classify_drug_response(delta=-0.30, q=0.9, q_reverse=1e-4, insufficient=False) == "not_drug_response_stratified"
    )


def test_forward_beats_reverse_when_both_significant():
    # a negative delta with a significant forward q classifies as sensitive; the reverse branch is
    # only reached for positive deltas, so there is no contradiction, but pin the precedence anyway.
    assert (
        classify_drug_response(delta=-0.30, q=1e-4, q_reverse=1e-4, insufficient=False)
        == "mutant_strongly_drug_sensitive"
    )


def test_strong_moderate_boundary_is_inclusive_on_strong():
    # delta exactly at the strong cut → strong (<=), and exactly at the moderate cut → moderate.
    assert (
        classify_drug_response(delta=STRONG_EFFECT_DELTA, q=1e-3, q_reverse=0.9, insufficient=False)
        == "mutant_strongly_drug_sensitive"
    )
    assert (
        classify_drug_response(delta=MODERATE_EFFECT_DELTA, q=1e-3, q_reverse=0.9, insufficient=False)
        == "mutant_moderately_drug_sensitive"
    )


def test_alpha_boundary_is_strict_less_than():
    # q exactly at alpha does NOT pass (strict <), so a strong delta at q==alpha is not stratified.
    assert (
        classify_drug_response(delta=-0.50, q=STRATIFICATION_ALPHA, q_reverse=0.9, insufficient=False)
        == "not_drug_response_stratified"
    )
