"""Tests for the curated_prior ClaimType rung — skills#2295, epic #1507.

curated_prior is the LOWEST rung of the ClaimType ladder / CLAIM_TYPE_LAYER — asserted
background/prior knowledge (curated vocabularies, curated rosters, curated SL/paralog relationships,
the disclaimed literature crosswalk), not measured in this run. It sits strictly below
observational_property. With teeth:

  * a curated_prior is legitimately accepted when declared as a curated-prior-input (informs a frame);
  * check_input_integrity REFUSES a curated_prior consumed as a canonical-property-claim, a measurement,
    or a local-composite-claim (the over-claim this rung exists to close — a prior laundered as if it
    were a measured L2 fact);
  * an unresolved curated_prior still behaves like every other unresolved property input (no over-claim,
    since nothing is being consumed);
  * from_curated_prior mirrors from_concordance's None-handling convention.

This suite is additive and verdict-inert: it exercises evidence_frame.py's public API only, touches no
skill verdict / claim_vector / resolver / golden.
"""

from __future__ import annotations

import pytest
from _skills_common import evidence_frame as ef  # noqa: E402
from _skills_common.evidence_frame import (  # noqa: E402
    ClaimType,
    InputKind,
    TypedEvidence,
    TypeIntegrityError,
    check_input_integrity,
    from_curated_prior,
)


# ---- ladder placement -----------------------------------------------------------------------------
def test_curated_prior_is_the_lowest_rung():
    assert ef.CLAIM_TYPE_LAYER[ClaimType.CURATED_PRIOR] < ef.CLAIM_TYPE_LAYER[ClaimType.OBSERVATIONAL_PROPERTY]
    assert ef._EMITTED_RANK[ClaimType.CURATED_PRIOR] < ef._EMITTED_RANK[ClaimType.OBSERVATIONAL_PROPERTY]
    # ... but strictly above UNRESOLVED (a prior is a real, weaker-than-observation, epistemic object).
    assert ef._EMITTED_RANK[ClaimType.CURATED_PRIOR] > ef._EMITTED_RANK[ef.UNRESOLVED]


def test_curated_prior_input_kind_is_registered():
    assert InputKind.CURATED_PRIOR_INPUT in ef._ALL_INPUT_KINDS
    assert ef._KIND_ASSERTS_LAYER[InputKind.CURATED_PRIOR_INPUT] == ClaimType.CURATED_PRIOR


# ---- legitimate routing: a curated_prior informing an L3 frame is accepted -------------------------
def test_curated_prior_accepted_as_curated_prior_input():
    ev = from_curated_prior("target_biology_axis", {"axis": "receptor_tyrosine_kinase"})
    check_input_integrity(InputKind.CURATED_PRIOR_INPUT, ev)  # must not raise


def test_unresolved_curated_prior_is_not_an_over_claim():
    ev = from_curated_prior("target_biology_axis", None)
    assert ev.resolved is False
    assert ev.emitted_type == ef.UNRESOLVED
    check_input_integrity(InputKind.CURATED_PRIOR_INPUT, ev)  # absence under a property kind: fine


def test_from_curated_prior_none_convention_mirrors_from_concordance():
    ev = from_curated_prior("shed_antigen_targets", None)
    assert ev.claim_type == ClaimType.CURATED_PRIOR
    assert ev.resolved is False


# ---- mutation teeth: the laundering risk this rung closes -----------------------------------------
@pytest.mark.parametrize(
    "kind",
    [InputKind.CANONICAL_PROPERTY_CLAIM, InputKind.MEASUREMENT, InputKind.LOCAL_COMPOSITE_CLAIM],
)
def test_curated_prior_refused_as_measured_l2_fact(kind):
    """A curated_prior consumed as a stronger (measured) kind must FAIL — the laundering guard."""
    ev = from_curated_prior("target_biology_axis", {"axis": "receptor_tyrosine_kinase"})
    with pytest.raises(TypeIntegrityError):
        check_input_integrity(kind, ev)


def test_curated_prior_over_claim_message_names_the_property():
    ev = from_curated_prior("shed_antigen_targets", {"target": "EPCAM"})
    with pytest.raises(TypeIntegrityError, match="shed_antigen_targets"):
        check_input_integrity(InputKind.CANONICAL_PROPERTY_CLAIM, ev)


def test_directly_constructed_curated_prior_also_refused_as_canonical():
    """Bypass the adapter and hand-construct a resolved curated_prior — still refused as canonical."""
    ev = TypedEvidence(
        property_id="internalizing_antigen_targets",
        claim_type=ClaimType.CURATED_PRIOR,
        resolved=True,
        value={"target": "EPCAM"},
    )
    with pytest.raises(TypeIntegrityError):
        check_input_integrity(InputKind.MEASUREMENT, ev)


# ---- control: a real observational_property is still legitimately consumed as a measurement --------
def test_control_real_measurement_not_affected_by_new_rung():
    ev = ef.measurement("crispr_effect", -0.8)
    check_input_integrity(InputKind.MEASUREMENT, ev)  # must not raise
