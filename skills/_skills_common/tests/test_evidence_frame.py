"""Tests for the L3 typed-evidence frame (design G) — skills#1753, epic #1507/#1749.

Covers, with teeth:
  * the reference frame exercises all FOUR typed input kinds and all FIVE roles;
  * the type-integrity checker REFUSES over-claiming (mutation: a composite consumed as a canonical
    property must FAIL) — plus every named clause of the invariant;
  * enforced ACYCLICITY (a real dependency cycle and a decision->property monotonicity violation both
    raise);
  * the property->frame decision-reach audit (every rung-4 family reaches a frame; an unreached
    property is flagged);
  * roles-not-weights routing: unresolved-critical -> L4 QUESTION (never a kill); a measured-adverse
    veto DOWN-RANKS (never a kill); weak corroboration adds a reservation;
  * the adapter consumes a REAL rung-4 concordance claim built by its own family builder.

The frame is a NEW additive surface: this suite never touches a skill verdict / claim_vector /
resolver. Byte-stability of every existing verdict is proven by the per-skill replay goldens + the
resolver golden in the full suite, which this PR leaves unmodified.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2]  # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common import evidence_frame as ef  # noqa: E402
from _skills_common.evidence_frame import (  # noqa: E402
    ClaimType,
    Frame,
    FrameCycleError,
    FrameInput,
    InputKind,
    Role,
    TypedEvidence,
    TypeIntegrityError,
)


# ---- fixtures: typed evidence objects -----------------------------------------------------------
def _canonical(pid, state="essentiality_concordant_dependent", corr="high", ind=2, res=2):
    return TypedEvidence(
        property_id=pid,
        claim_type=ClaimType.INTEGRATED_PROPERTY,
        resolved=True,
        state=state,
        corroboration=corr,
        independent_arm_count=ind,
        resolved_source_count=res,
        value={"concordance_class": state, "integration_method": "explicit_deterministic"},
    )


# ==================================================================================================
# 1. Reference frame shape — all four input kinds, all five roles
# ==================================================================================================
def test_reference_frame_declares_all_four_input_kinds_and_five_roles():
    kinds = {i.kind for i in ef.REFERENCE_FRAME.inputs}
    roles = {i.role for i in ef.REFERENCE_FRAME.inputs}
    assert kinds == {
        InputKind.CANONICAL_PROPERTY_CLAIM,
        InputKind.LOCAL_COMPOSITE_CLAIM,
        InputKind.MEASUREMENT,
        InputKind.MISSING_UNRESOLVED,
    }
    assert roles == {
        Role.REQUIRED,
        Role.SUPPORTIVE,
        Role.CONTEXTUAL,
        Role.VETO_CAPABLE,
        Role.CRITICAL_UNKNOWN,
    }
    # the three rung-4 families are consumed as canonical property claims
    canon = {i.property_id for i in ef.REFERENCE_FRAME.inputs if i.kind == InputKind.CANONICAL_PROPERTY_CLAIM}
    assert canon == set(ef.RUNG4_CANONICAL_PROPERTIES)
    assert ef.REFERENCE_FRAME.claim_type == ClaimType.DECISION_FRAME


# ==================================================================================================
# 2. Type-integrity checker — MUTATION TEETH + every named clause
# ==================================================================================================
def test_type_integrity_refuses_a_composite_consumed_as_a_canonical_property():
    """MUTATION: feeding a within-skill composite classifier where a canonical property is declared
    must FAIL the checker. This is the teeth of the type-integrity invariant."""
    composite = ef.local_composite("composite_selectivity_class", "win_and_dist")
    # correctly declared as a local composite -> fine
    ef.check_input_integrity(InputKind.LOCAL_COMPOSITE_CLAIM, composite)
    # over-claimed as a canonical property -> refused
    with pytest.raises(TypeIntegrityError, match="stronger epistemic type"):
        ef.check_input_integrity(InputKind.CANONICAL_PROPERTY_CLAIM, composite)


def test_type_integrity_falsification_a_real_canonical_passes_as_canonical():
    ef.check_input_integrity(InputKind.CANONICAL_PROPERTY_CLAIM, _canonical("recurrence_concordance"))


def test_type_integrity_measurement_not_integrated_property():
    m = ef.measurement("dependency_effect_size", -1.2)
    ef.check_input_integrity(InputKind.MEASUREMENT, m)
    with pytest.raises(TypeIntegrityError, match="stronger epistemic type"):
        ef.check_input_integrity(InputKind.CANONICAL_PROPERTY_CLAIM, m)


def test_type_integrity_local_composite_not_atomic_measurement():
    """A composite may not be consumed as an atomic measurement (local-composite != atomic property)."""
    composite = ef.local_composite("composite_selectivity_class", "win_and_dist")
    with pytest.raises(TypeIntegrityError, match="atomic/canonical"):
        ef.check_input_integrity(InputKind.MEASUREMENT, composite)


def test_type_integrity_unresolved_not_neutral_when_declared_missing():
    """A missing/unresolved slot supplied a RESOLVED object is a declaration mismatch."""
    resolved = _canonical("normal_liability_concordance", state="liability_concordant_low")
    with pytest.raises(TypeIntegrityError, match="declared missing/unresolved"):
        ef.check_input_integrity(InputKind.MISSING_UNRESOLVED, resolved)


def test_type_integrity_l3_may_not_be_consumed_as_a_property():
    """An L3 decision_frame object fed to a property slot violates L3 != L2 fact."""
    l3 = TypedEvidence(property_id="some_frame", claim_type=ClaimType.DECISION_FRAME, resolved=True)
    with pytest.raises(TypeIntegrityError, match="L3 interpretation != L2 fact"):
        ef.check_input_integrity(InputKind.CANONICAL_PROPERTY_CLAIM, l3)


def test_type_integrity_absent_property_input_is_routed_not_raised():
    """Absence under a property kind is NOT a type violation (the evaluator routes it)."""
    ef.check_input_integrity(InputKind.CANONICAL_PROPERTY_CLAIM, ef.unresolved("recurrence_concordance"))


# ==================================================================================================
# 3. Acyclicity — real cycle + monotonicity
# ==================================================================================================
def test_reference_registry_is_acyclic():
    ef.assert_acyclic(ef.FRAME_REGISTRY, ef.reference_emitted_layers())


def test_acyclicity_detects_a_real_cycle():
    """Two decision frames each declaring the other as an input is a back-edge -> refused."""
    a = Frame(
        frame_id="frame_a",
        claim_type=ClaimType.SYNTHESIS,
        inputs=(FrameInput("frame_b", InputKind.CANONICAL_PROPERTY_CLAIM, Role.REQUIRED),),
    )
    b = Frame(
        frame_id="frame_b",
        claim_type=ClaimType.DECISION_FRAME,
        inputs=(FrameInput("frame_a", InputKind.CANONICAL_PROPERTY_CLAIM, Role.REQUIRED),),
    )
    layers = {"frame_a": ClaimType.SYNTHESIS, "frame_b": ClaimType.DECISION_FRAME}
    with pytest.raises(FrameCycleError):
        ef.assert_acyclic((a, b), layers)


def test_acyclicity_refuses_a_decision_claim_feeding_a_lower_layer():
    """A decision_frame consumed as an input by another decision_frame violates monotonicity
    (decision claims never feed lower-layer properties / same layer)."""
    downstream = Frame(
        frame_id="downstream",
        claim_type=ClaimType.DECISION_FRAME,
        inputs=(FrameInput("upstream_frame", InputKind.CANONICAL_PROPERTY_CLAIM, Role.REQUIRED),),
    )
    layers = {"upstream_frame": ClaimType.DECISION_FRAME, "downstream": ClaimType.DECISION_FRAME}
    with pytest.raises(FrameCycleError, match="STRICTLY higher layer"):
        ef.assert_acyclic((downstream,), layers)


# ==================================================================================================
# 4. Reach audit
# ==================================================================================================
def test_reach_audit_every_rung4_family_reaches_a_frame():
    audit = ef.decision_reach_audit(ef.FRAME_REGISTRY, ef.RUNG4_CANONICAL_PROPERTIES)
    # anti-vacuity: the audited universe is the three named rung-4 families
    assert set(ef.RUNG4_CANONICAL_PROPERTIES) == {
        "crispr_rnai_essentiality_concordance",
        "recurrence_concordance",
        "selectivity_concordance",
    }
    assert audit["unreached"] == []
    for pid in ef.RUNG4_CANONICAL_PROPERTIES:
        assert ef.REFERENCE_FRAME.frame_id in audit["reached"][pid]


def test_reach_audit_flags_an_unreached_property():
    audit = ef.decision_reach_audit(ef.FRAME_REGISTRY, ("a_property_no_frame_declares",))
    assert audit["unreached"] == ["a_property_no_frame_declares"]


def test_reverse_index_is_derived_and_maps_property_to_frame():
    idx = ef.build_reverse_index(ef.FRAME_REGISTRY)
    assert idx[ef.ESSENTIALITY_PROPERTY] == [ef.REFERENCE_FRAME.frame_id]
    # every declared input is reachable in the derived reverse index (no silent unreached declaration)
    for inp in ef.REFERENCE_FRAME.inputs:
        assert ef.REFERENCE_FRAME.frame_id in idx[inp.property_id]


# ==================================================================================================
# 5. Roles-not-weights routing
# ==================================================================================================
def _full_bundle(selectivity_state="selectivity_window_concordant", ess_corr="high"):
    """Everything the reference frame reads EXCEPT the deliberately-absent critical normal_liability."""
    return {
        ef.ESSENTIALITY_PROPERTY: _canonical(ef.ESSENTIALITY_PROPERTY, "essentiality_concordant_dependent", ess_corr),
        ef.RECURRENCE_PROPERTY: _canonical(ef.RECURRENCE_PROPERTY, "recurrence_concordant"),
        ef.SELECTIVITY_PROPERTY: _canonical(ef.SELECTIVITY_PROPERTY, selectivity_state),
        ef.DEPENDENCY_EFFECT_MEASUREMENT: ef.measurement(ef.DEPENDENCY_EFFECT_MEASUREMENT, -1.4),
        ef.COMPOSITE_SELECTIVITY_CLASS: ef.local_composite(ef.COMPOSITE_SELECTIVITY_CLASS, "win_and_dist"),
    }


def test_unresolved_critical_routes_to_l4_question_never_a_kill():
    """The reference frame's normal_liability is a deliberately-absent critical_unknown -> L4 QUESTION."""
    result = ef.evaluate_frame(ef.REFERENCE_FRAME, _full_bundle())
    assert result["decision"] == ef.DECISION_QUESTION
    assert result["unresolved_critical"] == [ef.NORMAL_LIABILITY_PROPERTY]
    assert ef.NORMAL_LIABILITY_PROPERTY in result["l4_question"]
    # NEVER a kill: the decision vocabulary has no negative/kill token; question is the routed outcome.
    assert result["decision"] != ef.DECISION_HOLD
    assert result["claim_type"] == ClaimType.DECISION_FRAME


