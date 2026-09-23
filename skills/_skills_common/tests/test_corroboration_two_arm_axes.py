"""Per-axis corroboration semantics for the axes that consult a GENUINE second arm.

`test_corroboration_arm_frame.py` pins the fleet-wide properties, but two of its instruments are
structurally blind to this layer, and that blindness was measured rather than assumed — a mutation
turning selectivity's `else "low"` back into `else "moderate"` survived the entire fleet suite:

  * the AST guard only flags UNCONDITIONAL pins, and correctly abstains on a rung reached through
    `if arms_agree:` — which is exactly where the two-arm axes live;
  * the empty-headline probe can never reach a two-arm branch, because with no data there are no arms.

So these axes need real inputs. They are also the only axes where `moderate`/`high` are legitimately
reachable at all, which makes them the place a regression would be least visible: the value looks
plausible because the axis genuinely can produce it.

The CN case is enumerated EXHAUSTIVELY over the closed `patient_focal_cn_class` vocabulary rather than
sampled, because the four states the old trailing `return "moderate"` conflated (one-armed, direction
conflict, directionless `mixed`, measured-negative) are distinguishable only by walking the cross
product — and eval CASE-034's DLL3/SCLC row was unreadable precisely because two of them collided.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from _skills_common import cis_coherence_claims as cis  # noqa: E402
from _skills_common import genomic_claims as gen  # noqa: E402
from _skills_common import selectivity_claims as sel  # noqa: E402
from _skills_common.claim_vector_core import CORROBORATION_ORD, SIGNAL_ORD  # noqa: E402

# The closed vocabulary from cards/copy-number-distribution.card.yaml
# → outputs.summary_fields_vocabulary.patient_focal_cn_class. Mirrored here (skills CI does not
# necessarily have the contracts checkout) and CROSS-CHECKED against the contract when it IS reachable,
# by test_patient_focal_enum_matches_the_card_contract below — so this copy cannot silently go stale.
_PATIENT_FOCAL_ENUM = (
    "recurrent_focal_amplification",
    "recurrent_focal_deletion",
    "focal_neutral",
    "data_unavailable",
    # The patient-tumour focal arm looked but was under the CN power floor (too few CN-covered patient
    # samples to call recurrence) — a gap WITH INTENT, distinct from `data_unavailable` (nobody looked).
    # Added to the card's `patient_focal_cn_class` vocabulary by contracts PR-C3 (#851); mirrored here so
    # the exhaustive table below grows the two new directional rows rather than silently shrinking.
    "underpowered",
)


def _cn_headline(cn_class, focal):
    return {
        "genomic_alteration_by_class": {"copy_number": {"verdict": cn_class}},
        "patient_focal_cn_class": focal,
    }


# (cell-line copy_number_class, patient_focal_cn_class) -> expected corroboration, with the REASON.
# Enumerated over the full cross product: 6 cell-line classes x (5 enum values + None) = 36 rows.
_CN_CASES = {
    # A GAP carries no corroboration whatever the patient arm says: there is nothing to agree or disagree
    # with. The two gap KINDS collapse the axis alike — `data_unavailable` (nobody looked) and
    # `underpowered` (the cell-line arm looked but was under-powered): both are off-scale in SIGNAL_ORD, so
    # neither is a measured arm the patient focal call could corroborate. (Before the `underpowered` tier,
    # `data_unavailable` was the only signal state that collapsed the axis.)
    **{("data_unavailable", f): "unmeasured" for f in _PATIENT_FOCAL_ENUM + (None,)},
    **{("underpowered", f): "unmeasured" for f in _PATIENT_FOCAL_ENUM + (None,)},
    # `broadly_neutral` is a measured NEGATIVE and `mixed` a measured DIRECTIONLESS call. Both are real
    # one-armed claims: the cell-line arm looked and reported something, but nothing it reported gives a
    # patient focal call anything to agree or disagree WITH. `single_arm`, not `unmeasured` — collapsing
    # them to a gap would regress CASE-032, where a measured floor reading as a gap is the whole defect.
    **{("broadly_neutral", f): "single_arm" for f in _PATIENT_FOCAL_ENUM + (None,)},
    **{("mixed", f): "single_arm" for f in _PATIENT_FOCAL_ENUM + (None,)},
    # A positive, DIRECTIONAL cell-line call: now the patient arm can actually be compared.
    ("recurrently_amplified", "recurrent_focal_amplification"): "high",  # both arms, same direction
    ("recurrently_amplified", "recurrent_focal_deletion"): "low",  # OPPOSITE directions — a conflict
    ("recurrently_amplified", "focal_neutral"): "low",  # GISTIC looked and found nothing — disagreement
    ("recurrently_amplified", "data_unavailable"): "single_arm",  # a truthy STRING sentinel, not an arm
    # The patient focal arm RAN but was under-powered: a gap on the SECOND arm, exactly like
    # `data_unavailable`/None above — the measured cell-line call stands alone. NOT a conflict: reading
    # `underpowered` as "the patient arm disagrees" would fabricate the sharp discordance the eval ledger
    # routes to a reviewer, the same gap≠contradiction error the purity/panel arms guard against.
    ("recurrently_amplified", "underpowered"): "single_arm",
    ("recurrently_amplified", None): "single_arm",  # the field was never emitted
    ("recurrently_deleted", "recurrent_focal_deletion"): "high",
    ("recurrently_deleted", "recurrent_focal_amplification"): "low",
    ("recurrently_deleted", "focal_neutral"): "low",
    ("recurrently_deleted", "data_unavailable"): "single_arm",
    ("recurrently_deleted", "underpowered"): "single_arm",  # under-powered patient arm = a gap, one-armed
    ("recurrently_deleted", None): "single_arm",
}


def test_cn_case_table_is_exhaustive_over_the_closed_enum():
    """The table is a POPULATION, not a sample: every cell-line class in `_CN_SIGNAL` crossed with every
    value of the closed patient enum plus the never-emitted `None`. Derived from the module's own signal
    map, so a NEW cell-line class fails here rather than slipping through untested."""
    expected = {(cls, f) for cls in gen._CN_SIGNAL for f in _PATIENT_FOCAL_ENUM + (None,)}
    assert set(_CN_CASES) == expected, f"missing {sorted(expected - set(_CN_CASES))}"
    assert len(_CN_CASES) == 36


@pytest.mark.parametrize(("cn_class", "focal"), sorted(_CN_CASES, key=lambda k: (k[0], str(k[1]))))
def test_cn_corroboration_over_the_full_arm_cross_product(cn_class, focal):
    got = gen._cn_corroboration(_cn_headline(cn_class, focal), {})
    assert got == _CN_CASES[(cn_class, focal)], (
        f"copy_number={cn_class!r} x patient_focal={focal!r}: expected {_CN_CASES[(cn_class, focal)]!r}, got {got!r}"
    )


def test_cn_distinguishes_a_missing_patient_arm_from_a_contradicting_one():
    """The CASE-034 read, as one assertion. These two rows used to be the SAME value (`moderate`), which
    is why the ledger could not tell a coverage gap from a cross-grain contradiction."""
    gap = gen._cn_corroboration(_cn_headline("recurrently_amplified", "data_unavailable"), {})
    conflict = gen._cn_corroboration(_cn_headline("recurrently_amplified", "recurrent_focal_deletion"), {})
    assert gap == "single_arm" and conflict == "low"
    assert CORROBORATION_ORD[gap] > CORROBORATION_ORD[conflict], "a gap must not rank below a conflict"


# (label, signal map, class -> corroboration) for every axis whose corroboration reads the SAME source
# its signal does. The negative population is DERIVED from each map, per the idiom at
# test_the_negative_side_is_derived_from_the_signal_map_not_from_a_class_LITERAL below: a listed one goes
# stale the day a vocabulary gains a second negative class, which is exactly when this matters.
# The second arm is left ABSENT in every call, isolating the question this test asks — does a measured
# negative carry a tier AT ALL — from the separate question of which side that arm takes.
_MEASURED_NEGATIVE_AXES = [
    ("SNV", lambda: gen._RECURRENCE_SIGNAL, lambda cls: _snv(cls, None)),
    ("CN", lambda: gen._CN_SIGNAL, lambda cls: gen._cn_corroboration(_cn_headline(cls, None), {})),
    ("FUS", lambda: gen._FUS_SIGNAL, lambda cls: _fus(cls, None)),
    ("SPL", lambda: gen._SPLICE_SIGNAL, lambda cls: gen._spl_corroboration(_spl_headline(cls), None)),
    ("ROLE", lambda: gen._ROLE_SIGNAL, lambda cls: gen._role_corroboration({"alteration_role": cls}, {})),
]


def _spl_headline(verdict):
    return {"genomic_alteration_by_class": {"splice": {"verdict": verdict}}}


def test_the_measured_absent_convention_is_UNIFORM_across_the_genomic_fleet():
    """CONVENTION A, adopted fleet-wide 2026-09-14. THIS TEST PREVIOUSLY PINNED THE OPPOSITE — a declared
    SPLIT — and the change of reason is the point of the rewrite, so the old frame is recorded here.

    A measured `absent` signal ("we consulted the source; there is no event") KEEPS a measured
    corroboration tier on every axis whose corroboration reads the same source its signal does. The
    negative is itself a finding, and a second arm can agree with it or contradict it. Collapsing it to
    `unmeasured` is the `gap != absent` invariant of `claim_vector_core:16` violated one level up: a
    curated passenger call and an unread registry would then render identically, and CASE-032 exists to
    stop precisely that on the five surfaces that consume the tier.

    Formerly SNV/CN/FUS/literature-context kept the tier while SPL/ROLE collapsed it. Grounds A won on:
    (1) it is the invariant the shared core already declares, so B was a local exception to a global rule;
    (2) only A had an eval case pinning it, while B was pinned by this test alone; (3) DEP, named as a
    third collapsing axis by this test's earlier docstring, was never collapsing — see the exemption
    below — so the "consistent" side had two members, not three, and the split was thinner than declared.

    DEP IS DELIBERATELY EXEMPT, and not by oversight: `_dep_corroboration` reads the PHARMACOLOGY field
    through `_DRUG_CORR` and never consults `_dep_signal` at all, so its measuredness tracks a different
    source. `_STRAT_SIGNAL` carries eight `absent` classes and none of them can move it. That is a real
    second arm, not a collapse — `mutant_drug_resistant` -> `low` shows the negative side is graded — so
    co-movement is not the property to assert there and asserting it would fail for the right reason.

    A future change that RE-SPLITS the fleet is a display-tier move across the genomic axes: land it as
    its own reviewed change and rewrite this docstring, rather than letting it arrive as a side effect."""
    measured = {r for r, o in CORROBORATION_ORD.items() if o is not None}
    seen = {}
    for label, get_map, call in _MEASURED_NEGATIVE_AXES:
        negatives = [k for k, v in get_map().items() if v == "absent"]
        assert negatives, f"{label}: no measured-negative class left in the signal map — it changed shape"
        for cls in negatives:
            got = call(cls)
            assert got in measured, (
                f"{label} class {cls!r} maps to tier `absent` in its signal map — a MEASURED finding — but "
                f"corroboration read {got!r}. A consulted source reporting no event is not a gap; that is "
                f"the convention-B collapse this axis was moved off on 2026-09-14."
            )
            seen[f"{label}:{cls}"] = got

    # …and UNIFORM means one tier, not merely five measured ones: with the second arm absent on both
    # sides of the old split, every axis must land on the SAME rung, or the split has only moved rungs.
    assert set(seen.values()) == {"single_arm"}, f"the fleet re-split across rungs: {seen}"


def _fus(verdict, sv):
    return gen._fus_corroboration(
        {"genomic_alteration_by_class": {"fusion": {"verdict": verdict, "genie_sv_recurrence_class": sv}}}, {}
    )


def _snv(rec, genie, n_cohorts=0):
    return gen._snv_corroboration(
        {
            "driver_recurrence_class": rec,
            "genie_driver_recurrence_class": genie,
            "pooled_recurrence_cohorts": n_cohorts,
        },
        {},
    )


# The MEASURED-NEGATIVE side of the two panel-arm axes, which is where reading an arm in ISOLATION goes
# wrong. Both `_snv_corroboration` and `_fus_corroboration` keep a corroboration tier when their signal is
# a measured `absent` (the CASE-032 convention pinned above) — so "does the panel arm agree?" has no
# answer until you know WHICH SIDE the primary arm took. A first cut at this change mapped the panel band
# straight to an agreement boolean, which inverted BOTH ends of the negative branch:
#   * primary negative + panel negative (the two arms CONCUR that nothing recurrent is there) -> `low`,
#     a fabricated sharp discordance of exactly the kind the eval ledger routes to a reviewer;
#   * primary negative + panel top-percentile (a REAL contradiction) -> `high`.
# It survived four rounds of mutation testing because every fixture in play asserted a POSITIVE signal,
# where absolute and relative agreement happen to coincide. Hence the table below is keyed on the primary
# arm's SIDE, and both sides are enumerated.
_PANEL_ARM_CASES = [
    # (fn, primary_class, panel_band, expected, reason)
    (_snv, "top_1pct", "top_decile", "high", "WES driver + panel driver — two arms, same side"),
    (_snv, "top_1pct", "bottom_decile", "low", "WES driver, panel says not recurrent — a real conflict"),
    (_snv, "bottom_decile", "bottom_decile", "high", "BOTH arms measured NO recurrence — concordant"),
    (_snv, "bottom_decile", "top_1pct", "low", "panel sees a driver where WES sees none — a real conflict"),
    (_snv, "top_1pct", None, "single_arm", "no panel arm"),
    (_snv, "top_1pct", "data_unavailable", "single_arm", "truthy sentinel is not a band"),
    (_snv, "top_1pct", "a_new_percentile_band", "single_arm", "off-roster band leaves the frame"),
    (_fus, "recurrent_fusion_driver", "top_1pct", "high", "fusion driver + recurrent SV"),
    (_fus, "recurrent_fusion_driver", "bottom_decile", "low", "driver call, panel says not recurrent"),
    (_fus, "no_recurrent_fusion", "bottom_decile", "high", "BOTH arms measured NO recurrent fusion"),
    (_fus, "no_recurrent_fusion", "top_1pct", "low", "panel sees a top-percentile SV where this arm sees none"),
    (_fus, "no_recurrent_fusion", "mid", "low", "still a side disagreement; the `mid` cap only LOWERS"),
    (_fus, "recurrent_fusion_driver", "mid", "moderate", "thin agreement — the preserved `mid` band"),
    (_fus, "recurrent_fusion_driver", None, "single_arm", "no panel arm"),
    (_fus, "no_recurrent_fusion", "a_new_percentile_band", "single_arm", "off-roster band leaves the frame"),
]


@pytest.mark.parametrize(
    ("fn", "primary", "band", "expected", "reason"),
    _PANEL_ARM_CASES,
    ids=[f"{c[0].__name__.strip('_')}:{c[1]}:{c[2]}" for c in _PANEL_ARM_CASES],
)
def test_panel_arm_agreement_is_relative_to_the_primary_arms_side(fn, primary, band, expected, reason):
    got = fn(primary, band)
    assert got == expected, f"{primary!r} x {band!r}: expected {expected!r} ({reason}), got {got!r}"


def test_two_concordant_negatives_outrank_a_contradiction_on_both_panel_axes():
    """The inversion, stated as the comparison that makes it unmissable. Reading the band absolutely put
    these two rows in the WRONG ORDER on both axes — concordance below contradiction."""
    for fn, negative, positive in ((_snv, "bottom_decile", "top_1pct"), (_fus, "no_recurrent_fusion", "top_1pct")):
        concordant = fn(negative, negative if fn is _snv else "bottom_decile")
        contradicted = fn(negative, positive)
        assert CORROBORATION_ORD[concordant] > CORROBORATION_ORD[contradicted], (
            f"{fn.__name__}: concordant negatives ({concordant}) must outrank a contradiction ({contradicted})"
        )


def test_the_negative_side_is_derived_from_the_signal_map_not_from_a_class_LITERAL():
    """Pins the DERIVATION, because the values alone cannot.

    A mutant replacing `fus_tier != "absent"` with `verdict != "no_recurrent_fusion"` passes every
    assertion above — the two are identical today, since `no_recurrent_fusion` is the only `absent` row in
    `_FUS_SIGNAL` (and `bottom_decile` the only one in `_RECURRENCE_SIGNAL`). It is a latent defect, not a
    harmless paraphrase: the day either vocabulary gains a SECOND negative class, the literal keeps
    treating it as a positive claim and the panel arm's agreement silently inverts on that class alone.

    So the population is read out of the module's own signal map rather than listed here, and EVERY
    negative-tier class is required to behave the same way. The coverage assertion is what keeps this
    honest when the map grows — without it, a one-element population would make the loop decorative."""
    fus_negatives = [k for k, v in gen._FUS_SIGNAL.items() if v == "absent"]
    snv_negatives = [k for k, v in gen._RECURRENCE_SIGNAL.items() if v == "absent"]
    assert fus_negatives and snv_negatives, "no measured-negative class left to test — the maps changed shape"

    for cls in fus_negatives:
        assert _fus(cls, "bottom_decile") == "high", (
            f"fusion class {cls!r} has tier `absent` in _FUS_SIGNAL, so a panel arm that ALSO reports no "
            f"recurrence agrees with it. Reading it as a positive claim (e.g. by testing the class literal "
            f"instead of its tier) inverts this row."
        )
        assert _fus(cls, "top_1pct") == "low", f"{cls!r} vs a top-percentile panel SV is a contradiction"

    for cls in snv_negatives:
        assert _snv(cls, "bottom_decile") == "high", f"recurrence class {cls!r} is a measured negative"
        assert _snv(cls, "top_1pct") == "low"

    # …and the positive side must be the MIRROR, or "relative" would just be an inverted absolute read.
    # The positive population is derived from the ORDINAL, not a literal exclusion list: a POSITIVE
    # directional class is on-scale (not a gap → not None) AND above the negative floor (> `absent`). This
    # excludes both gap kinds (`unmeasured` AND `underpowered`, both None) and the measured-negative floor
    # in one predicate — a literal `not in ("absent", "unmeasured")` silently admitted the `underpowered`
    # gap as a positive class the day that tier landed, which is exactly the map-not-literal defect this
    # whole test exists to prevent.
    for cls in (k for k, v in gen._FUS_SIGNAL.items() if SIGNAL_ORD.get(v) not in (None, SIGNAL_ORD["absent"])):
        assert _fus(cls, "top_1pct") == "high" and _fus(cls, "bottom_decile") == "low"


def test_a_SECOND_negative_class_follows_the_signal_map_not_todays_only_literal(monkeypatch):
    """The test above states the right property but CANNOT FAIL on the mutation it exists to catch, and
    that was measured rather than assumed: swapping `fus_tier != "absent"` for
    `bc.get("verdict") != "no_recurrent_fusion"` (and the SNV equivalent) survives it. The reason is that
    each map holds exactly ONE negative class today, so a loop over the real population has one iteration
    and the literal and the derivation agree on it. A one-element population cannot discriminate.

    So the population is GROWN here. A hypothetical second negative class is inserted into the module's own
    signal map (`monkeypatch.setitem`, so the real map is restored even on failure) and the same property
    is demanded of it. A literal-based implementation reads the new class as a POSITIVE claim and inverts
    both rows, which is precisely the decay this guards: correct today, wrong on the next vocabulary
    addition, and invisible until someone reads a corroboration tier that means the opposite of what it
    says. This is the `derive the check's own population` lesson with the extra step that makes it bite."""
    monkeypatch.setitem(gen._FUS_SIGNAL, "hypothetical_second_negative_fusion_class", "absent")
    assert _fus("hypothetical_second_negative_fusion_class", "bottom_decile") == "high", (
        "a class the SIGNAL MAP calls `absent` must be read as a negative claim by the corroboration fn "
        "too — so a panel arm reporting no recurrence AGREES with it. Getting `low` here means the side is "
        "being decided by a hardcoded class name instead of by `_FUS_SIGNAL`."
    )
    assert _fus("hypothetical_second_negative_fusion_class", "top_1pct") == "low"

    monkeypatch.setitem(gen._RECURRENCE_SIGNAL, "hypothetical_second_negative_recurrence_class", "absent")
    assert _snv("hypothetical_second_negative_recurrence_class", "bottom_decile") == "high"
    assert _snv("hypothetical_second_negative_recurrence_class", "top_1pct") == "low"


def test_patient_focal_enum_matches_the_card_contract():
    """The mirrored vocabulary above is CROSS-CHECKED against the contract when the checkout is present.
    Skips (loudly, by name) rather than failing when it is not — but a drift is a hard failure, because
    an enum value missing from `_PATIENT_FOCAL_ENUM` would silently shrink the exhaustive table."""
    yaml = pytest.importorskip("yaml")
    card = (
        pathlib.Path.home()
        / "rnd-computational-biology-oncology-target-contracts/cards/copy-number-distribution.card.yaml"
    )
    if not card.exists():
        pytest.skip(f"contracts checkout not present at {card}")
    vocab = (yaml.safe_load(card.read_text()).get("outputs") or {}).get("summary_fields_vocabulary") or {}
    declared = vocab.get("patient_focal_cn_class")
    assert declared, "the card no longer declares a patient_focal_cn_class vocabulary"
    assert set(declared) == set(_PATIENT_FOCAL_ENUM), (
        f"the closed enum DRIFTED: contract={sorted(declared)} vs mirrored={sorted(_PATIENT_FOCAL_ENUM)}. "
        f"Extend _PATIENT_FOCAL_ENUM and the _CN_CASES table together."
    )


# ── selectivity: two measured arms that DISAGREE are a conflict, not partial agreement ────────────

_MEASURED_INT = "malignant_subset_detected"  # any _INT_SIGNAL key that is not `unmeasured`


def _int(caf, purity, spatial=None):
    return sel._int_corroboration(
        {
            "sc_tumor_expression_class": _MEASURED_INT,
            "sc_caf_vs_malignant_class": caf,
            "purity_confound_class": purity,
            "spatial_rna_class": spatial,
        },
        {},
    )


def test_int_two_agreeing_arms_reach_high_and_disagreeing_arms_are_low():
    assert _int("malignant_dominant", "tumor_intrinsic") == "high"
    assert _int("caf_dominant", "tumor_intrinsic") == "low", "a stroma-dominant arm contradicts"
    assert _int("malignant_dominant", "microenvironment_confounded") == "low", "purity arm contradicts"


def test_int_an_absent_purity_arm_is_not_a_disagreeing_one():
    """The distinction the first draft of this change got WRONG, in the direction the whole change is
    supposed to correct.

    `purity in ("tumor_intrinsic", "purity_independent")` is False in two unrelated situations: the
    purity read CONTRADICTS the single-cell call, and the field was never emitted at all. Replacing the
    old trailing `else "moderate"` with `else "low"` fixed the first and broke the second — an
    UNMEASURED confound arm was scored as a contradiction, dragging a clean sc+CAF agreement from `high`
    down to `low`. That is the mirror image of the original defect and strictly worse, because `low` is
    what the eval ledger reads as a SHARP discordance: it would have manufactured conflicts out of the
    coverage gaps this change exists to make visible.

    So an absent purity arm LEAVES THE FRAME, and the two arms that did report still reach `high`."""
    assert _int("malignant_dominant", None) == "high", "field never emitted → 2 agreeing arms remain"
    assert _int("malignant_dominant", "data_unavailable") == "high", "truthy sentinel is not a reading"
    assert _int("malignant_dominant", "some_new_vocabulary_token") == "high", "off-roster = unaskable"
    # …and dropping BOTH corroborating arms falls to the one-armed rung rather than to a conflict.
    assert _int(None, None) == "single_arm"


def test_int_spatial_is_a_third_independent_arm():
    """The spatial arm is independent (deconvolution-free), so it moves corroboration, never the signal.
    It is now a PEER in the frame rather than a bump/cap on a base: an agreeing spatial arm and an
    agreeing purity arm are the same kind of support and must not be priced differently."""
    assert _int("malignant_dominant", "tumor_intrinsic", "tumour_enriched_rna") == "high"
    assert _int("malignant_dominant", "tumor_intrinsic", "tme_enriched_rna") == "low", "one arm dissents"
    assert _int("malignant_dominant", "tumor_intrinsic", None) == "high", "absent spatial arm is a no-op"
    # Spatial alone can carry the second arm when the deconvolution arms are silent — the substitutability
    # that makes it a peer rather than a modifier.
    assert _int(None, None, "tumour_enriched_rna") == "high"
    assert _int(None, None, "tme_enriched_rna") == "low"


def test_safe_a_fired_window_veto_alone_is_one_armed():
    """The residual one-armed `moderate` the AST guard could not see, because it sits inside the
    sc-normal-absent branch: a fired window veto IS a measured normal-side refutation, but it is the
    ONLY arm — there is no sc-normal read for it to agree with."""
    veto_only = {
        "sc_normal_safety_essential_class": "data_unavailable",
        "therapeutic_window_class": "no_therapeutic_window",
    }
    assert sel._safe_corroboration(veto_only, {}) == "single_arm"
    assert sel._safe_corroboration({"sc_normal_safety_essential_class": "data_unavailable"}, {}) == "unmeasured"


def test_safe_two_normal_side_reads_agree_or_conflict():
    def f(ess, expr, veto=False):
        h = {"sc_normal_safety_essential_class": ess, "sc_normal_expression_class": expr}
        if veto:
            h["full_normal_window_class"] = "no_full_normal_window"
        return sel._safe_corroboration(h, {})

    assert f("critical_organ_liability", "HIGH_LIABILITY") == "high", "both arms flag a liability"
    assert f("none", "LOW_LIABILITY") == "high", "both arms agree there is NO liability"
    assert f("critical_organ_liability", "LOW_LIABILITY") == "low", "the two arms DISAGREE"
    assert f("none", "HIGH_LIABILITY") == "low"
    assert f("critical_organ_liability", "LOW_LIABILITY", veto=True) == "high", "veto + liability agree"


# ── cis-coherence: the cross-grain patient boolean ───────────────────────────────────────────────


def test_cis_patient_arm_separates_absent_from_disagreeing():
    """`_patient_corr`'s three outcomes must stay three. A missing patient arm reading `moderate` was the
    original defect; reading `low` would be the over-correction that files coverage gaps as conflicts."""
    fn = cis._patient_corr("some-card", "fld", {"measured": "moderate"}, "agrees")
    cards = {"some-card": {"fld": "measured"}}
    assert fn({"agrees": True}, cards) == "high"
    assert fn({"agrees": False}, cards) == "low"
    assert fn({}, cards) == "single_arm", "no patient arm read at all — the cell-line call stands alone"
    assert fn({"agrees": True}, {}) == "unmeasured", "a gap on the FIRST arm outranks the second"


def test_every_two_arm_axis_can_actually_reach_the_top_of_the_ladder():
    """ANTI-VACUITY for this file's premise: these axes are the ones where `high` is REACHABLE. If none
    of them could reach it, the fixtures above would be pinning dead branches — the exact failure the
    repo's `test_ruler_is_not_vacuous` exists for."""
    reached = {
        "genomic:CN": gen._cn_corroboration(_cn_headline("recurrently_amplified", "recurrent_focal_amplification"), {}),
        "selectivity:INT": _int("malignant_dominant", "tumor_intrinsic"),
        "selectivity:SAFE": sel._safe_corroboration(
            {"sc_normal_safety_essential_class": "none", "sc_normal_expression_class": "LOW_LIABILITY"}, {}
        ),
        "cis:patient": cis._patient_corr("c", "f", {"m": "moderate"}, "a")({"a": True}, {"c": {"f": "m"}}),
    }
    assert all(v == "high" for v in reached.values()), f"an axis cannot reach `high`: {reached}"
    # …and every one of them can also report the one-armed rung, so neither branch is dead.
    assert gen._cn_corroboration(_cn_headline("recurrently_amplified", None), {}) == "single_arm"
