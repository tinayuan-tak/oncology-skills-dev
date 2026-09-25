"""Unit tests for genomic-alteration-profile's claim vector (skills/_skills_common/genomic_claims.py),
the FOURTH concrete over claim_vector_core. Pin the per-class SNV/CN/FUS driver tiers + the DEP
(alteration-confers-dependency) max-over-stratified-classes + corroboration + the multi-class headline.
Pure over a headline dict — no S3, no card reads.

The KRAS-shaped headline mirrors the frozen KRAS/COADREAD genomic replay fixture; ERBB2/MET-shaped
contrast cases exercise amplification- and fusion-driven mixes (the whole point of the multi-class
skill — it must not read "not a driver" for an amp/fusion-driven target).
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]  # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.claim_vector_core import CORROBORATION_ORD, SIGNAL_ORD  # noqa: E402
from _skills_common.genomic_claims import (  # noqa: E402  # noqa: E402
    _CN_CELL_LINE_RECURRENT,
    _CN_FOCAL_NEG,
    _CN_FOCAL_POS,
    _CN_SIGNAL,
    _FUS_SIGNAL,
    _RECURRENCE_SIGNAL,
    _ROLE_SIGNAL,
    _SPLICE_SIGNAL,
    _UNMEASURED_RECURRENCE,
    _recurrence_class,
    _recurrence_concordance_claim,
    _recurrence_direction,
    _role_corroboration,
    _role_signal,
    _spl_corroboration,
    _spl_signal,
    genomic_claim_vector,
    genomic_key_signals,
)


def _by_class(
    snv_landscape=None,
    snv_rec=None,
    cn=None,
    amp_expr=None,
    cn_strat=None,
    fusion=None,
    fusion_strat=None,
    genie_sv=None,
    mut_strat=None,
):
    return {
        "snv_indel": {"verdict": snv_landscape, "recurrence_class": snv_rec, "stratified_dependency_class": mut_strat},
        "copy_number": {"verdict": cn, "stratified_dependency_class": cn_strat, "amp_expr_dependency_class": amp_expr},
        "fusion": {
            "verdict": fusion,
            "stratified_dependency_class": fusion_strat,
            "genie_sv_recurrence_class": genie_sv,
        },
    }


def _kras_headline():
    """KRAS/COADREAD-shaped: recurrent missense SNV driver (top_1pct), no CN/fusion, strong
    mutant-selective + amp-expr dependency, drug-sensitive."""
    return {
        "genomic_alteration_by_class": _by_class(
            snv_landscape="missense_dominant",
            snv_rec="top_1pct",
            cn="broadly_neutral",
            amp_expr="amplified_overexpressed_strongly_dependent",
            cn_strat="amplified_moderately_dependent",
            fusion="no_recurrent_fusion",
            fusion_strat="fusion_positive_moderately_dependent",
            genie_sv="mid",
            mut_strat="mutant_strongly_dependent",
        ),
        "driver_recurrence_class": "top_1pct",
        "genie_driver_recurrence_class": "top_1pct",
        "overall_mutation_frequency": 0.42,
        "patient_focal_cn_class": "focal_neutral",
        "mutation_stratification_class": "mutant_strongly_dependent",
        "stratified_evidence_scope": "within_indication",
        "cn_stratification_class": "amplified_moderately_dependent",
        "amp_expr_stratification_class": "amplified_overexpressed_strongly_dependent",
        "fusion_stratification_class": "fusion_positive_moderately_dependent",
        "drug_response_stratification_class": "mutant_strongly_drug_sensitive",
    }


def test_kras_snv_driven_with_dependency():
    vec = genomic_claim_vector(_kras_headline(), [])
    assert vec["SNV"]["signal"] == "strong"
    assert vec["CN"]["signal"] == "absent" and vec["FUS"]["signal"] == "absent"
    # DEP = max over the 4 stratified classes (mutant_strongly + amp_expr_strongly → strong), drug-confirmed
    assert vec["DEP"]["signal"] == "strong" and vec["DEP"]["corroboration"] == "high"
    ks = genomic_key_signals(_kras_headline(), [])
    assert ks["headline"] == "SNV/indel-driven alteration, biomarker-stratified dependency."


def test_amplification_driven_is_not_read_as_not_a_driver():
    """ERBB2-shaped: broadly-neutral SNV but recurrently amplified + patient-focal-confirmed. The
    multi-class skill must surface the CN driver, not imply 'not a driver' off the SNV axis."""
    h = {
        "genomic_alteration_by_class": _by_class(
            snv_landscape="no_mutations",
            cn="recurrently_amplified",
            amp_expr="amplified_overexpressed_strongly_dependent",
            fusion="no_recurrent_fusion",
        ),
        "driver_recurrence_class": "bottom_decile",
        "patient_focal_cn_class": "recurrent_focal_amplification",
        "amp_expr_stratification_class": "amplified_overexpressed_strongly_dependent",
        "drug_response_stratification_class": "not_drug_response_stratified",
    }
    vec = genomic_claim_vector(h, [])
    assert vec["SNV"]["signal"] == "absent"  # no SNV
    assert vec["CN"]["signal"] == "strong"  # cell-line amplified + patient-focal confirms → strong
    assert vec["CN"]["corroboration"] == "high"
    assert vec["DEP"]["signal"] == "strong"
    ks = genomic_key_signals(h, [])
    assert ks["headline"].startswith("Copy-number-driven alteration")


def test_patient_focal_amp_drives_cn_signal_when_cellline_neutral():
    """Regression: HER2/CCND1 reality — recurrently focally amplified in PATIENT tumours but
    broadly_neutral in the DepMap cell-line panel. The CN claim must read the patient-focal amplification
    (signal `moderate`), NOT `absent` off the neutral cell-line arm. (Prior bug: focal only upgraded an
    already-≥moderate cell-line signal, so cell-line-neutral+patient-focal-amp silently read `absent`.)"""
    h = {
        "genomic_alteration_by_class": _by_class(
            snv_landscape="no_mutations", cn="broadly_neutral", fusion="no_recurrent_fusion"
        ),
        "patient_focal_cn_class": "recurrent_focal_amplification",
        "drug_response_stratification_class": "not_drug_response_stratified",
    }
    vec = genomic_claim_vector(h, [])
    assert vec["CN"]["signal"] == "moderate"  # patient-focal amp drives it (was 'absent' pre-fix)
    # and when the cell-line arm ALSO agrees, it strengthens to 'strong' (unchanged behaviour):
    h2 = dict(h)
    h2["genomic_alteration_by_class"] = _by_class(
        snv_landscape="no_mutations", cn="recurrently_amplified", fusion="no_recurrent_fusion"
    )
    assert genomic_claim_vector(h2, [])["CN"]["signal"] == "strong"


def test_fusion_driven():
    h = {
        "genomic_alteration_by_class": _by_class(
            snv_landscape="no_mutations",
            cn="broadly_neutral",
            fusion="recurrent_fusion_driver",
            fusion_strat="fusion_positive_strongly_dependent",
            genie_sv="top_1pct",
        ),
        "fusion_stratification_class": "fusion_positive_strongly_dependent",
        "drug_response_stratification_class": "data_unavailable",
    }
    vec = genomic_claim_vector(h, [])
    assert vec["FUS"]["signal"] == "strong" and vec["FUS"]["corroboration"] == "high"
    assert vec["DEP"]["signal"] == "strong"
    assert genomic_key_signals(h, [])["headline"].startswith("Fusion-driven alteration")


def test_multi_class_driver():
    h = {
        "genomic_alteration_by_class": _by_class(
            snv_landscape="missense_dominant", snv_rec="top_decile", cn="recurrently_amplified"
        ),
        "driver_recurrence_class": "top_decile",
        "patient_focal_cn_class": "recurrent_focal_amplification",
    }
    ks = genomic_key_signals(h, [])
    assert ks["headline"].startswith("Multi-class alteration driver")


def test_passenger_and_wt_dependent_is_absent_dep():
    """A passenger with a WT-dependent (not alteration-conferred) dependency: DEP must be `absent`,
    NOT read as the alteration conferring the dependency."""
    h = {
        "genomic_alteration_by_class": _by_class(
            snv_landscape="missense_dominant",
            snv_rec="bottom_decile",
            cn="broadly_neutral",
            fusion="no_recurrent_fusion",
            mut_strat="wt_strongly_dependent",
        ),
        "driver_recurrence_class": "bottom_decile",
        "mutation_stratification_class": "wt_strongly_dependent",
        "drug_response_stratification_class": "data_unavailable",
    }
    vec = genomic_claim_vector(h, [])
    assert vec["SNV"]["signal"] == "absent"
    assert vec["DEP"]["signal"] == "absent"  # WT is dependent → the ALTERATION does not confer it
    assert genomic_key_signals(h, [])["headline"] == "No recurrent alteration (passenger / not altered)."


def test_dep_underpowered_is_gap_not_absent():
    h = {
        "genomic_alteration_by_class": _by_class(snv_landscape="missense_dominant", snv_rec="mid"),
        "driver_recurrence_class": "mid",
        "mutation_stratification_class": "insufficient_mutation_rate",
        "cn_stratification_class": "data_unavailable",
        "amp_expr_stratification_class": "data_unavailable",
        "fusion_stratification_class": "data_unavailable",
    }
    vec = genomic_claim_vector(h, [])
    assert vec["DEP"]["signal"] == "unmeasured"  # insufficient-rate + data_unavailable → gap, not absent


def test_underpowered_cn_and_fus_read_as_a_gap_with_intent_not_absent_or_driver():
    """C1 foundation. A classifier that emits `underpowered` (measured, but under its power floor) below
    CN / fusion recurrence must read as the gap-WITH-INTENT `underpowered` tier — never `unmeasured`
    (which would erase that the axis WAS consulted) and never `absent` (a measured floor / passenger). The
    token is forward-declared for C3's emitters (depmap_cn_distribution `_classify_cn`, tcga `_classify`,
    tcga_fusion_consensus `fclass`); this pins the mapping so a C3 emitter cannot silently fall through to
    `unmeasured`, and pins the tier DISTINCT from the `data_unavailable`/`no_recurrent_fusion` families."""
    # the map entries, distinct from the nobody-looked gap and from a measured `absent` floor
    assert _CN_SIGNAL["underpowered"] == "underpowered"
    assert _FUS_SIGNAL["underpowered"] == "underpowered"
    assert _CN_SIGNAL["underpowered"] != _CN_SIGNAL["data_unavailable"]  # gap-with-intent ≠ nobody-looked
    assert _FUS_SIGNAL["underpowered"] != _FUS_SIGNAL["no_recurrent_fusion"]  # ≠ a measured `absent` floor
    # end-to-end through the claim vector: the axis signal is the gap tier, off-scale (never a driver/floor)
    cn = genomic_claim_vector({"genomic_alteration_by_class": _by_class(cn="underpowered")}, [])["CN"]
    assert cn["signal"] == "underpowered" and SIGNAL_ORD[cn["signal"]] is None
    fus = genomic_claim_vector({"genomic_alteration_by_class": _by_class(fusion="underpowered")}, [])["FUS"]
    assert fus["signal"] == "underpowered" and SIGNAL_ORD[fus["signal"]] is None
    # …and the CORROBORATION collapses too: an underpowered arm looked but is off-scale, so there is
    # nothing for a second arm to agree with. Pins the `_cn_/_fus_corroboration` off-scale guards — a
    # regression back to a string match on `"unmeasured"` would let this read as a measured `single_arm`.
    assert cn["corroboration"] == "unmeasured", "an underpowered CN arm is a gap, not a measured arm"
    assert fus["corroboration"] == "unmeasured", "an underpowered fusion arm is a gap, not a measured arm"


def test_field_names_are_corroboration():
    vec = genomic_claim_vector(_kras_headline(), [])
    assert "corroboration" in vec["SNV"] and "reliability" not in vec["SNV"]


# ── citable evidence atoms (values bound to {card_id, fields} + entity) ──────────────────────────────
def _kras_genomic_cards():
    """Minimal genomic source-card summaries mirroring the real KRAS/COADREAD package fields."""
    return [
        {
            "card_id": "mutation-hotspot-frequency",
            "summary": {
                "driver_recurrence_class": "top_1pct",
                "pooled_mutation_frequency": 0.4346,
                "pooled_driver_recurrence_percentile": 99.97,
                "n_samples_in_indication": 559,
                "n_samples_mutated": 235,
            },
        },
        {
            "card_id": "copy-number-distribution",
            "summary": {
                "copy_number_class": "broadly_neutral",
                "cn_distribution_shape": "bimodal_mixed",
                "cn_median_panel": 1.056,
                "cn_p95_panel": 2.262,
                "patient_focal_cn_class": "focal_neutral",
            },
        },
        {
            "card_id": "mutation-stratified-dependency",
            "summary": {
                "mutation_stratification_class": "mutant_strongly_dependent",
                "delta_chronos_hotspot_mut_vs_wt": -1.1423,
                "median_chronos_hotspot_mutant": -1.7287,
                "median_chronos_hotspot_wildtype": -0.5864,
                "hotspot_mannwhitney_q": 1.25e-10,
                "n_hotspot_mutant": 43,
                "n_hotspot_wildtype": 45,
                "evidence_scope": "within_indication",
            },
        },
    ]


def test_genomic_atoms_present_and_citable_with_cards():
    vec = genomic_claim_vector(_kras_headline(), _kras_genomic_cards())
    snv = vec["SNV"]["evidence_atom"]
    assert snv["cite"]["card_id"] == "mutation-hotspot-frequency"
    assert snv["values"]["pooled_mutation_frequency"] == 0.4346  # frequency, citable
    # DEP atom carries the stratified EFFECT size + significance (the decision-relevant magnitude)
    dep = vec["DEP"]["evidence_atom"]
    assert dep["cite"]["card_id"] == "mutation-stratified-dependency"
    assert dep["values"]["delta_chronos_hotspot_mut_vs_wt"] == -1.1423
    assert dep["values"]["hotspot_mannwhitney_q"] == 1.25e-10
    # CN atom carries a distribution_shape (bimodal_mixed) — a notable atom even under a neutral label
    assert vec["CN"]["evidence_atom"]["values"]["cn_distribution_shape"] == "bimodal_mixed"


def test_genomic_atoms_absent_without_cards():
    vec = genomic_claim_vector(_kras_headline(), [])
    for ax in ("SNV", "CN", "FUS", "DEP"):
        assert "evidence_atom" not in vec[ax], f"{ax} gained an atom with no source card"


# ── SPL (splice-exon-skip) signal/corroboration co-movement ──────────────────────────────────────
# Regression for the latent asymmetry: `_spl_signal` and `_spl_corroboration` once applied DIFFERENT
# fallbacks to the same class (signal→`absent` via an else-branch, corrob→`unmeasured`), and the map
# keyed a dead `no_exon_skip` class the splice card never emits (real vocab: recurrent_splice_driver /
# splice_event_off_indication / no_registered_event / data_unavailable). Both now key off `_spl_tier`.
def _spl_h(cls, n=None):
    d = {"verdict": cls}
    if n is not None:
        d["n_depmap_carriers"] = n
    return {"genomic_alteration_by_class": {"splice": d}}


def test_spl_dead_class_key_removed():
    # the card never emits `no_exon_skip`; keying it was dead. Real non-driver classes ARE mapped.
    assert "no_exon_skip" not in _SPLICE_SIGNAL
    assert _SPLICE_SIGNAL["splice_event_off_indication"] == "absent"
    assert _SPLICE_SIGNAL["no_registered_event"] == "absent"


def test_spl_driver_is_corroborated():
    # A curated driver with a live DepMap carrier is a genuine SECOND arm → strong + high. WITHOUT a
    # carrier the curation arm stands alone: `single_arm`, not `moderate` — there is no second arm for the
    # curation call to partly agree with, and `moderate` claimed exactly that.
    assert _spl_signal(_spl_h("recurrent_splice_driver", n=3), None)[0] == "strong"
    assert _spl_corroboration(_spl_h("recurrent_splice_driver", n=3), None) == "high"
    assert _spl_corroboration(_spl_h("recurrent_splice_driver"), None) == "single_arm"


def test_spl_off_indication_carrier_arm_is_incommensurate():
    """ARM-COMMENSURABILITY (SK#1674, sibling of the landed #1667 GENIE-superset fix).

    `_spl_corroboration` folds a curated splice-registry arm (`splice_exon_skip_class`) and a live
    DepMap-carrier arm (`n_depmap_carriers`). `exon_skip_carrier.depmap_carriers` is PAN-CANCER — it
    counts every DepMap line carrying the event, with no indication filter. That count cannot agree or
    disagree with `splice_event_off_indication`, a curated INDICATION-SCOPED negative ("the event is
    registered but NOT oncogenic in THIS indication"): whether METex14 physically appears in DepMap's
    (mostly-lung) panel says nothing about whether it drives off its curated scope. So the carrier arm
    must leave the frame → `single_arm`, NOT a manufactured `low`/`high`.

    Inputs are RAW ARM TOKENS (the curated class + a stored carrier count), re-derived through the real
    function — no derived tier is baked into a fixture that could never fail. n=3 is the live MET/LUAD
    audit carrier count, which a MET run in any off-lung indication (MET/COADREAD, MET/STAD are real
    corpus rows) carries unchanged, since the probe is pan-cancer."""
    # The bug flips a vote in BOTH directions. Before the fix these read `low` and `high` respectively;
    # both are spurious because the pan-cancer carrier count is incommensurate with the off-scope negative.
    assert _spl_corroboration(_spl_h("splice_event_off_indication", n=3), None) == "single_arm", (
        "pan-cancer carriers cannot CONTRADICT an indication-scoped off-indication call (was a false `low`)"
    )
    assert _spl_corroboration(_spl_h("splice_event_off_indication", n=0), None) == "single_arm", (
        "pan-cancer 0-carriers cannot CONFIRM an indication-scoped off-indication call (was a false `high`)"
    )
    # DepMap not consulted → the arm leaves the frame anyway (unchanged, both branches agree here).
    assert _spl_corroboration(_spl_h("splice_event_off_indication"), None) == "single_arm"

    # CONCORDANT CONTROL — the commensurate case must stay a genuine two-arm vote. A curated DRIVER in its
    # oncogenic indication IS confirmed by pan-cancer carriers (METex14's carriers are its own lung lines),
    # so this stays `high` and is BYTE-STABLE across the fix (the real MET/LUAD audit emission).
    assert _spl_corroboration(_spl_h("recurrent_splice_driver", n=3), None) == "high"
    # And a whole-registry negative keeps its relative reading (the producer emits n=None here, but the
    # branch is preserved: a hypothetical carrier of an unregistered event is a genuine conflict).
    assert _spl_corroboration(_spl_h("no_registered_event", n=7), None) == "low"
    assert _spl_corroboration(_spl_h("no_registered_event", n=0), None) == "high"


def test_spl_signal_corroboration_comove_over_full_vocab():
    """CO-MOVEMENT IS NOW AN EXACT IFF ON MEASUREDNESS, which is the stronger form of what this test
    always wanted. It formerly read "corroboration is `unmeasured` for every NON-POSITIVE signal", lumping
    the measured floor `absent` in with the gap `unmeasured` — convention B, retired fleet-wide 2026-09-14
    (see `test_the_measured_absent_convention_is_UNIFORM_across_the_genomic_fleet`). Lumping them here was
    the `gap != absent` invariant inverted: it made a curated "the registry reports no event" render
    exactly like "the registry was never read".

    So the axis is measured together or unmeasured together, in BOTH directions — the gap is the only
    state that collapses corroboration, and every measured signal (including the negative floor) carries a
    tier. Both branches are asserted, so neither half can be deleted silently.

    Both MEASURED sets are derived from the shared ladders rather than listed, so adding a rung (as
    `single_arm` was) cannot make either assertion narrow silently — the previous literal
    `("moderate", "high")` would have rejected the new rung as a lost corroboration."""
    measured_rungs = {r for r, o in CORROBORATION_ORD.items() if o is not None}
    assert "single_arm" in measured_rungs and "unmeasured" not in measured_rungs
    for cls in list(_SPLICE_SIGNAL) + ["no_exon_skip", None, "some_future_class"]:
        sig = _spl_signal(_spl_h(cls), None)[0]
        corr = _spl_corroboration(_spl_h(cls), None)
        if SIGNAL_ORD.get(sig) is None:  # a GAP — nobody looked, so there is nothing to corroborate
            assert corr == "unmeasured", f"{cls!r}: signal={sig} is a gap but corrob={corr}"
        else:  # MEASURED, negative floor included — a finding a second arm could agree with
            assert corr in measured_rungs, f"{cls!r}: measured signal={sig} lost corroboration ({corr})"


def test_spl_common_cases_are_absent_not_unmeasured():
    # the common no-curated-event case and an off-indication event are a measured floor, not a gap
    assert _spl_signal(_spl_h("no_registered_event"), None)[0] == "absent"
    assert _spl_signal(_spl_h("splice_event_off_indication"), None)[0] == "absent"
    # a missing/failed read stays a gap
    assert _spl_signal(_spl_h(None), None)[0] == "unmeasured"
    assert _spl_signal(_spl_h("data_unavailable"), None)[0] == "unmeasured"


# ── ROLE (curated alteration-role) signal/corroboration co-movement ──────────────────────────────
# The SPL twin above, on the axis that needs it MORE. `_spl_signal`/`_spl_corroboration` both route
# through the shared `_spl_tier`, so they physically cannot disagree about measuredness. ROLE has TWO
# INDEPENDENT derivations of one vocabulary — `_role_signal:163` and `_role_corroboration:183` each run
# their own `_ROLE_SIGNAL.get(cls, "unmeasured")` — and nothing makes them co-move. That is
# `feedback_two_files_route_the_same_axis` in miniature: one axis, two readers, no guard tying them.
def _role_h(cls, fd=None):
    """ROLE reads the headline FLAT (`alteration_role` / `functional_direction`), not through
    `genomic_alteration_by_class` like the per-class axes — the curated role call is class-AGNOSTIC by
    design (`genomic_claims.py:149-151`), so it needs its own helper rather than reusing `_spl_h`."""
    return {"alteration_role": cls, "functional_direction": fd}


def test_role_signal_corroboration_comove_over_full_vocab():
    """The measuredness IFF, over the full class vocabulary CROSSED with the full direction vocabulary.

    Convention A is what makes this load-bearing here: `passenger` is now a MEASURED negative that keeps a
    tier, so `absent` and `unmeasured` are no longer interchangeable on this axis and the two lookups'
    agreement is a correctness property rather than a coincidence. An edit to either derivation alone — a
    class added to one, a default changed on one side — desynchronises them, and before this test nothing
    in the suite touched `_role_signal` or `_role_corroboration` at all.

    `measured_rungs` is DERIVED from CORROBORATION_ORD, never listed, for the reason the SPL twin's
    docstring records: a literal `("moderate", "high")` would have rejected `single_arm` as a lost
    corroboration the day the rung was added."""
    measured_rungs = {r for r, o in CORROBORATION_ORD.items() if o is not None}
    assert "single_arm" in measured_rungs and "unmeasured" not in measured_rungs
    # every declared class + a gap + an UNSEEN future class, × the closed direction vocabulary
    for cls in list(_ROLE_SIGNAL) + [None, "some_future_class"]:
        for fd in ("activating", "loss_of_function", "ambiguous", None):
            h = _role_h(cls, fd)
            sig = _role_signal(h, None)[0]
            corr = _role_corroboration(h, None)
            if SIGNAL_ORD.get(sig) is None:  # a GAP — nobody looked, so there is nothing to corroborate
                assert corr == "unmeasured", f"{cls!r}/{fd!r}: signal={sig} is a gap but corrob={corr}"
            else:  # MEASURED, `passenger`'s negative floor included
                assert corr in measured_rungs, f"{cls!r}/{fd!r}: measured signal={sig} lost corrob ({corr})"


def test_role_direction_arm_is_read_relative_to_the_signal_side():
    """The half a measuredness IFF cannot see: the direction arm must be read RELATIVE to the role call,
    or a contradiction files as agreement. `_role_corroboration`'s docstring claims a curated `passenger`
    carrying a definitive direction "is a real conflict and now reports `low`" — an absolute
    positive-direction-agrees rule would report `high` for that pair and read as a corroborated passenger.

    `ambiguous` is asserted NOT to be a conflict: IntOGen rows disagreeing WITH EACH OTHER is
    inconclusive, not opposed, so the arm leaves the frame (→ `single_arm`) rather than voting against."""
    # driver + definitive direction: two agreeing measured arms
    assert _role_signal(_role_h("direct_driver_gof", "activating"), None)[0] == "strong"
    assert _role_corroboration(_role_h("direct_driver_gof", "activating"), None) == "high"
    assert _role_corroboration(_role_h("direct_driver_lof", "loss_of_function"), None) == "high"
    assert _role_corroboration(_role_h("predictive_biomarker", "activating"), None) == "high"
    # measured negative + definitive direction: the arms CONTRADICT → low, not high
    assert _role_signal(_role_h("passenger", "activating"), None)[0] == "absent"
    assert _role_corroboration(_role_h("passenger", "activating"), None) == "low"
    assert _role_corroboration(_role_h("passenger", "loss_of_function"), None) == "low"
    # `ambiguous`/null leave the frame — one arm stands alone, on EITHER side of the signal
    for cls in ("direct_driver_gof", "passenger"):
        assert _role_corroboration(_role_h(cls, "ambiguous"), None) == "single_arm"
        assert _role_corroboration(_role_h(cls), None) == "single_arm"
    # the gap collapses the axis regardless of how definitive the direction is
    assert _role_corroboration(_role_h("data_unavailable", "activating"), None) == "unmeasured"


# ── CASE-031: the CN demotion mirror (cell-line recurrent vs patient-tumour focal-neutral) ────────
def _cn_disagree_headline(cell_line_cls):
    """The measured discordance shape from the genomic-20 panel: DepMap calls the locus recurrently
    amplified/deleted, but GISTIC says patient tumours are focal-neutral (0.1-2.3% of the cohort)."""
    return {
        "genomic_alteration_by_class": _by_class(
            snv_landscape="no_mutations", cn=cell_line_cls, fusion="no_recurrent_fusion"
        ),
        "patient_focal_cn_class": "focal_neutral",
        "drug_response_stratification_class": "not_drug_response_stratified",
    }


def test_cellline_recurrent_over_focal_neutral_patients_is_demoted_in_BOTH_directions():
    """CASE-031. `_cn_corroboration` already returned `low` for this shape while `_cn_signal` kept
    publishing a measured-POSITIVE `moderate` — corroboration was bidirectional, signal was one-way.

    Iterates `_CN_CELL_LINE_RECURRENT` rather than naming the two tokens, so a vocabulary that grows a
    third recurrent cell-line class is covered by declaration; the length assert keeps that derivation
    honest (a token RENAMED out of the set would otherwise make this test vacuously pass over 0 cases).
    """
    assert len(_CN_CELL_LINE_RECURRENT) >= 2, "population shrank — the symmetry claim is no longer tested"
    for cls in _CN_CELL_LINE_RECURRENT:
        vec = genomic_claim_vector(_cn_disagree_headline(cls), [])
        assert vec["CN"]["signal"] == "weak", f"{cls}: measured patient focal-neutral did not demote"
        assert vec["CN"]["corroboration"] == "low", f"{cls}: corroboration arm regressed"
        assert "not population recurrence" in vec["CN"]["evidence"], f"{cls}: demotion unnarrated"


def test_cn_demotion_is_keyed_on_a_MEASURED_negative_not_on_a_gap():
    """DLL3/SCLC shape: cell-line `recurrently_deleted` with NO patient-CN read. An unmeasured patient
    arm is not a contradiction — demoting on it would price a coverage gap as disagreement. This is the
    both-directions companion to the test above and the reason `_CN_FOCAL_NEG` is not `!= focal event`."""
    for gap in ("data_unavailable", None):
        h = _cn_disagree_headline("recurrently_deleted")
        h["patient_focal_cn_class"] = gap
        vec = genomic_claim_vector(h, [])
        assert vec["CN"]["signal"] == "moderate", f"patient-focal {gap!r} wrongly demoted the CN claim"
        assert "not population recurrence" not in vec["CN"]["evidence"]


def test_cn_elevation_and_agreement_paths_survive_the_demotion_arm():
    """Anti-vacuity in the other direction: the four controls that must NOT move. PTEN/MYC-shaped
    agreement stays `strong`, HER2/CCND1-shaped patient-only focal stays `moderate`, and a `mixed`
    cell-line call over focal-neutral patients is untouched (it was never a recurrent positive)."""
    for cls, focal in (
        ("recurrently_deleted", "recurrent_focal_deletion"),
        ("recurrently_amplified", "recurrent_focal_amplification"),
    ):
        h = _cn_disagree_headline(cls)
        h["patient_focal_cn_class"] = focal
        assert genomic_claim_vector(h, [])["CN"]["signal"] == "strong", f"{cls}: agreement path regressed"
    h = _cn_disagree_headline("broadly_neutral")
    h["patient_focal_cn_class"] = "recurrent_focal_amplification"
    assert genomic_claim_vector(h, [])["CN"]["signal"] == "moderate", "patient-only elevation path regressed"
    assert genomic_claim_vector(_cn_disagree_headline("mixed"), [])["CN"]["signal"] == "weak"


def test_cn_focal_populations_are_disjoint_and_declared():
    """Structural pin: the elevation and demotion arms are an if/elif over two sets, so an overlap would
    make the demotion silently unreachable for the overlapping token. Also pins every recurrent cell-line
    class as a POSITIVE tier in `_CN_SIGNAL` — the premise that makes demotion meaningful."""
    assert not (_CN_FOCAL_POS & _CN_FOCAL_NEG)
    for cls in _CN_CELL_LINE_RECURRENT:
        assert _CN_SIGNAL[cls] not in ("absent", "unmeasured"), f"{cls} is not a positive CN call"


# ── CASE-032: a truthy sentinel is not a measurement ──────────────────────────────────────────────
def test_unmeasured_recurrence_sentinel_does_not_shadow_a_measured_class():
    """CASE-032. `pooled or per_indication` short-circuits on the NON-EMPTY string "data_unavailable",
    discarding a measured `bottom_decile` floor and republishing it as `unmeasured` — failing OPEN in the
    direction that hides false negatives."""
    assert (
        _recurrence_class(
            {"pooled_driver_recurrence_class": "data_unavailable", "driver_recurrence_class": "bottom_decile"}
        )
        == "bottom_decile"
    )
    # precedence among MEASURED reads is unchanged: pooled still wins
    assert (
        _recurrence_class({"pooled_driver_recurrence_class": "top_decile", "driver_recurrence_class": "mid"})
        == "top_decile"
    )
    # a caller-supplied fallback is reached only after both named reads are unmeasured
    assert _recurrence_class({"pooled_driver_recurrence_class": "data_unavailable"}, "mid") == "mid"
    # all-unmeasured keeps the sentinel (evidence prose must say data_unavailable, not None)
    assert (
        _recurrence_class(
            {"pooled_driver_recurrence_class": "data_unavailable", "driver_recurrence_class": "data_unavailable"}
        )
        == "data_unavailable"
    )
    assert _recurrence_class({}) is None
    # an UNRECOGNISED token is not a declared sentinel and must NOT be skipped (it may be a new real band)
    assert (
        _recurrence_class({"pooled_driver_recurrence_class": "some_future_band", "driver_recurrence_class": "mid"})
        == "some_future_band"
    )


def test_unmeasured_recurrence_set_is_derived_from_the_signal_map():
    """The set is computed from `_RECURRENCE_SIGNAL`, not restated, so a new unavailability token joins by
    declaration. Pinned BY NAME so a rename cannot leave this green over an empty set."""
    assert _UNMEASURED_RECURRENCE == {"data_unavailable"}
    assert all(_RECURRENCE_SIGNAL[k] == "unmeasured" for k in _UNMEASURED_RECURRENCE)


def test_sentinel_fix_reaches_every_recurrence_surface():
    """The fan-out that makes CASE-032 more than a helper bug: FIVE surfaces read the or-chain (signal,
    corroboration, the SNV evidence atom, and BOTH narrator strings). A measured `bottom_decile` floor must
    read as a measured `absent` on all of them, not as a gap."""
    h = {
        "genomic_alteration_by_class": _by_class(
            snv_landscape="missense_dominant", cn="broadly_neutral", fusion="no_recurrent_fusion"
        ),
        "pooled_driver_recurrence_class": "data_unavailable",
        "driver_recurrence_class": "bottom_decile",
        "drug_response_stratification_class": "not_drug_response_stratified",
    }
    vec = genomic_claim_vector(h, [])
    assert vec["SNV"]["signal"] == "absent", "signal surface still reads the sentinel"
    assert vec["SNV"]["corroboration"] != "unmeasured", "corroboration surface still reads the sentinel"
    assert "bottom_decile" in vec["SNV"]["evidence"] and "data_unavailable" not in vec["SNV"]["evidence"]
    blob = repr(genomic_key_signals(h, []))
    assert "bottom_decile" in blob, "narrator surfaces still quote the sentinel"


# ── L2b-5: recurrence_concordance (SK#1629) — MC3 × GENIE concordance + the envelope's dependence slot ──
# The FIRST conformance test of docs/EVIDENCE_PROPERTY_ENVELOPE_v0.md from a foreign modality (variant
# recurrence, not continuous abundance/dependency) AND the first family with a genuinely DEPENDENT source
# (pooled ⊃ MC3+GENIE). These tests pin: the direction split, the four classes, the corroboration frame,
# the envelope's TWO COUNTS + THREE source notions, that pooled is evidence-not-corroboration and NEVER
# resurrects the key, the M3 defeat-EVERY-independent-arm discipline, byte-stability, and verdict-inertness.
def _rec_h(mc3=None, genie=None, pooled=None, mc3_pct=None, genie_pct=None, pooled_pct=None):
    """A minimal headline carrying only the recurrence fields the claim reads (all live on the headline,
    already read by run.py — no card reads)."""
    return {
        "genomic_alteration_by_class": _by_class(),  # keep the rest of the vector well-formed
        "driver_recurrence_class": mc3,
        "genie_driver_recurrence_class": genie,
        "pooled_driver_recurrence_class": pooled,
        "driver_recurrence_percentile": mc3_pct,
        "genie_driver_recurrence_percentile": genie_pct,
        "pooled_driver_recurrence_percentile": pooled_pct,
    }


def test_recurrence_direction_reuses_the_driver_split():
    # bottom_decile is the ONLY measured NEGATIVE band; every other measured band is a positive driver
    # call; data_unavailable / off-roster / None are UNRESOLVED gaps (gap != absent).
    assert _recurrence_direction("top_1pct") == "recurrent"
    assert _recurrence_direction("top_decile") == "recurrent"
    assert _recurrence_direction("mid") == "recurrent"
    assert _recurrence_direction("bottom_decile") == "not_recurrent"
    assert _recurrence_direction("data_unavailable") is None  # a gap, NOT a measured negative
    assert _recurrence_direction(None) is None
    assert _recurrence_direction("some_off_roster_token") is None


def test_recurrence_concordant_positive_two_agreeing_arms():
    claim = _recurrence_concordance_claim(_rec_h(mc3="top_1pct", genie="top_decile"))
    assert claim["concordance_class"] == "recurrence_concordant"
    assert claim["corroboration"] == "high"  # two INDEPENDENT arms agree
    assert claim["corroborating_independent_arm_count"] == 2
    assert claim["resolved_source_count"] == 2  # no pooled
    assert claim["concordance_support"] == {"agreed_direction": "recurrent"}
    assert claim["integration_method"] == "explicit_deterministic"
    assert claim["grain"] == "patient_cohort_variant"


def test_recurrence_concordant_negative_is_a_measured_floor_not_a_gap():
    # both arms read the measured bottom_decile floor: a real "we looked; not a recurrent driver" AGREEMENT
    # (Convention A) — corroborated, not collapsed to unmeasured.
    claim = _recurrence_concordance_claim(_rec_h(mc3="bottom_decile", genie="bottom_decile"))
    assert claim["concordance_class"] == "recurrence_concordant"
    assert claim["corroboration"] == "high"
    assert claim["concordance_support"] == {"agreed_direction": "not_recurrent"}


def test_panel_masks_recurrence_is_a_low_corroboration_disagreement():
    # MC3 exome recurrent, GENIE panel a measured not-recurrent floor → the panel misses it.
    claim = _recurrence_concordance_claim(_rec_h(mc3="top_1pct", genie="bottom_decile"))
    assert claim["concordance_class"] == "panel_masks_recurrence"
    assert claim["corroboration"] == "low"  # a disagreement caps corroboration
    assert claim["corroborating_independent_arm_count"] == 2
    assert claim["concordance_support"] == {"recurrent_in": "mc3_exome", "not_recurrent_in": "genie_panel"}


def test_exome_masks_recurrence_is_the_mirror():
    claim = _recurrence_concordance_claim(_rec_h(mc3="bottom_decile", genie="top_1pct"))
    assert claim["concordance_class"] == "exome_masks_recurrence"
    assert claim["corroboration"] == "low"
    assert claim["concordance_support"] == {"recurrent_in": "genie_panel", "not_recurrent_in": "mc3_exome"}


def test_single_independent_arm_degrades_not_omits():
    # ONE independent arm resolves (GENIE a data_unavailable gap) → single_source_only, corroboration
    # single_arm, key PRESENT. This is the envelope's "emit-on-one-arm" boundary (essentiality/normal-
    # liability precedent), chosen so the resolved_source_count != corroborating_independent_arm_count
    # case is SURFACED, not hidden. Defeating one arm only DEGRADES (M3).
    claim = _recurrence_concordance_claim(_rec_h(mc3="top_1pct", genie="data_unavailable"))
    assert claim["concordance_class"] == "single_source_only"
    assert claim["corroboration"] == "single_arm"
    assert claim["corroborating_independent_arm_count"] == 1
    assert claim["concordance_support"] == {
        "resolved_by": "mc3_exome",
        "resolved_call": "top_1pct",
        "resolved_direction": "recurrent",
    }


def test_key_omitted_when_neither_independent_arm_resolves():
    # Byte-stable: both independent arms are gaps → no claim (key omitted).
    assert _recurrence_concordance_claim(_rec_h(mc3="data_unavailable", genie=None)) is None
    assert _recurrence_concordance_claim(_rec_h()) is None
    # and it is genuinely absent from the emitted vector (not merely None)
    vec = genomic_claim_vector(_rec_h(mc3="data_unavailable", genie=None), [])
    assert "recurrence_concordance" not in vec


def test_pooled_is_evidence_not_corroboration_and_never_resurrects():
    # (a) pooled ALONE can never emit the claim: both independent arms are gaps, pooled resolves → OMITTED.
    # This is the `pooled OR driver` superset-as-fallback anti-pattern being replaced.
    assert _recurrence_concordance_claim(_rec_h(mc3="data_unavailable", genie=None, pooled="top_1pct")) is None
    # (b) with both independent arms present, pooled is SHOWN + PRESERVED (resolved_source_count 3) but
    # NEVER inflates corroboration and is corroboration_INELIGIBLE (the three source notions kept separate).
    claim = _recurrence_concordance_claim(_rec_h(mc3="top_1pct", genie="top_decile", pooled="top_1pct"))
    assert claim["corroborating_independent_arm_count"] == 2  # pooled EXCLUDED
    assert claim["resolved_source_count"] == 3  # pooled INCLUDED as evidence
    assert claim["corroboration"] == "high"  # pooled did NOT inflate it beyond the two real arms
    pooled_src = next(s for s in claim["source_support"] if s["source"] == "pooled")
    assert pooled_src["resolved"] is True and pooled_src["quality_eligible"] is True
    assert pooled_src["corroboration_eligible"] is False  # dependent != independent corroboration
    assert pooled_src["derived_from"] == ["mc3_exome", "genie_panel"]
    assert claim["evidence_dependence"]["derived_sources"]["pooled"]["corroboration_eligible"] is False


def test_m3_defeat_every_independent_supply_path():
    """M3 all-supply fidelity: the concordance conclusion must survive defeating ONE arm (degrade only)
    and vanish ONLY when EVERY independent arm is defeated — with pooled unable to keep it alive."""
    full = _rec_h(mc3="top_1pct", genie="top_decile", pooled="top_1pct")
    assert _recurrence_concordance_claim(full)["concordance_class"] == "recurrence_concordant"
    # defeat GENIE only → still emits, degraded to single_source_only (pooled irrelevant to emission)
    m1 = dict(full, genie_driver_recurrence_class="data_unavailable")
    assert _recurrence_concordance_claim(m1)["concordance_class"] == "single_source_only"
    # defeat BOTH independent arms (pooled STILL present) → key omitted; pooled does not resurrect it
    m2 = dict(m1, driver_recurrence_class="data_unavailable")
    assert _recurrence_concordance_claim(m2) is None


def test_retained_quantitative_is_recoverable_per_source():
    # fidelity/recoverability: the raw percentile anchor is DEMOTED into the payload, not deleted, and is
    # recoverable per source (store an irreproducible number, re-read it here).
    claim = _recurrence_concordance_claim(_rec_h(mc3="top_1pct", genie="top_decile", mc3_pct=99.7, genie_pct=93.1))
    by_src = {s["source"]: s for s in claim["source_support"]}
    assert by_src["mc3_exome"]["retained_quantitative"]["driver_recurrence_percentile"] == 99.7
    assert by_src["genie_panel"]["retained_quantitative"]["driver_recurrence_percentile"] == 93.1
    assert by_src["mc3_exome"]["provenance"]["headline_field"] == "driver_recurrence_class"


def test_recurrence_concordance_is_verdict_inert():
    # NO `signal` key (never a chip / tier / averaged) and PURELY ADDITIVE: for the SAME headline the L2b
    # claim only appends its own key — every pre-existing SNV/CN/FUS/SPL/DEP/ROLE axis is byte-identical to
    # the bare build_claim_vector (the axes DO read the recurrence bands directly, but the concordance
    # claim itself routes nothing back into them or the verdict).
    from _skills_common.claim_vector_core import build_claim_vector  # noqa: PLC0415
    from _skills_common.genomic_claims import _DISCLAIMER, GENOMIC_CLAIM_SPEC  # noqa: PLC0415

    h = _rec_h(mc3="top_1pct", genie="top_decile")
    claim = _recurrence_concordance_claim(h)
    assert "signal" not in claim
    assert "verdict-INERT" in claim["_disclaimer"]
    base = build_claim_vector(GENOMIC_CLAIM_SPEC, h, [], _DISCLAIMER)
    vec = genomic_claim_vector(h, [])
    for ax in ("SNV", "CN", "FUS", "SPL", "DEP", "ROLE"):
        assert vec[ax] == base[ax], f"{ax} axis moved when recurrence_concordance was added"
    assert set(vec) - set(base) == {"recurrence_concordance"}  # the ONLY delta


def test_dependence_structure_is_relational_not_a_global_boolean():
    claim = _recurrence_concordance_claim(_rec_h(mc3="top_1pct", genie="top_decile", pooled="top_1pct"))
    assert "independent" not in claim  # no global independence boolean
    groups = {g["members"][0]: g["relationship"] for g in claim["evidence_dependence"]["groups"]}
    assert groups == {"mc3_exome": "independent_cohort", "genie_panel": "independent_cohort"}
    # the grain comparability caveat (panel denominator != exome) is carried, per F caveat §5
    assert "not" in claim["provenance"]["independence_note"].lower()
    assert "exome" in claim["provenance"]["independence_note"].lower()