def test_veto_on_measured_adverse_property_downranks_never_kills():
    """A veto_capable property with a MEASURED-adverse state down-ranks one notch; never a kill/question."""
    no_critical = Frame(
        frame_id="test_veto_frame",
        inputs=(
            FrameInput(
                ef.ESSENTIALITY_PROPERTY,
                InputKind.CANONICAL_PROPERTY_CLAIM,
                Role.REQUIRED,
                positive_states=frozenset({"essentiality_concordant_dependent"}),
            ),
            FrameInput(
                ef.SELECTIVITY_PROPERTY,
                InputKind.CANONICAL_PROPERTY_CLAIM,
                Role.VETO_CAPABLE,
                adverse_states=frozenset({"protein_masks_selectivity_window", "rna_masks_selectivity_window"}),
            ),
        ),
    )
    clean = {
        ef.ESSENTIALITY_PROPERTY: _canonical(ef.ESSENTIALITY_PROPERTY, "essentiality_concordant_dependent"),
        ef.SELECTIVITY_PROPERTY: _canonical(ef.SELECTIVITY_PROPERTY, "selectivity_window_concordant"),
    }
    assert ef.evaluate_frame(no_critical, clean)["decision"] == ef.DECISION_PRIORITIZE

    adverse = dict(clean)
    adverse[ef.SELECTIVITY_PROPERTY] = _canonical(ef.SELECTIVITY_PROPERTY, "protein_masks_selectivity_window")
    res = ef.evaluate_frame(no_critical, adverse)
    assert res["decision"] == ef.DECISION_PRIORITIZE_RESERVED  # down-ranked one notch, not killed
    assert res["vetoes_applied"] and "protein_masks_selectivity_window" in res["vetoes_applied"][0]


