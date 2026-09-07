"""Per-SCOPE decomposition (genomic_alteration_by_scope + scope_of_driving_verdict).

The genomic_alteration verdict is a SCOPE HYBRID: the ladder-leading KO-dependency / variant-shape /
drug-response signals are pan-cancer DepMap/PRISM cell-line calls (localised to the queried lineage only
when powered, via each stratified card's evidence_scope), while patient recurrence, patient-focal CN,
TCGA fusion recurrence, and the IntOGen role are indication-native. This reducer classifies the SCOPE of
the driving verdict and rolls up which evidence exists at each scope. ADDITIVE / verdict-inert — it reads
fields already emitted by the cards and touches no resolver rung."""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

gap = load_run_py(Path(__file__).resolve().parent.parent, "gap_run_byscope")


def _card(cid, **fields):
    return {"card_id": cid, "summary": dict(fields)}


def _by_id(cards):
    return {c["card_id"]: c for c in cards}


# ── scope_of_driving_verdict ───────────────────────────────────────────────────────────────────────


def test_within_indication_dependency_is_indication_anchored():
    """KRAS/COADREAD-like: the strong mutation dependency leads the ladder and its evidence_scope is
    within_indication → the verdict is indication_anchored."""
    cards = _by_id(
        [
            _card(
                "mutation-stratified-dependency",
                mutation_stratification_class="mutant_strongly_dependent",
                evidence_scope="within_indication",
            ),
            _card("alteration-role", alteration_role="direct_driver_gof", intogen_scope="indication"),
        ]
    )
    assert gap._scope_of_driving_verdict(cards, "mutant-strongly-dependent-supportive") == "indication_anchored"


def test_pan_lineage_dependency_without_indication_support_is_extrapolation():
    """A dependency computed from pan-lineage evidence only, with no indication-native corroboration,
    is honestly a pan_cancer_extrapolation — the scope leak the verdict otherwise hides."""
    cards = _by_id(
        [
            _card(
                "copy-number-stratified-dependency",
                cn_stratification_class="amplified_strongly_dependent",
                evidence_scope="pan_lineage_evidence_only",
            ),
            _card("alteration-role", alteration_role="passenger", intogen_scope="pan_cancer"),
            _card("mutation-hotspot-frequency", driver_recurrence_class="bottom_decile"),
            _card("copy-number-distribution", patient_focal_cn_class="focal_neutral"),
            _card("fusion-rearrangement-landscape", fusion_class="no_recurrent_fusion"),
        ]
    )
    assert (
        gap._scope_of_driving_verdict(cards, "cn-amplified-strongly-dependent-supportive") == "pan_cancer_extrapolation"
    )


def test_pan_lineage_dependency_with_indication_role_is_mixed():
    """Same pan-lineage dependency, but an IntOGen indication-scoped driver role corroborates it in the
    queried indication → mixed (not a bare extrapolation)."""
    cards = _by_id(
        [
            _card(
                "copy-number-stratified-dependency",
                cn_stratification_class="amplified_strongly_dependent",
                evidence_scope="pan_lineage_evidence_only",
            ),
            _card("alteration-role", alteration_role="direct_driver_gof", intogen_scope="indication"),
        ]
    )
    assert gap._scope_of_driving_verdict(cards, "cn-amplified-strongly-dependent-supportive") == "mixed"


def test_patient_focal_cn_rung_is_indication_anchored():
    """A patient-focal CN landscape driver is inherently indication-native (TCGA GISTIC in-tissue)."""
    assert gap._scope_of_driving_verdict({}, "cn-patient-focal-amplified-supportive") == "indication_anchored"


def test_pan_cancer_variant_shape_rung_without_support_is_extrapolation():
    """A bare missense-dominant SHAPE call (cell-line MAF, pan-cancer) with no indication anchor."""
    cards = _by_id([_card("alteration-role", intogen_scope="pan_cancer")])
    assert gap._scope_of_driving_verdict(cards, "mut-missense-dominant-supportive") == "pan_cancer_extrapolation"


def test_no_driving_rule_is_not_applicable():
    assert gap._scope_of_driving_verdict({}, None) == "not_applicable"


# ── genomic_alteration_by_scope structure ────────────────────────────────────────────────────────


def test_by_scope_has_three_scopes_and_flags_presence():
    cards = [
        _card(
            "mutation-stratified-dependency",
            mutation_stratification_class="mutant_strongly_dependent",
            evidence_scope="within_indication",
        ),
        _card(
            "mutation-hotspot-frequency", driver_recurrence_class="top_1pct", genie_driver_recurrence_class="top_1pct"
        ),
        _card("alteration-role", alteration_role="direct_driver_gof", intogen_scope="indication"),
    ]
    bs = gap._genomic_alteration_by_scope(cards, "mutant-strongly-dependent-supportive")
    assert set(bs) == {"scope_of_driving_verdict", "pan_cancer", "indication", "subtype"}
    assert bs["scope_of_driving_verdict"] == "indication_anchored"
    assert bs["pan_cancer"]["evidence_present"] is True  # mutation dependency present
    assert bs["indication"]["evidence_present"] is True  # top_1pct recurrence + role present
    assert bs["pan_cancer"]["mutation_dependency_scope"] == "within_indication"
    assert bs["indication"]["driver_recurrence_class"] == "top_1pct"
    # subtype is a placeholder until --subtypes is passed (patched by main()), so it must not fabricate.
    assert bs["subtype"]["evidence_present"] is False


def test_by_scope_indication_absent_when_no_patient_evidence():
    """Only pan-cancer cell-line evidence present → indication.evidence_present is False (an honest gap,
    not a fabricated indication anchor)."""
    cards = [
        _card(
            "mutation-stratified-dependency",
            mutation_stratification_class="mutant_strongly_dependent",
            evidence_scope="pan_lineage_evidence_only",
        ),
    ]
    bs = gap._genomic_alteration_by_scope(cards, "mutant-strongly-dependent-supportive")
    assert bs["pan_cancer"]["evidence_present"] is True
    assert bs["indication"]["evidence_present"] is False
    assert bs["scope_of_driving_verdict"] == "pan_cancer_extrapolation"
