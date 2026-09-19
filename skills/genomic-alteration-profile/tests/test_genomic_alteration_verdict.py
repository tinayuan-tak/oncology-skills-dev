"""genomic-alteration-profile _verdict coverage.

This multi-class skill fuses a SNV/indel axis (primary) with a copy-number modifier. These tests
pin EVERY fired rule_id → verdict mapping and, crucially, make the DELIBERATE non-driver choices
explicit (mutation-stratified WT / not-stratified / insufficient-rate are intentionally NOT
genomic-alteration drivers — they fall through), so a future SILENT drop of a class that SHOULD
drive fails CI.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

gap = load_run_py(Path(__file__).resolve().parent.parent, "gap_run")


def _v(*rule_ids):
    return gap._verdict([{"rule_id": r} for r in rule_ids])


# --- mutation axis: driver classes ----------------------------------------


def test_biomarker_stratified_is_primary_driver():
    # scope-coherence Phase 1: a biomarker verdict now requires the indication-scope gate co-fire
    # (mutant-indication-scoped-context, fired when evidence_scope is within_indication) — a pan-lineage
    # dependency alone no longer earns it. The gate does NOT change the driving_rule (kept explicit).
    assert _v("mutant-strongly-dependent-supportive", "mutant-indication-scoped-context") == (
        "biomarker_stratified_dependency",
        "mutant-strongly-dependent-supportive",
    )


def test_moderate_biomarker():
    assert _v("mutant-moderately-dependent-supportive", "mutant-indication-scoped-context")[0] == (
        "moderate_biomarker_dependency"
    )


def test_biomarker_requires_indication_scope_gate():
    # The Phase-1 flip: the SAME strong dependency WITHOUT the indication-scope gate (i.e. pan-lineage
    # evidence only) no longer reads biomarker — it falls through (here, to insufficient with nothing
    # else fired). The by_scope block surfaces the pan-cancer-extrapolation scope for such a call.
    assert _v("mutant-strongly-dependent-supportive")[0] == "insufficient"


def test_lof_and_missense_dominant_patterns():
    # Variant-class composition verdicts: recurrent_{lof,missense}_driver were renamed to
    # {lof,missense}_dominant_pattern (they report spectrum composition, not patient recurrence).
    # These fire on variant-CLASS composition (mutation-type-counts), NOT patient recurrence — the
    # honest name. "recurrent" is reserved for signals that literally count sample recurrence
    # (cn-recurrently-*, fusion-landscape). Pure verdict-string rename; precedence/logic unchanged.
    assert _v("mut-lof-dominant-supportive")[0] == "lof_dominant_pattern"
    assert _v("mut-missense-dominant-supportive")[0] == "missense_dominant_pattern"


# --- CN axis --------------------------------------------------------------


def test_cn_amplification_driver_when_mutation_passenger():
    # CN drives, mutation is passenger → CN driver (not collapsed to passenger)
    assert _v("cn-recurrently-amplified-supportive", "mut-no-mutations-neutral") == (
        "recurrent_amplification_driver",
        "cn-recurrently-amplified-supportive",
    )


def test_cn_deletion_driver():
    # SPECIFICITY (resolver 1.9.0). The DELETION arm of copy_number_class is shallow-inclusive and
    # clears its 0.20 cut for 60.1% of ALL genes genome-wide (median gene 0.228, ABOVE the cut) vs 2.9%
    # for the amplification arm and 1.5% for the deep-deletion fraction — measured over 1433 randomly
    # sampled 26Q1 WGS CN gene columns. It reads the aneuploid cell-line background, so it establishes
    # NO driver on its own: FGFR2/STAD, a focal-AMPLIFICATION target in gastric cancer, read
    # `confirmed_driver` driven by this rule. It remains a display/modality signal.
    assert _v("cn-recurrently-deleted-supportive")[0] == "insufficient"
    # The two arms that DO survive an aneuploidy-background null each still drive the verdict alone:
    # the biallelic cell-line event (deep/homozygous, 1.5% null) ...
    assert _v("cn-recurrent-homozygous-deletion-supportive")[0] == "recurrent_deletion_driver"
    # ... and the indication-native patient GISTIC -2 event.
    assert _v("cn-patient-focal-deleted-supportive")[0] == "recurrent_deletion_driver"
    # ... and neither is weakened by the shallow-inclusive class co-firing (it is additive, never a veto).
    assert _v("cn-recurrent-homozygous-deletion-supportive", "cn-recurrently-deleted-supportive")[0] == (
        "recurrent_deletion_driver"
    )


def test_cn_deletion_driver_needs_a_specific_deletion_not_just_a_role():
    # The confirmed_driver / multi_class deletion rungs are gated the same way: a driver ROLE plus the
    # 60%-null shallow-inclusive class is NOT a confirmed deletion driver (that combination is what gave
    # SMAD4/STK11/FGFR2 their `confirmed_*` calls), but a role plus a SPECIFIC deletion event is.
    assert _v("cn-recurrently-deleted-supportive", "alteration-role-lof-driver-neutral")[0] == "insufficient"
    assert _v("cn-patient-focal-deleted-supportive", "alteration-role-lof-driver-neutral")[0] == (
        "confirmed_lof_driver"
    )
    assert _v("cn-recurrent-homozygous-deletion-supportive", "alteration-role-lof-driver-neutral")[0] == (
        "confirmed_lof_driver"
    )
    # ... and the INDICATION-NATIVE patient event leads the pan-cancer cell-line one when both fire
    # (scope honesty: it previously ranked BELOW, which also mislabelled scope_of_driving_verdict).
    assert _v(
        "cn-patient-focal-deleted-supportive",
        "cn-recurrent-homozygous-deletion-supportive",
        "alteration-role-lof-driver-neutral",
    ) == ("confirmed_lof_driver", "cn-patient-focal-deleted-supportive")


def test_promiscuous_fusion_does_not_outrank_snv_recurrence():
    # SPECIFICITY (resolver 1.9.0). fusion_recurrence_confidence == moderate_promiscuous is the fusion
    # card's OWN self-declared MIXED bucket ("genuine kinase fusions AND amplicon passenger SVs both
    # fall here"); #983 demoted only the AMPLIFIED subset. STK11/LUAD — 3/632 samples (0.47%), ZERO
    # recurrent partners, at a DELETED tumour-suppressor locus — was reading recurrent_fusion_driver
    # over its real mechanism (top-1% patient SNV recurrence in a TSG).
    assert _v("fusion-landscape-recurrent-driver-supportive", "snv-recurrence-top-driver-supportive")[0] == (
        "recurrent_snv_driver"
    )
    # WITH the high-partner confidence gate (same partner >=3 samples: EML4-ALK, TMPRSS2-ERG) the fusion
    # is partner-specific and DOES lead — the genuine-kinase-fusion case must not regress.
    assert _v(
        "fusion-landscape-recurrent-driver-supportive",
        "fusion-recurrence-high-partner-context",
        "snv-recurrence-top-driver-supportive",
    ) == ("recurrent_fusion_driver", "fusion-landscape-recurrent-driver-supportive")


def test_variant_class_shape_does_not_outrank_landscape_recurrence():
    # SPECIFICITY (resolver 1.9.0). missense_dominant fires for 62% of the review panel INCLUDING both
    # the GAPDH and ACTB negative controls — >=0.70 missense is the no-selection expectation of the
    # genetic code — and mutation-type-counts' own caveat says "'missense_dominant' alone doesn't prove
    # oncogene status". So a spectrum SHAPE must not pre-empt a measured patient landscape event.
    # ROS1/LUAD, a textbook fusion-driven LUAD target, read `missense_dominant_pattern`.
    assert _v("mut-missense-dominant-supportive", "fusion-landscape-recurrent-driver-supportive")[0] == (
        "recurrent_fusion_driver"
    )
    assert _v("mut-lof-dominant-supportive", "cn-patient-focal-deleted-supportive")[0] == ("recurrent_deletion_driver")
    # The shape rungs still rank ABOVE mixed/passenger — a driver-shaped spectrum is more informative
    # than "no dominant class", so demoting them must not silently erase the verdicts themselves.
    assert _v("mut-missense-dominant-supportive")[0] == "missense_dominant_pattern"
    assert _v("mut-lof-dominant-supportive")[0] == "lof_dominant_pattern"


def test_fusion_landscape_recurrent_driver():
    # Fusion-only driver: a recurrently rearranged patient oncogene with NO DepMap dependency line
    # now reads recurrent_fusion_driver (was: collapsed to passenger/insufficient). The fusion analog
    # of recurrent_amplification_driver — a landscape-recurrence driver, not a nominating positive.
    assert _v("fusion-landscape-recurrent-driver-supportive")[0] == "recurrent_fusion_driver"
    # ... even when the mutation axis says "no mutations" (the exact line-poor-oncogene gap).
    assert _v("fusion-landscape-recurrent-driver-supportive", "mut-no-mutations-neutral")[0] == (
        "recurrent_fusion_driver"
    )


def test_precedence_by_strength_strong_cn_over_moderate_mut():
    # Effect-strength precedence: for a dually-altered gene, a STRONG CN-dependency outranks a MODERATE
    # mutation-dependency — the larger effect is named the driver. Both map to the stratified
    # verdicts, but the driving_rule must be the strong CN rule, not the moderate mut rule.
    # Both dependency rungs carry their indication-scope gate (Phase 1); strong CN still wins precedence.
    v, drv = _v(
        "mutant-moderately-dependent-supportive",
        "mutant-indication-scoped-context",
        "cn-amplified-strongly-dependent-supportive",
        "cn-amplified-indication-scoped-context",
    )
    assert v == "biomarker_stratified_dependency"
    assert drv == "cn-amplified-strongly-dependent-supportive", (
        "strong CN dependency must win over moderate mutation dependency (precedence-by-strength)"
    )


# --- multi-class ----------------------------------------------------------


def test_both_axes_drive_is_multi_class():
    # multi_class_driver requires an alteration-role DRIVER co-signal, not variant
    # SHAPE alone (a missense+CN passenger with no driver role → missense_dominant_pattern, the
    # CEACAM5 fix). A genuine dually-altered DRIVER therefore includes the role rule.
    assert (
        _v(
            "mut-missense-dominant-supportive",
            "cn-recurrently-amplified-supportive",
            "alteration-role-gof-driver-supportive",
        )[0]
        == "multi_class_driver"
    )


# --- deliberate NON-drivers (documented fall-through — the C exhaustiveness pins) --


def test_mixed_and_passenger_are_non_driver_but_not_silent():
    # these ARE mapped (to their own verdict) — not a silent insufficient
    assert _v("mut-mixed-neutral")[0] == "mixed_pattern"
    assert _v("mut-no-mutations-neutral")[0] == "passenger_pattern"


def test_nothing_fired_is_insufficient():
    assert gap._verdict([]) == ("insufficient", None)


def test_stratified_non_driver_classes_are_intentionally_not_drivers():
    """DELIBERATE (documented): a WT-dependency / not-stratified / insufficient-mutation-
    rate is NOT a genomic-alteration DRIVER — the mutation axis maps only the mutant-*
    biomarker + lof/missense/mixed/passenger classes. If one of those stratified rules is
    the ONLY thing fired, the skill correctly falls through to insufficient (a genomic-
    alteration verdict shouldn't be manufactured from a WT dependency). This test PINS
    that intent so a future change that silently starts (or stops) driving is caught."""
    for rid in (
        "wt-strongly-dependent-neutral",  # if such a rule fires here
        "not-mutation-stratified-neutral",
    ):
        # not in _mutation_verdict's map → mut_verdict None → falls through
        v, drv = _v(rid)
        assert v == "insufficient" and drv is None, (
            f"{rid} is intentionally a non-driver for genomic-alteration; if this should "
            f"change, update _mutation_verdict + this test together"
        )


# --- SUBTYPE panorama (2026-08-05 hardening) ------------------------------
# The subtype axis is a DESCRIPTIVE panorama: it must never enter the verdict spine,
# and its display-flavor label must track the card's own delta thresholds. These tests
# exercise _resolve_subtype_panorama with a stubbed resolve_cards so no S3/MAF is needed.


def _panorama_with(monkeypatch, per_subgroup, delta, n_with_data, missing=False):
    """Drive _resolve_subtype_panorama with a synthetic card summary."""
    summary = {
        "per_subgroup_metrics": per_subgroup,
        "cross_subgroup_delta_frequency": delta,
        "n_subgroups_with_data": n_with_data,
        "max_subgroup_frequency": None,
        "min_subgroup_frequency": None,
    }
    card = {"card_id": "subgroup-stratified-mutation-frequency", "summary": summary, "_missing": missing}

    def _fake_resolve_cards(card_ids, target, indication, subgroup_context=None):
        # Contract guard: the panorama path MUST thread resolved_strata_ids or the
        # dispatcher returns only a data-note (the whole reason this card is off the
        # scalar CARDS list). Assert the wiring passes it.
        assert subgroup_context and subgroup_context.get("resolved_strata_ids"), (
            "subtype panorama must pass subgroup_context.resolved_strata_ids"
        )
        return [card]

    monkeypatch.setattr(gap, "resolve_cards", _fake_resolve_cards)
    return gap._resolve_subtype_panorama("KRAS", "COADREAD", ["MSI_H", "MSS"])


def test_subtype_pattern_subgroup_specific_when_delta_high(monkeypatch):
    rows = [{"stratum": "MSI_H", "evidence_state": "measured"}, {"stratum": "MSS", "evidence_state": "measured"}]
    res = _panorama_with(monkeypatch, rows, delta=0.22, n_with_data=2)
    # Phase 3: the return is now per-axis (axes.subtype_axis is the SNV panorama, unchanged shape).
    assert res["axes"]["subtype_axis"]["subtype_mutation_pattern"] == "subgroup_specific_pattern"
    assert res["axes"]["subtype_axis"]["measured_strata"] == ["MSI_H", "MSS"]


def test_subtype_pattern_uniform_when_delta_low(monkeypatch):
    rows = [{"stratum": "MSI_H", "evidence_state": "measured"}, {"stratum": "MSS", "evidence_state": "measured"}]
    res = _panorama_with(monkeypatch, rows, delta=0.03, n_with_data=2)
    assert res["axes"]["subtype_axis"]["subtype_mutation_pattern"] == "uniform_across_subgroups"


def test_subtype_pattern_underpowered_when_strata_evaluated_but_under_two_measured(monkeypatch):
    # POWER HONESTY (v2.19.0): strata WERE evaluated but only ONE cleared the n-floor (the other absent)
    # → `underpowered`. We looked and the arms are too thin to contrast — a measured limitation, NOT an
    # absence of anything to compare. (Previously this and the nothing-evaluated case both read
    # `not_informative`; the two are now distinct — see the not_informative test below.)
    rows = [{"stratum": "MSI_H", "evidence_state": "measured"}, {"stratum": "MSS", "evidence_state": "absent"}]
    res = _panorama_with(monkeypatch, rows, delta=None, n_with_data=1)
    assert res["axes"]["subtype_axis"]["subtype_mutation_pattern"] == "underpowered"


def test_subtype_pattern_not_informative_when_nothing_evaluated(monkeypatch):
    # The OTHER half of the split: NO per-stratum records were evaluated at all (a could-not-look) →
    # `not_informative`, distinct from the underpowered "looked-but-too-thin" above.
    res = _panorama_with(monkeypatch, [], delta=None, n_with_data=0)
    assert res["axes"]["subtype_axis"]["subtype_mutation_pattern"] == "not_informative"


def test_subtype_axis_is_not_in_scalar_cards():
    """The panorama card is a PANORAMA dispatcher — putting it on the whole-cohort CARDS
    list would make it perpetually _missing (no strata threaded). It must live ONLY on
    SUBTYPE_CARDS. Guards against a future re-add to CARDS."""
    assert "subgroup-stratified-mutation-frequency" not in gap.CARDS
    assert "subgroup-stratified-mutation-frequency" in gap.SUBTYPE_CARDS