def test_required_resolved_but_non_positive_holds():
    frame = Frame(
        frame_id="test_required_frame",
        inputs=(
            FrameInput(
                ef.ESSENTIALITY_PROPERTY,
                InputKind.CANONICAL_PROPERTY_CLAIM,
                Role.REQUIRED,
                positive_states=frozenset({"essentiality_concordant_dependent"}),
            ),
        ),
    )
    bundle = {ef.ESSENTIALITY_PROPERTY: _canonical(ef.ESSENTIALITY_PROPERTY, "essentiality_concordant_nondependent")}
    assert ef.evaluate_frame(frame, bundle)["decision"] == ef.DECISION_HOLD


def test_weak_corroboration_on_a_required_property_adds_a_reservation():
    frame = Frame(
        frame_id="test_corr_frame",
        inputs=(
            FrameInput(
                ef.ESSENTIALITY_PROPERTY,
                InputKind.CANONICAL_PROPERTY_CLAIM,
                Role.REQUIRED,
                positive_states=frozenset({"essentiality_concordant_dependent"}),
            ),
        ),
    )
    bundle = {
        ef.ESSENTIALITY_PROPERTY: _canonical(
            ef.ESSENTIALITY_PROPERTY, "essentiality_concordant_dependent", corr="single_arm"
        )
    }
    res = ef.evaluate_frame(frame, bundle)
    assert res["reservations"]
    assert res["decision"] == ef.DECISION_PRIORITIZE_RESERVED


def test_required_unresolved_also_routes_to_question_never_a_kill():
    frame = Frame(
        frame_id="test_req_absent",
        inputs=(FrameInput(ef.ESSENTIALITY_PROPERTY, InputKind.CANONICAL_PROPERTY_CLAIM, Role.REQUIRED),),
    )
    res = ef.evaluate_frame(frame, {})  # essentiality absent
    assert res["decision"] == ef.DECISION_QUESTION
    assert res["unresolved_required"] == [ef.ESSENTIALITY_PROPERTY]


# ==================================================================================================
# 6. Adapter grounds on REAL rung-4 emitted output
# ==================================================================================================
def test_adapter_consumes_a_real_recurrence_concordance_claim():
    """Build a real recurrence_concordance via its own family builder and adapt it through the typed
    interface — proves the interface consumes actual rung-4 emitted shapes, not just hand-built dicts."""
    from _skills_common.genomic_claims import _recurrence_concordance_claim  # noqa: PLC0415

    h = {
        "driver_recurrence_class": "top_1pct",
        "genie_driver_recurrence_class": "top_decile",
        "pooled_driver_recurrence_class": None,
        "driver_recurrence_percentile": 99.7,
        "genie_driver_recurrence_percentile": 93.1,
        "pooled_driver_recurrence_percentile": None,
    }
    claim = _recurrence_concordance_claim(h)
    assert claim is not None and claim["integration_method"] == "explicit_deterministic"

    ev = ef.from_concordance(ef.RECURRENCE_PROPERTY, claim)
    assert ev.emitted_type == ClaimType.INTEGRATED_PROPERTY
    assert ev.state == claim["concordance_class"]
    # independence-correct: reads the independent-arm count, never resolved_source_count for corroboration
    assert ev.independent_arm_count == claim.get("corroborating_independent_arm_count")
    # passes as a canonical property; refused if over-claimed nowhere here
    ef.check_input_integrity(InputKind.CANONICAL_PROPERTY_CLAIM, ev)


def test_adapter_refuses_a_non_envelope_dict_as_canonical():
    with pytest.raises(TypeIntegrityError, match="not an L2b integrated_property"):
        ef.from_concordance("bogus", {"some": "dict"})


def test_adapter_absent_claim_is_unresolved():
    ev = ef.from_concordance(ef.SELECTIVITY_PROPERTY, None)
    assert ev.emitted_type == ef.UNRESOLVED
    assert not ev.resolved


# ==================================================================================================
# 8. Production entry — the L3 -> production beachhead (SK#1841)
# ==================================================================================================
def test_normal_liability_property_name_matches_the_key_safety_emits():
    """PRECONDITION (SK#1841): the critical_unknown input is named for the key safety_claims.py actually
    emits (`normal_liability_concordance`), so it is WIREABLE — while staying the deliberately-absent
    critical specimen."""
    assert ef.NORMAL_LIABILITY_PROPERTY == "normal_liability_concordance"
    crit = [i for i in ef.REFERENCE_FRAME.inputs if i.role == Role.CRITICAL_UNKNOWN]
    assert len(crit) == 1 and crit[0].property_id == "normal_liability_concordance"
    assert crit[0].kind == InputKind.MISSING_UNRESOLVED


def test_dependency_priority_frame_synthesizes_over_an_emitted_claim_vector():
    """The production entry consumes a functional-requirement claim_vector's already-emitted essentiality
    concordance claim as a typed input and routes to an L4 QUESTION on the absent safety critical."""
    from _skills_common.dependency_claims import _essentiality_concordance_claim

    # a REAL essentiality concordance claim (both assays agree, dependent)
    cards = {
        "pan-cancer-crispr-dependency-distribution": {"dependency_class": "strongly_selective"},
        "pan-cancer-rnai-dependency-distribution": {"rnai_dependency_class": "strongly_selective"},
    }
    ess = _essentiality_concordance_claim(cards)
    assert ess is not None and ess["integration_method"] == "explicit_deterministic"

    result = ef.dependency_priority_frame({"crispr_rnai_essentiality_concordance": ess})
    # the essentiality claim resolved as a typed input the frame synthesized over
    assert result["resolved_inputs"].get("crispr_rnai_essentiality_concordance") == ess["concordance_class"]
    assert result["claim_type"] == ClaimType.DECISION_FRAME
    # the absent safety critical routes to an L4 QUESTION (never a kill)
    assert result["decision"] == ef.DECISION_QUESTION
    assert result["unresolved_critical"] == [ef.NORMAL_LIABILITY_PROPERTY]
    assert ef.NORMAL_LIABILITY_PROPERTY in result["l4_question"]
    assert result["decision"] != ef.DECISION_HOLD


def test_dependency_priority_frame_verdict_inert_disclaimer():
    """The production surface is ADDITIVE / verdict-inert — the frame's disclaimer says it routes nothing
    back into any skill verdict / claim_vector / question_table / resolver."""
    result = ef.dependency_priority_frame({}, {})
    assert "routes NOTHING back" in result["_disclaimer"]
    # with nothing supplied the required essentiality is also unresolved -> still a question, never a kill
    assert result["decision"] == ef.DECISION_QUESTION
    assert ef.NORMAL_LIABILITY_PROPERTY in result["unresolved_critical"]


# ==================================================================================================
# 9. Second domain — the PRESENCE frame + the four surfaced concordance families (SK#1842)
# ==================================================================================================
def test_the_four_surfaced_families_are_declared_typed_inputs_with_correct_types():
    """The interface now DECLARES the four remaining built/surfaced concordance families as typed inputs
    (not just the three rung-4 families). Each carries its correct emitted layer (INTEGRATED_PROPERTY) and
    is consumed under a valid InputKind by a frame."""
    assert set(ef.SURFACED_CONCORDANCE_PROPERTIES) == {
        "bulk_vs_singlecell_coverage_concordance",
        "abundance_concordance",
        "subtype_restriction_concordance",
        "normal_liability_concordance",
    }
    layers = ef.reference_emitted_layers()
    for pid in ef.SURFACED_CONCORDANCE_PROPERTIES:
        # correct emitted layer: every surfaced family is an L2b integrated_property
        assert layers[pid] == ClaimType.INTEGRATED_PROPERTY
    # the three presence families are consumed as canonical property claims on PRESENCE_FRAME
    canon = {i.property_id for i in ef.PRESENCE_FRAME.inputs if i.kind == InputKind.CANONICAL_PROPERTY_CLAIM}
    assert canon == {
        ef.COVERAGE_CONCORDANCE_PROPERTY,
        ef.ABUNDANCE_CONCORDANCE_PROPERTY,
        ef.SUBTYPE_RESTRICTION_PROPERTY,
    }
    # normal_liability is the deliberately-absent critical on BOTH frames (missing/unresolved kind)
    crit = [i for i in ef.PRESENCE_FRAME.inputs if i.role == Role.CRITICAL_UNKNOWN]
    assert len(crit) == 1
    assert crit[0].property_id == ef.NORMAL_LIABILITY_PROPERTY
    assert crit[0].kind == InputKind.MISSING_UNRESOLVED


def test_presence_frame_shape_covers_the_roles_it_exercises():
    """The PRESENCE_FRAME exercises required / supportive / veto_capable / critical_unknown over the
    presence + safety families."""
    by_role = {i.role: i.property_id for i in ef.PRESENCE_FRAME.inputs}
    assert by_role[Role.REQUIRED] == ef.COVERAGE_CONCORDANCE_PROPERTY
    assert by_role[Role.SUPPORTIVE] == ef.ABUNDANCE_CONCORDANCE_PROPERTY
    assert by_role[Role.VETO_CAPABLE] == ef.SUBTYPE_RESTRICTION_PROPERTY
    assert by_role[Role.CRITICAL_UNKNOWN] == ef.NORMAL_LIABILITY_PROPERTY
    assert ef.PRESENCE_FRAME.claim_type == ClaimType.DECISION_FRAME


def test_registry_with_the_presence_frame_is_still_acyclic():
    """Two decision frames sharing property leaves (normal_liability) but no cross-frame edge stay a DAG."""
    ef.assert_acyclic(ef.FRAME_REGISTRY, ef.reference_emitted_layers())
    assert set(f.frame_id for f in ef.FRAME_REGISTRY) == {
        "corroborated_dependency_priority",
        "corroborated_tumor_presence",
    }


def test_reach_audit_every_surfaced_family_reaches_a_frame():
    """Reach ratchet lifted to the surfaced set: each of the four families is declared by >=1 frame."""
    audit = ef.decision_reach_audit(ef.FRAME_REGISTRY, ef.SURFACED_CONCORDANCE_PROPERTIES)
    assert audit["unreached"] == []
    for pid in (ef.COVERAGE_CONCORDANCE_PROPERTY, ef.ABUNDANCE_CONCORDANCE_PROPERTY, ef.SUBTYPE_RESTRICTION_PROPERTY):
        assert ef.PRESENCE_FRAME.frame_id in audit["reached"][pid]
    # normal_liability is the shared absent critical on BOTH frames
    assert set(audit["reached"][ef.NORMAL_LIABILITY_PROPERTY]) == {
        ef.REFERENCE_FRAME.frame_id,
        ef.PRESENCE_FRAME.frame_id,
    }


def test_presence_frame_type_integrity_teeth_composite_may_not_be_a_canonical_property():
    """MUTATION TEETH (SK#1842): the PRESENCE_FRAME declares coverage as a CANONICAL_PROPERTY_CLAIM. Feeding
    a within-skill LOCAL-COMPOSITE classifier into that slot must FAIL evaluate_frame — an object may not be
    consumed as a STRONGER epistemic type than it was emitted as (local-composite != atomic/canonical)."""
    # a composite masquerading as the coverage canonical property
    masquerade = {
        ef.COVERAGE_CONCORDANCE_PROPERTY: ef.local_composite(ef.COVERAGE_CONCORDANCE_PROPERTY, "coverage_concordant")
    }
    with pytest.raises(TypeIntegrityError, match="atomic/canonical|stronger epistemic type"):
        ef.evaluate_frame(ef.PRESENCE_FRAME, masquerade)
    # the honest canonical property passes through evaluate_frame (falsification)
    honest = {ef.COVERAGE_CONCORDANCE_PROPERTY: _canonical(ef.COVERAGE_CONCORDANCE_PROPERTY, "coverage_concordant")}
    assert ef.evaluate_frame(ef.PRESENCE_FRAME, honest)["claim_type"] == ClaimType.DECISION_FRAME


def _real_coverage_concordant_claim():
    """A REAL `bulk_vs_singlecell_coverage_concordance` claim (coverage_concordant) via its own builder."""
    from _skills_common.presence_claims import _coverage_concordance_claim  # noqa: PLC0415

    cards = {
        "tumor-rna-distribution": {"tumor_expression_class": "broadly_high", "distribution_pattern": "diffuse"},
        "tumor-scrna-celltype-expression": {
            "within_tumor_coverage_class": "high",
            "tce_antigen_escape_class": "escape_risk_low",
        },
    }
    return _coverage_concordance_claim(cards)


def test_tumor_presence_frame_synthesizes_over_emitted_presence_vectors():
    """The presence production entry consumes a tumor-presence claim vector's already-emitted coverage
    concordance claim as a typed input and routes to an L4 QUESTION on the absent safety critical."""
    cov = _real_coverage_concordant_claim()
    assert cov is not None and cov["integration_method"] == "explicit_deterministic"
    assert cov["concordance_class"] == "coverage_concordant"

    result = ef.tumor_presence_frame({"bulk_vs_singlecell_coverage_concordance": cov})
    # the coverage claim resolved as a typed input the frame synthesized over
    assert result["resolved_inputs"].get("bulk_vs_singlecell_coverage_concordance") == "coverage_concordant"
    assert result["claim_type"] == ClaimType.DECISION_FRAME
    # the absent safety critical routes to an L4 QUESTION (never a kill)
    assert result["decision"] == ef.DECISION_QUESTION
    assert result["unresolved_critical"] == [ef.NORMAL_LIABILITY_PROPERTY]
    assert ef.NORMAL_LIABILITY_PROPERTY in result["l4_question"]
    assert result["decision"] != ef.DECISION_HOLD


def test_tumor_presence_frame_reads_subtype_from_the_by_subtype_vector():
    """subtype_restriction_concordance is keyed on the BY-SUBTYPE vector, not the pooled one — the
    production entry reads it there and synthesizes over it as the veto_capable input."""
    cov = _real_coverage_concordant_claim()
    sub = {"concordance_class": "subtype_restriction_concordant", "integration_method": "explicit_deterministic"}
    result = ef.tumor_presence_frame(
        {"bulk_vs_singlecell_coverage_concordance": cov},
        {"subtype_restriction_concordance": sub},
    )
    assert result["resolved_inputs"].get("subtype_restriction_concordance") == "subtype_restriction_concordant"
    # a concordant (non-adverse) subtype restriction applies no veto
    assert result["vetoes_applied"] == []


def test_tumor_presence_frame_verdict_inert_disclaimer_and_empty_is_a_question():
    result = ef.tumor_presence_frame({}, {})
    assert "routes NOTHING back" in result["_disclaimer"]
    # nothing supplied: the required coverage anchor is also unresolved -> still a question, never a kill
    assert result["decision"] == ef.DECISION_QUESTION
    assert ef.NORMAL_LIABILITY_PROPERTY in result["unresolved_critical"]
