"""genomic_claims — genomic-alteration-profile's CLAIM VECTOR + KEY SIGNALS: a verdict-INERT projection
of the alteration cards into (signal × corroboration) per orthogonal claim.

A concrete instance of the shared claim_vector_core contract. Genomic-alteration is inherently MULTI-CLASS — its whole point is
"which alteration class drives" — so the claim decomposition is by alteration class:

  SNV recurrent SNV/indel driver — driver-recurrence (pooled TCGA-MC3 + GENIE + MSK) + mutation
                                   landscape; corroboration = cross-cohort agreement.
  CN  copy-number driver         — cell-line amplification/deletion + patient-tumour focal CN;
                                   corroboration = cell-line ↔ patient agreement.
  FUS fusion driver              — recurrent fusion/rearrangement; corroboration = GENIE-SV recurrence.
  DEP alteration confers dependency — the "so what": is the target a biomarker-stratified genetic
                                   dependency (max over the 4 stratified-dependency classes — mutation /
                                   CN / fusion / amp-expr)? corroboration = mutation-drug-response
                                   (pharmacological confirmation). A WT/neutral-dependent signal is
                                   `absent` here (the ALTERATION does not confer the dependency).

FIT: like dependency + selectivity (and unlike presence), genomic's claims are cleanly SEPARABLE — a
class primary call for the signal, a distinct provenance for corroboration — so they map onto the
core's signal_fn / corroboration_fn ClaimSpec contract directly. The per-class primaries are read from
the skill's own `genomic_alteration_by_class` breakdown (single source — cannot drift from the cards).

Verdict-INERT: reads the ALREADY-computed headline; never feeds the genomic_alteration resolver. All
inputs come from `headline` (its `genomic_alteration_by_class` block + the guard-covered _HEADLINE_FIELDS
lifts); the `cards` param is accepted for contract-uniformity but unused.
"""

from __future__ import annotations

from _skills_common.claim_vector_core import (
    SIGNAL_ORD,
    ClaimSpec,
    build_claim_vector,
    build_key_signals,
    bump_corroboration,
    cap_corroboration,
    corroboration_from_arms,
    sig_ge,
)

# ── enum → tier maps (grounded in the target-contracts card summary_fields_vocabulary) ────────────
# driver_recurrence_class / pooled_driver_recurrence_class / genie_sv_recurrence_class (percentile bands)
_RECURRENCE_SIGNAL = {
    "top_1pct": "strong",
    "top_decile": "moderate",
    "mid": "weak",
    "bottom_decile": "absent",
    "data_unavailable": "unmeasured",
}
# copy_number_class / patient_copy_number_class
_CN_SIGNAL = {
    "recurrently_amplified": "moderate",
    "recurrently_deleted": "moderate",
    "mixed": "weak",
    "broadly_neutral": "absent",
    # Measured, but under the CN power floor (too few CN-covered samples to call recurrence) — a gap WITH
    # INTENT, distinct from `data_unavailable` (nobody looked → `unmeasured`). Reads as the off-scale
    # `underpowered` tier (never `absent`/passenger, never a driver). Consumed by C3's `_classify_cn`
    # (depmap_cn_distribution) + tcga `_classify` (tcga_patient_cn) below each classifier's power floor;
    # forward-declared here so C3 need not re-touch this shared file, and BYTE-INERT until an emitter ships
    # (no live fixture emits copy_number_class == "underpowered").
    "underpowered": "underpowered",
    "data_unavailable": "unmeasured",
}
_CN_FOCAL_POS = {"recurrent_focal_amplification", "recurrent_focal_deletion"}
# The patient-tumour arm's EXPLICITLY MEASURED negative. Distinct from `data_unavailable`: focal_neutral
# means GISTIC looked and found no recurrent focal event, so it CONTRADICTS a cell-line recurrent call;
# data_unavailable means nobody looked, which contradicts nothing. Kept as a set so a future
# `focal_low_level` style token joins the disagreement population by declaration, not by editing an `==`.
_CN_FOCAL_NEG = {"focal_neutral"}
# The cell-line arm's recurrent calls — the classes a measured patient-tumour negative can disagree WITH.
_CN_CELL_LINE_RECURRENT = {"recurrently_amplified", "recurrently_deleted"}
# fusion_class
_FUS_SIGNAL = {
    "recurrent_fusion_driver": "strong",
    "sporadic_fusion": "weak",
    # #983: a moderate_promiscuous fusion at a focally-amplified locus, demoted to an amplicon
    # PASSENGER by the copy-number gate (card preprocessor). A measured SV but NOT a competent
    # driver → WEAK (never absent: the rearrangement is real; never strong: it is a passenger).
    "promiscuous_amplicon_fusion": "weak",
    "no_recurrent_fusion": "absent",
    # Measured, but under the fusion power floor (too few SV-covered samples / null fusion_frequency to
    # call recurrence) — a gap WITH INTENT, distinct from `data_unavailable` (nobody looked → `unmeasured`).
    # Reads as the off-scale `underpowered` tier (never `absent`/passenger, never a driver). Consumed by
    # C3's fusion `fclass` (tcga_fusion_consensus), which kills the `recurrent_fusion_driver`-with-null-
    # frequency case by emitting this token instead; forward-declared here so C3 need not re-touch this
    # shared file, and BYTE-INERT until an emitter ships (no live fixture emits fusion_class ==
    # "underpowered").
    "underpowered": "underpowered",
    "data_unavailable": "unmeasured",
}
# splice_exon_skip_class (splice-exon-skip-landscape) — curated oncogenic exon-skip DRIVER (METex14).
# Card vocab: recurrent_splice_driver | splice_event_off_indication | no_registered_event | data_unavailable.
# A registered event OFF its curated oncogenic indication, and the common no-curated-event case, both read as a
# measured floor (`absent`) for "is this a splice-exon-skip driver HERE"; only a missing/failed read is `unmeasured`.
# (Prior map keyed a dead `no_exon_skip` class the card never emits; the real classes fell through the else-branch.)
_SPLICE_SIGNAL = {
    "recurrent_splice_driver": "strong",
    "splice_event_off_indication": "absent",
    "no_registered_event": "absent",
    "data_unavailable": "unmeasured",
}


def _spl_tier(cls):
    """Single source for the SPL signal tier. Unknown/None → `unmeasured` (a gap, per gap≠absent); a recognized
    non-driver class → its mapped floor. Shared by `_spl_signal` and `_spl_corroboration` so the two can never
    disagree on what counts as measured (the historical signal=absent / corrob=? asymmetry)."""
    return _SPLICE_SIGNAL.get(cls, "unmeasured" if cls in (None, "data_unavailable") else "absent")


# the four stratified-dependency classes → "does the ALTERATION-positive subgroup selectively depend?"
# POSITIVE (alteration-positive dependent) vs NEGATIVE (WT/neutral dependent = alteration doesn't confer)
_STRAT_SIGNAL = {
    "mutant_strongly_dependent": "strong",
    "mutant_moderately_dependent": "moderate",
    "amplified_strongly_dependent": "strong",
    "amplified_moderately_dependent": "moderate",
    "fusion_positive_strongly_dependent": "strong",
    "fusion_positive_moderately_dependent": "moderate",
    "amplified_overexpressed_strongly_dependent": "strong",
    "amplified_overexpressed_moderately_dependent": "moderate",
    # WT/neutral/negative dependent → the alteration does NOT confer the dependency
    "wt_strongly_dependent": "absent",
    "neutral_strongly_dependent": "absent",
    "fusion_negative_strongly_dependent": "absent",
    "amp_expr_negative_more_dependent": "absent",
    # measured, not stratified by the alteration
    "not_mutation_stratified": "absent",
    "not_cn_stratified": "absent",
    "not_fusion_stratified": "absent",
    "not_amp_expr_stratified": "absent",
    # underpowered = gap, NOT absent
    "insufficient_mutation_rate": "unmeasured",
    "insufficient_amplification_rate": "unmeasured",
    "insufficient_fusion_rate": "unmeasured",
    "insufficient_amp_expr_rate": "unmeasured",
    "data_unavailable": "unmeasured",
}
# mutation-drug-response.drug_response_stratification_class → DEP corroboration (pharmacology)
_DRUG_CORR = {
    "mutant_strongly_drug_sensitive": "high",
    "mutant_moderately_drug_sensitive": "moderate",
    "mutant_drug_resistant": "low",
    # NOT `moderate`: the pharmacology arm ran and found no stratification, so it neither agrees nor
    # disagrees with the genetic dependency call — the genetic arm stands alone.
    "not_drug_response_stratified": "single_arm",
    "insufficient_mutant_or_drug_data": "unmeasured",
    "no_on_target_compound": "unmeasured",
    "data_unavailable": "unmeasured",
}
_INDICATION_SCOPES = {"within_indication", "within_indication_mut_vs_pan_wt"}

_INFORMS = {
    "SNV": "recurrent SNV/indel driver — patient-selection (mutation-defined subgroup)",
    "CN": "copy-number driver — amplification/deletion biomarker",
    "FUS": "fusion driver — rearrangement-defined subgroup",
    "SPL": "splice exon-skip driver — a transcript-form driver (e.g. METex14), rearrangement-independent",
    "DEP": "alteration confers a genetic dependency — the actionability 'so what' (biomarker-stratified)",
    "ROLE": "curated driver role (OncoKB × IntOGen GoF/LoF) — a driver call independent of cohort recurrence",
}


# curated driver-role class (alteration-role card) → driver-confidence signal. Class-AGNOSTIC (it does not
# say which alteration class drives), so it is its OWN claim, not folded into SNV/CN/FUS: a curated driver
# with NO cohort recurrence would otherwise be invisible (the recurrence-keyed SNV signal reads `absent`).
_ROLE_SIGNAL = {
    "direct_driver_gof": "strong",
    "direct_driver_lof": "strong",
    "predictive_biomarker": "moderate",
    "passenger": "absent",
    "data_unavailable": "unmeasured",
}


def _role_signal(h, c):
    cls = h.get("alteration_role")
    sig = _ROLE_SIGNAL.get(cls, "unmeasured")
    fd = h.get("functional_direction")
    ev = f"curated role: {cls or 'data_unavailable'}" + (f" ({fd})" if fd else "")
    return sig, ev, None


def _role_corroboration(h, c):
    """ROLE corroboration over the curated role-call arm and the functional-direction arm.

    CONVENTION A (user decision, 2026-09-14), same change as `_spl_corroboration`: a curated `passenger`
    is a measured negative — OncoKB/IntOGen were consulted and returned a verdict — so it keeps a
    corroboration tier instead of collapsing to `unmeasured` with the genuine gap.

    The direction arm is read RELATIVE to the role side. `functional_direction` is a closed vocabulary
    (`alteration-role.card.yaml`: activating | loss_of_function | ambiguous | null), and only a
    DEFINITIVE direction is a measured arm: `ambiguous` means the IntOGen rows disagreed with each other,
    which is inconclusive rather than opposed, so it leaves the frame along with null. A definitive
    direction AGREES with a driver call and CONTRADICTS `passenger` — a curated passenger with a
    definitive activating/LoF direction is a real conflict and now reports `low`, where the old
    positive-only gate reported the whole axis as unmeasured."""
    sig = _ROLE_SIGNAL.get(h.get("alteration_role"), "unmeasured")
    if sig == "unmeasured":
        return "unmeasured"
    definitive = h.get("functional_direction") in ("activating", "loss_of_function")
    # `ambiguous`/null -> None (the arm leaves the frame); definitive -> agrees iff the role is positive.
    dir_arm = (sig != "absent") if definitive else None
    return corroboration_from_arms([True, dir_arm])


def _by_class(h):
    return (h.get("genomic_alteration_by_class") or {}) if isinstance(h, dict) else {}


def _f(v, nd=0):
    return f"{v:.{nd}f}" if isinstance(v, (int, float)) else "n/a"


# ── recurrence-class precedence: a truthy SENTINEL is not a measurement ───────────────────────────
# `pooled_driver_recurrence_class` carries the explicit string "data_unavailable" when the pooled read
# found no cohort for the indication — and "data_unavailable" is a NON-EMPTY STRING, so the natural
#     h.get("pooled_driver_recurrence_class") or h.get("driver_recurrence_class")
# short-circuits ON the sentinel and DISCARDS a measured per-indication class behind it, including a
# measured `bottom_decile` floor. Same family as `±Inf is a NUMBER`: a sentinel that satisfies the very
# guard meant to exclude it. It fails OPEN in the direction that HIDES false negatives — a measured
# "recurrence absent" is republished as "unmeasured", so a literature contradiction against it is filed
# as a coverage gap instead of a calibration miss.
#
# Derived from _RECURRENCE_SIGNAL rather than restated, so a new unavailability token added to the
# vocabulary joins this set by declaration. A class ABSENT from the map is deliberately NOT skipped: an
# unrecognised token is an unknown band, not a declared sentinel, and skipping it would silently drop a
# newly-added real band.
_UNMEASURED_RECURRENCE = frozenset(k for k, v in _RECURRENCE_SIGNAL.items() if v == "unmeasured")


def _recurrence_class(h, *fallbacks):
    """The driver-recurrence class, preferring a MEASURED read over an explicit unavailability sentinel.

    Precedence is otherwise unchanged (pooled -> per-indication -> any caller-supplied fallback). When
    every present candidate is unmeasured, returns the first present one so evidence prose still names
    `data_unavailable` rather than None.
    """
    present = [v for v in (h.get("pooled_driver_recurrence_class"), h.get("driver_recurrence_class"), *fallbacks) if v]
    for v in present:
        if v not in _UNMEASURED_RECURRENCE:
            return v
    return present[0] if present else None


# ── the four claims (signal_fn -> (tier, evidence, conflict); corroboration_fn -> tier) ───────────
def _snv_signal(h, c):
    bc = _by_class(h).get("snv_indel") or {}
    landscape = bc.get("verdict")  # mutation_landscape_class
    if landscape == "no_mutations":
        return "absent", "no SNV/indel mutations in cohort", None
    rec = _recurrence_class(h, bc.get("recurrence_class"))
    sig = _RECURRENCE_SIGNAL.get(rec, "unmeasured")
    ev = f"SNV: {landscape or 'data_unavailable'}, recurrence {rec or 'data_unavailable'}" + (
        f" ({_f((h.get('pooled_mutation_frequency') or h.get('overall_mutation_frequency') or 0) * 100, 1)}% freq)"
        if isinstance(h.get("pooled_mutation_frequency") or h.get("overall_mutation_frequency"), (int, float))
        else ""
    )
    return sig, ev, None


def _snv_corroboration(h, c):
    """SNV corroboration over the WES recurrence arm and the GENIE panel arm.

    The fix here is the ARM frame: the one-armed base was `moderate`, so a claim with GENIE
    `data_unavailable` and a single cohort read identically to one where two independent arms agreed.

    NOT gated on a measured-`absent` signal, deliberately. A `bottom_decile` recurrence class is a
    MEASURED floor ("we looked; this is not a recurrent driver"), and that negative is itself a claim two
    arms can corroborate — so it keeps a measured corroboration tier. Gating it to `unmeasured` would
    regress CASE-032, whose whole point is that a measured floor must not read as a gap on ANY of the
    five surfaces that consume the recurrence class, the corroboration surface included
    (`test_sentinel_fix_reaches_every_recurrence_surface` pins it).

    ★ THIS IS CONVENTION A, AND IT IS NOW THE FLEET CONVENTION (user decision, 2026-09-14). Until then
    this file held two opposing conventions, each argued in a comment citing the other: A here and on
    CN/FUS, versus "corroboration only exists for a positive signal" on SPL/ROLE. A won on three
    grounds: (1) collapsing a measured negative to `unmeasured` corroboration is the `gap != absent`
    invariant (claim_vector_core:16) violated one level up — the exact conflation this whole frame
    exists to prevent; (2) A is pinned by an eval case and B was pinned by nothing; (3) B's rationale
    conflates "the finding is negative" with "nobody looked", and a passenger IS a finding. SPL and
    ROLE were converted, which also forced their second arms to be read RELATIVE to the signal side —
    the correction below is what makes a negative signal safe to keep a tier."""
    rec = _recurrence_class(h)
    if _RECURRENCE_SIGNAL.get(rec, "unmeasured") == "unmeasured":
        return "unmeasured"
    cohorts = h.get("pooled_recurrence_cohorts")
    n_cohorts = len(cohorts) if isinstance(cohorts, (list, tuple)) else (cohorts if isinstance(cohorts, int) else 0)
    genie = h.get("genie_driver_recurrence_class")
    # The GENIE panel arm. AGREEMENT IS RELATIVE, so it is computed by comparing the two arms' SIDES of
    # the driver/not-a-driver split through the shared `_RECURRENCE_SIGNAL` map — never by testing the
    # panel token on its own. `genie not in ("bottom_decile",)` reads like the same thing and is not: it
    # calls a panel `bottom_decile` a disagreement even when the WES arm ALSO read `bottom_decile`, i.e.
    # it files two arms CONCORDANT on a measured negative as a sharp conflict. That is strictly worse than
    # the `moderate` default it replaced, and it is the same mistake in a second costume — an arm read in
    # isolation cannot tell agreement from disagreement, only presence from absence.
    #
    # An off-roster or unmeasured panel token leaves the frame (None) rather than defaulting to a side.
    genie_tier = _RECURRENCE_SIGNAL.get(genie) if genie is not None else None
    if genie_tier in (None, "unmeasured"):
        genie_arm = None
    else:
        # `bottom_decile` is the only NEGATIVE band; every other measured band is a positive driver call.
        genie_arm = (genie_tier != "absent") == (_RECURRENCE_SIGNAL[rec] != "absent")
    # Independent multi-cohort pooled recurrence is a genuine SECOND arm on the WES side. Fewer than two
    # cohorts is not a disagreement — there was simply no second cohort — so it leaves the frame.
    multi_cohort_arm = True if n_cohorts >= 2 else None
    return corroboration_from_arms([True, genie_arm, multi_cohort_arm])


def _cn_signal(h, c):
    bc = _by_class(h).get("copy_number") or {}
    cls = bc.get("verdict")  # copy_number_class (cell-line)
    sig = _CN_SIGNAL.get(cls, "unmeasured")
    focal = h.get("patient_focal_cn_class")
    demoted = False
    if focal in _CN_FOCAL_POS:
        # Patient-tumour focal CN is the clinically-relevant driver event and drives the signal
        # INDEPENDENTLY of the cell-line arm. HER2/CCND1 are recurrently focally amplified in patient
        # tumours but read broadly_neutral in the DepMap cell-line panel; keying the signal off the
        # cell-line arm alone (the prior `sig_ge(sig,"moderate")` gate) silently discarded the focal
        # amplification and mis-read them as CN-`absent`. Now: cell-line + patient agree -> strong;
        # patient-focal alone (cell-line neutral) -> moderate. Mirrors the tumor-presence de-differentiation
        # fix (a measured tumour-tissue positive is not vetoed by a neutral cell-line proxy).
        sig = "strong" if sig_ge(sig, "moderate") else "moderate"
    elif cls in _CN_CELL_LINE_RECURRENT and focal in _CN_FOCAL_NEG:
        # The MIRROR of the arm above, and it was missing: corroboration is bidirectional but signal was
        # one-way. `_cn_corroboration` already returns `low` for exactly this shape (cell-line recurrent,
        # patient tumour explicitly focal-neutral), while `_cn_signal` had only the elevation path — so the
        # claim kept publishing a `moderate` measured-POSITIVE CN signal for a shallow cell-line call over
        # near-diploid patient tumours (0.1-2.3% of the cohort). TC #739 retired this predicate from every
        # driver-establishing rung, but retiring it from the LADDER does not retire it from the CLAIM, which
        # is what the eval harness, the literature lane and the discordance ledger read.
        #
        # SYMMETRIC across amplification and deletion on purpose: the mechanism is direction-agnostic and
        # `_cn_corroboration` already treats both alike, so demoting only the deletion instance would
        # recreate the mirror-guard DIRECTION gap this arm exists to close. `weak` (not `absent`) mirrors
        # `_fus_signal`'s `promiscuous_amplicon_fusion` — the event is real in some lines, it just is not
        # population recurrence. Keyed on _CN_FOCAL_NEG, never on `data_unavailable`: an UNMEASURED patient
        # arm is not a contradiction, and demoting on it would punish coverage gaps as disagreement.
        sig, demoted = "weak", True
    ev = f"CN: cell-line {cls or 'data_unavailable'}, patient-focal {focal or 'data_unavailable'}"
    if demoted:
        # Name the demotion in the evidence, not just in the tier — the literature lane and the ledger
        # read this string, and "weak" alone reads as a weak measurement rather than as a disagreement.
        ev += " — cell-line-recurrent but patient tumours focal-neutral: not population recurrence"
    return sig, ev, None


def _cn_corroboration(h, c):
    """CN corroboration over the two arms — cell-line `copy_number_class` and patient-tumour
    `patient_focal_cn_class` — under the MEASURED-ARM frame.

    The unconditional trailing `return "moderate"` this replaced conflated THREE distinct states, which
    is what made eval CASE-034's DLL3/SCLC row unreadable:
      1. one-armed (patient focal `data_unavailable`/None) — nobody looked for a second arm;
      2. DIRECTION CONFLICT (cell-line amplified + patient `recurrent_focal_deletion`, or the mirror) —
         two measured arms pointing OPPOSITE ways, priced as partial agreement;
      3. `cls == "mixed"` — a measured but directionless cell-line call, which has no direction for a
         patient focal call to agree OR disagree with.

    A measured-NEGATIVE `broadly_neutral` keeps a measured corroboration tier (`single_arm`): the
    cell-line arm did look and did report no event, and that negative is a claim a second arm could
    corroborate. This is convention A — see `_snv_corroboration`, which records why it became the fleet
    convention on 2026-09-14 and which axes were converted to it.

    `patient_focal_cn_class` is a CLOSED enum, so the arms below are exhaustive by construction rather
    than by a trailing else."""
    bc = _by_class(h).get("copy_number") or {}
    cls = bc.get("verdict")
    # A GAP collapses the axis — keyed off the OFF-SCALE ordinal (None) so BOTH gap kinds qualify:
    # `data_unavailable` (nobody looked → `unmeasured`) AND `underpowered` (the CN arm looked but was
    # under-powered). A string match on `unmeasured` alone would let an `underpowered` cell arm slip past
    # and read as a MEASURED positive (`single_arm` via the arm frame below) — the gap≠measured error this
    # tier exists to prevent. Byte-identical for every existing class (all non-gap tiers are non-None).
    if SIGNAL_ORD.get(_CN_SIGNAL.get(cls, "unmeasured")) is None:
        return "unmeasured"  # a gap is neither corroborated nor contradicted

    focal = h.get("patient_focal_cn_class")
    # The patient arm: True/False if GISTIC looked, None if it did not. `data_unavailable` is a truthy
    # STRING, so it is tested against the sentinel explicitly and never by truthiness.
    if focal is None or focal == "data_unavailable":
        patient_arm = None
    elif cls == "recurrently_amplified":
        patient_arm = focal == "recurrent_focal_amplification"
    elif cls == "recurrently_deleted":
        patient_arm = focal == "recurrent_focal_deletion"
    else:
        # `mixed` and `broadly_neutral`: the cell-line arm asserts no DIRECTION (mixed) or asserts a
        # NEGATIVE (broadly_neutral), so no patient focal call can agree or disagree with it. Measured,
        # but not comparable — which is a one-armed claim, not a conflict.
        patient_arm = None
    # The cell-line arm is measured and positive by the guard above, so it always agrees with itself.
    return corroboration_from_arms([True, patient_arm])


def _fus_signal(h, c):
    bc = _by_class(h).get("fusion") or {}
    cls = bc.get("verdict")  # fusion_class
    sig = _FUS_SIGNAL.get(cls, "unmeasured")
    # #983 COPY-NUMBER GATE (upstream, card preprocessor): a moderate_promiscuous fusion at a recurrently
    # focally-AMPLIFIED locus is demoted to `promiscuous_amplicon_fusion` (an amplicon passenger, not a
    # competent driver) BEFORE rules fire — so it fires no driver rung and drops out of the multi-class
    # framing. Here it reads WEAK with an explicit rationale (a real SV, but a passenger).
    if cls == "promiscuous_amplicon_fusion":
        return (
            "weak",
            (
                "fusion: promiscuous_amplicon_fusion (copy-number-gated — a moderate_promiscuous SV "
                "at a focally-amplified locus: an amplicon passenger, not a competent fusion driver)"
            ),
            None,
        )
    # VERDICT-INERT confidence-aware downgrade: a `recurrent_fusion_driver` call flagged
    # `fusion_recurrence_confidence == moderate_promiscuous` rests on a promiscuous recurrence with NO
    # recurrent partner — the mixed bucket that also catches amplicon-artifact SVs at amplified oncogenes.
    # This fires when the copy-number co-signal is ABSENT (so the #983 preprocessor did not demote — e.g.
    # MET/LUAD, where MET amp is often below the CN-card focal threshold): downgrade strong->weak so the
    # signals-first layer + key_signals headline stop over-reading a thin/promiscuous fusion as a co-driver
    # (MET/LUAD: n=3 promiscuous, contradicted by literature). Complements the upstream CN gate (they cover
    # the amplified vs not-focally-amplified halves of the moderate_promiscuous bucket).
    if sig == "strong" and h.get("fusion_recurrence_confidence") == "moderate_promiscuous":
        return "weak", f"fusion: {cls} (low-confidence: moderate_promiscuous — no recurrent partner)", None
    return sig, f"fusion: {cls or 'data_unavailable'}", None


def _spl_signal(h, c):
    bc = _by_class(h).get("splice") or {}
    cls = bc.get("verdict")  # splice_exon_skip_class
    sig = _spl_tier(cls)
    ev = f"splice exon-skip: {cls or 'data_unavailable'}" + (f" ({bc.get('event_id')})" if bc.get("event_id") else "")
    return sig, ev, None


def _spl_corroboration(h, c):
    """SPL corroboration over the curated splice-registry arm and the live DepMap-carrier arm.

    CONVENTION A (user decision, 2026-09-14): a MEASURED NEGATIVE keeps a corroboration tier. This
    function used to collapse `absent` to `unmeasured` alongside the real gap, which is the file's own
    `gap != absent` invariant (claim_vector_core:16) violated one level up — `no_registered_event` means
    the registry WAS consulted, and that negative is a claim a second arm can agree or disagree with.
    Only an unreadable axis returns `unmeasured` now. (The old gate also listed `negative`, which
    `_SPLICE_SIGNAL` cannot emit — a dead branch, dropped with it.)

    AND SO THE CARRIER ARM MUST BE READ RELATIVE TO THE SIGNAL, exactly as in `_fus_corroboration`.
    Once a negative signal keeps a tier, "do live carriers agree" depends on which side the registry
    arm took: carriers >= 1 CONFIRMS a driver call but CONTRADICTS `no_registered_event` (DepMap sees
    carriers of an event the registry does not register). Testing `n >= 1` on its own would file that
    contradiction as `high` — the same mistake `_snv_corroboration` documents, in a third costume."""
    bc = _by_class(h).get("splice") or {}
    # Keyed off the SHARED `_spl_tier` so signal and corroboration can never disagree on what counts as
    # measured (the historical signal=absent / corrob=unmeasured asymmetry).
    tier = _spl_tier(bc.get("verdict"))
    if tier == "unmeasured":
        return "unmeasured"
    n = bc.get("n_depmap_carriers")
    # None/non-numeric = DepMap was not consulted: the arm leaves the frame rather than taking a side.
    # `n == 0` is a MEASURED read ("we looked, no carriers"), so it counts and takes the negative side.
    carrier_arm = None if not isinstance(n, (int, float)) else ((n >= 1) == (tier != "absent"))
    return corroboration_from_arms([True, carrier_arm])


def _fus_corroboration(h, c):
    """FUS corroboration over the fusion-class arm and the GENIE-SV recurrence arm.

    The old form had the defect in its LOOKUP TABLE rather than in a trailing return:
    `_RECURRENCE_SIGNAL_TO_CORR["data_unavailable"] = "moderate"` and the `.get(..., "moderate")`
    default meant an UNMEASURED GENIE-SV arm — and a missing key alike — yielded moderate corroboration.
    An absent second arm was literally tabulated as partial agreement.

    Like SNV/CN, this keeps a measured corroboration tier for a measured-`absent` fusion signal
    (`no_recurrent_fusion` = "we looked, there is no recurrent fusion"), rather than collapsing the
    negative to a gap — convention A, made fleet-wide on 2026-09-14 (see `_snv_corroboration`). SPL and
    ROLE now derive their second arm's side the same way this function does, for the same reason.

    AND THAT IS EXACTLY WHY THE PANEL ARM MUST BE READ RELATIVE TO IT. Because a measured-negative fusion
    call keeps a corroboration tier, "does the GENIE-SV arm agree" depends on which side the fusion arm
    took. Mapping the SV band straight to an agreement boolean got both ends backwards on the negative
    branch: `no_recurrent_fusion` + SV `bottom_decile` (both arms say there is no population-recurrent
    rearrangement) scored `low` as if they clashed, while `no_recurrent_fusion` + SV `top_1pct` (a real
    contradiction — the panel sees a top-percentile recurrent SV where this arm sees none) scored `high`.
    Deriving the side from `_FUS_SIGNAL` fixes both, and cannot drift from the signal tier."""
    bc = _by_class(h).get("fusion") or {}
    fus_tier = _FUS_SIGNAL.get(bc.get("verdict"), "unmeasured")
    # A GAP (off-scale ordinal) collapses the axis: `data_unavailable`→`unmeasured` AND `underpowered`
    # (the fusion arm looked but was under-powered / null fusion_frequency). Off-scale keying, not a string
    # match, so an `underpowered` fusion arm cannot read as a measured positive. Byte-identical for every
    # existing class.
    if SIGNAL_ORD.get(fus_tier) is None:
        return "unmeasured"
    genie_sv = bc.get("genie_sv_recurrence_class")
    sv_positive = _SV_BAND_IS_RECURRENT.get(genie_sv) if genie_sv is not None else None
    # None = the panel arm was not measured (or is an off-roster band): it leaves the frame either way.
    sv_arm = None if sv_positive is None else (sv_positive == (fus_tier != "absent"))
    base = corroboration_from_arms([True, sv_arm])
    if genie_sv == "mid":
        # A `mid` percentile band is a measured arm that supports only thinly, and the arms frame has no
        # "weakly agrees" rung. Capping preserves the old table's `mid -> moderate` exactly instead of
        # promoting it to `high` just because a second arm exists — the strength of an arm and the
        # NUMBER of arms are different questions, and this claim answers both. A cap only ever lowers, so
        # this cannot rescue a `mid` band that DISAGREES with the fusion arm out of `low`.
        base = cap_corroboration(base, "moderate")
    return base


# GENIE-SV recurrence percentile → is this band a POSITIVE (population-recurrent) call? A SIDE, not an
# agreement: whether it corroborates depends on which side the fusion arm took, which is why the caller
# compares the two rather than reading a boolean straight out of here. Replaces the old
# percentile→corroboration-tier table, whose `data_unavailable: "moderate"` row priced an unmeasured arm
# as partial agreement. A band absent from this map resolves to None (arm not measured) rather than to a
# default, so a NEW percentile token cannot silently inherit either a tier or a side.
_SV_BAND_IS_RECURRENT = {
    "top_1pct": True,
    "top_decile": True,
    "mid": True,
    "bottom_decile": False,  # GENIE-SV says this rearrangement is not population-recurrent
    "data_unavailable": None,  # explicit: the sentinel is a truthy STRING, never a band
}


def _resistance_actionability(h) -> str | None:
    """VERDICT-INERT clinical-actionability breadcrumb from CIViC per-variant interpretation (the
    variant-level-interpretation card, this skill's own). Summarises the THERAPY-RESISTANCE alleles
    (`civic_resistance_variants`, already lifted onto the headline) as a compact clause the DEP claim's
    rendered evidence surfaces to the narrator. Motivated by the KRAS/COADREAD benchmark: the single most
    clinically-important CRC-specific KRAS fact — that KRAS mutation is a NEGATIVE predictive biomarker for
    anti-EGFR mAbs (cetuximab/panitumumab; extended-RAS testing = standard of care) — is fully present in
    the card but was invisible to the claim_vector / key_signals / narrator (the capsule projection does
    not surface resistance_variants), so the LLM synthesis missed it. Class-generic (no hardcoded therapy /
    indication); returns None when no resistance alleles are curated (axis byte-stable — no clause added).
    This is a clinical-INTERPRETATION annotation on the target's OWN alterations, squarely within this
    skill's variant-level-interpretation card — NOT a selectivity / therapeutic-window call (owned by
    tumor-selectivity) and NOT a nomination input (the claim vector never feeds the genomic resolver)."""
    rv = h.get("civic_resistance_variants") if isinstance(h, dict) else None
    if not isinstance(rv, list) or not rv:
        return None
    therapies: dict[str, int] = {}
    n_alleles = 0
    for v in rv:
        if not isinstance(v, dict):
            continue
        n_alleles += 1
        for combo in v.get("therapies") or []:
            # a CIViC "therapies" entry can be a combination ("Panitumumab,Cetuximab"); count each agent
            for t in str(combo).split(","):
                t = t.strip()
                if t:
                    therapies[t] = therapies.get(t, 0) + 1
    if not n_alleles or not therapies:
        return None
    top = sorted(therapies, key=lambda t: (-therapies[t], t))[:3]
    return (
        f"CIViC therapy-resistance: {n_alleles} allele(s) annotated resistant to {len(therapies)} "
        f"therapies (top: {', '.join(top)}) [variant-level-interpretation]"
    )


def _dep_signal(h, c):
    bc = _by_class(h)
    fields = [
        h.get("mutation_stratification_class") or (bc.get("snv_indel") or {}).get("stratified_dependency_class"),
        h.get("cn_stratification_class") or (bc.get("copy_number") or {}).get("stratified_dependency_class"),
        h.get("amp_expr_stratification_class") or (bc.get("copy_number") or {}).get("amp_expr_dependency_class"),
        h.get("fusion_stratification_class") or (bc.get("fusion") or {}).get("stratified_dependency_class"),
    ]
    tiers = [_STRAT_SIGNAL.get(f, "unmeasured") for f in fields if f is not None]
    measured = [t for t in tiers if SIGNAL_ORD.get(t) is not None]
    # VERDICT-INERT clinical-actionability breadcrumb (CIViC therapy-resistance) folded into the DEP
    # ("actionability so what") claim's rendered evidence so the narrator surfaces it; None → no clause.
    _res = _resistance_actionability(h)
    _res_clause = f"; {_res}" if _res else ""
    if not measured:
        return "unmeasured", "no biomarker-stratified dependency measured" + _res_clause, None
    best = max(measured, key=lambda t: SIGNAL_ORD[t])
    fired = [f for f in fields if f and _STRAT_SIGNAL.get(f) == best]
    return best, f"biomarker-stratified dependency: strongest = {fired[0] if fired else best}" + _res_clause, None


def _dep_corroboration(h, c):
    """DEP corroboration over the PHARMACOLOGY arm (`drug_response_stratification_class`), graded for
    strength by `_DRUG_CORR` rather than counted by the arm frame — this is one of the bespoke
    strength-grading fns `corroboration_from_arms` defers `moderate` to.

    Note it does NOT gate on the DEP signal: unlike SPL/ROLE this reads a DIFFERENT field than the
    signal does, so there is no signal tier to be in lock-step with, and `_DRUG_CORR`'s own
    `unmeasured` entries carry the gap. (A comment here previously claimed a positive-signal gate that
    the code never had; removed rather than implemented, since convention A — see `_snv_corroboration`
    — says a measured negative keeps its tier anyway.)"""
    drug = h.get("drug_response_stratification_class")
    base = _DRUG_CORR.get(drug, "unmeasured")
    # Within-indication (not a pan-cancer extrapolation) localisation raises confidence — but `arm=False`:
    # WHERE the pharmacology arm's evidence was measured is a property OF that arm, not a second arm
    # agreeing with it. Before 2026-09-14 this took `not_drug_response_stratified` (= `single_arm`, the
    # pharmacology arm ran and found no stratification, so the genetic arm stands alone) straight to
    # `high` on a scope token — one arm reading as the top corroboration rung.
    scopes = [
        h.get("stratified_evidence_scope"),
        h.get("cn_stratified_evidence_scope"),
        h.get("fusion_stratified_evidence_scope"),
        h.get("amp_expr_stratified_evidence_scope"),
    ]
    if base in ("single_arm", "moderate", "low") and any(s in _INDICATION_SCOPES for s in scopes):
        base = bump_corroboration(base, True, arm=False)
    return base


SNV, CN, FUS, SPL, DEP, ROLE = "SNV", "CN", "FUS", "SPL", "DEP", "ROLE"


# ── citable evidence atoms (claim_vector_core atom_fn) ──────────────────────────────────────────────
# Bind each genomic axis's load-bearing VALUES to its source {card_id, fields} + entity keys, so the
# cross-evidence reasoner can cite the number (frequency, recurrence percentile, stratified effect
# size + q) by a discrete token rather than the bare class label. Verdict-inert; returns None when the
# source card is absent (axis stays byte-stable — no evidence_atom key).
from _skills_common.claim_vector_core import build_summary_atom  # shared atom builder (Group D)


def _gatom(card_id: str, summary: dict, keys: tuple, entity: dict, read) -> dict | None:
    return build_summary_atom(card_id=card_id, summary=summary, keys=keys, read=read, entity=entity)


def _snv_atom(h, c):
    cid = "mutation-hotspot-frequency"
    return _gatom(
        cid,
        c.get(cid) or {},
        (
            "driver_recurrence_class",
            "pooled_mutation_frequency",
            "overall_mutation_frequency",
            "pooled_driver_recurrence_percentile",
            "driver_recurrence_percentile",
            "n_samples_in_indication",
            "n_samples_mutated",
        ),
        {"measurement_type": "mutation_hotspot_recurrence", "grain": "target_indication"},
        _recurrence_class(h),
    )


def _cn_atom(h, c):
    cid = "copy-number-distribution"
    return _gatom(
        cid,
        c.get(cid) or {},
        (
            "copy_number_class",
            "cn_distribution_shape",
            "cn_median_panel",
            "cn_p95_panel",
            "cn_fraction_deep_deletion",
            "patient_focal_cn_class",
        ),
        {"measurement_type": "copy_number_alteration", "sample_context": "cell_line"},
        (c.get(cid) or {}).get("copy_number_class"),
    )


def _fus_atom(h, c):
    cid = "fusion-rearrangement-landscape"
    return _gatom(
        cid,
        c.get(cid) or {},
        ("fusion_class", "n_samples_with_fusion", "genie_sv_frequency", "genie_sv_recurrence_percentile"),
        {"measurement_type": "fusion_rearrangement", "grain": "target_indication"},
        (c.get(cid) or {}).get("fusion_class"),
    )


def _gdep_atom(h, c):
    cid = "mutation-stratified-dependency"
    return _gatom(
        cid,
        c.get(cid) or {},
        (
            "mutation_stratification_class",
            "delta_chronos_hotspot_mut_vs_wt",
            "median_chronos_hotspot_mutant",
            "median_chronos_hotspot_wildtype",
            "hotspot_mannwhitney_q",
            "n_hotspot_mutant",
            "n_hotspot_wildtype",
            "evidence_scope",
        ),
        {
            "measurement_type": "mutation_stratified_dependency",
            "sample_context": "cell_line",
            "stratum": "hotspot_mutant_vs_wt",
        },
        (c.get(cid) or {}).get("mutation_stratification_class"),
    )


GENOMIC_CLAIM_SPEC = [
    ClaimSpec(SNV, "recurrent SNV/indel driver", _snv_signal, _snv_corroboration, _INFORMS["SNV"], _snv_atom),
    ClaimSpec(CN, "copy-number driver", _cn_signal, _cn_corroboration, _INFORMS["CN"], _cn_atom),
    ClaimSpec(FUS, "fusion driver", _fus_signal, _fus_corroboration, _INFORMS["FUS"], _fus_atom),
    # SPLICE exon-skip driver (METex14): the verdict-driving class added to the resolver in v2.13.0 but
    # historically absent from the claim vector — so a splice_exon_skip_driver verdict had no signal-layer
    # representation (the narrator led with SNV/fusion, not the driving splice class). No atom_fn yet
    # (curated event, not a numeric anchor). Verdict-INERT.
    ClaimSpec(SPL, "splice exon-skip driver", _spl_signal, _spl_corroboration, _INFORMS["SPL"]),
    ClaimSpec(DEP, "alteration confers dependency", _dep_signal, _dep_corroboration, _INFORMS["DEP"], _gdep_atom),
    # ROLE: curated driver-role (OncoKB × IntOGen). Class-agnostic driver CONFIDENCE, independent of the
    # cohort-recurrence-keyed SNV/CN/FUS signals — captures a curated driver with no cohort recurrence
    # (previously invisible to the claim vector / atlas). No numeric anchor → no atom_fn (like SPL).
    ClaimSpec(ROLE, "curated driver role", _role_signal, _role_corroboration, _INFORMS["ROLE"]),
]

_DISCLAIMER = (
    "Verdict-INERT projection of the alteration cards into orthogonal per-class claims (SNV recurrent "
    "SNV/indel driver / CN copy-number driver / FUS fusion driver / SPL splice exon-skip driver / "
    "DEP alteration-confers-dependency / ROLE curated driver role), "
    "each signal×corroboration. Claims are NOT additive; genomic-alteration is a MIX — a strong CN does "
    "not degrade a weak SNV, and the strongest class is what drives. DEP asks whether the ALTERATION "
    "confers a genetic dependency (a WT/neutral-dependent signal is `absent` here). corroboration is a "
    "within-claim support tier, NOT the axis certainty. Never feeds the genomic_alteration verdict."
)


def genomic_claim_vector(headline: dict, cards: list) -> dict:
    """The verdict-inert claim vector {SNV,CN,FUS,SPL,DEP,ROLE: {signal, corroboration, evidence,
    conflict, informs}, _disclaimer}. Projection over the computed headline. The axis roster is
    GENOMIC_CLAIM_SPEC — never re-enumerate it by hand (this docstring and _DISCLAIMER both omitted ROLE
    for the whole window it existed, and so did the narrator lens, which made it unaskable)."""
    return build_claim_vector(GENOMIC_CLAIM_SPEC, headline, cards, _DISCLAIMER)


def genomic_key_signals(headline: dict, cards: list) -> dict:
    """A brief, direct, CITED read (deterministic; available without the LLM)."""
    vec = genomic_claim_vector(headline, cards)
    h = headline

    def sup_snv(claim):
        rec = _recurrence_class(h)
        return f"Recurrent SNV/indel driver — {rec} recurrence [mutation-hotspot-frequency]"

    def sup_cn(claim):
        bc = _by_class(h).get("copy_number") or {}
        return (
            f"Copy-number driver — {bc.get('verdict')} (patient-focal {h.get('patient_focal_cn_class')}) "
            f"[copy-number-distribution]"
        )

    def sup_fus(claim):
        return f"Fusion driver — {(_by_class(h).get('fusion') or {}).get('verdict')} [fusion-rearrangement-landscape]"

    def sup_spl(claim):
        bc = _by_class(h).get("splice") or {}
        n = bc.get("n_depmap_carriers")
        return (
            f"Splice exon-skip driver — {bc.get('verdict')} ({bc.get('event_id') or 'event'}"
            + (f", {n} DepMap carriers" if n is not None else "")
            + ") [splice-exon-skip-landscape]"
        )

    def sup_dep(claim):
        return (
            f"Alteration confers a dependency — {vec['DEP']['evidence'].split('= ')[-1]} "
            f"(drug-response {h.get('drug_response_stratification_class')}) [stratified-dependency + drug-response]"
        )

    def cav_snv(claim):
        return f"Not a recurrent SNV driver — {_recurrence_class(h)} recurrence [mutation-hotspot-frequency]"

    def cav_cn(claim):
        return f"No recurrent copy-number alteration — {(_by_class(h).get('copy_number') or {}).get('verdict')} [copy-number-distribution]"

    def cav_spl(claim):
        return "No recurrent splice exon-skip driver [splice-exon-skip-landscape]"

    def cav_dep(claim):
        return "Alteration does not confer a measured genetic dependency (WT/neutral or not-stratified) [stratified-dependency]"

    # The alteration-CLASS keys whose (moderate+) signal names a driver — now includes SPL so a
    # splice_exon_skip_driver (METex14) verdict is NAMED in the headline (was previously omitted, and a
    # spuriously-strong promiscuous fusion led the line instead — see _fus_signal downgrade + #983).
    _CLASS_KEYS = (SNV, CN, FUS, SPL)

    def head(v, supports):
        drivers = [k for k in _CLASS_KEYS if sig_ge(v[k]["signal"], "moderate")]
        names = {SNV: "SNV/indel", CN: "Copy-number", FUS: "Fusion", SPL: "Splice exon-skip"}
        if len(drivers) >= 2:
            base = "Multi-class alteration driver (" + " + ".join(names[k] for k in drivers) + ")."
        elif len(drivers) == 1:
            base = f"{names[drivers[0]]}-driven alteration."
        elif any(v[k]["signal"] == "weak" for k in _CLASS_KEYS):
            base = "Sub-threshold alteration signal (passenger-leaning)."
        elif all(v[k]["signal"] in ("absent", "unmeasured") for k in _CLASS_KEYS):
            base = "No recurrent alteration (passenger / not altered)."
        else:
            base = "Alteration profile largely unmeasured."
        if sig_ge(v[DEP]["signal"], "moderate"):
            # Respect the emitted-verdict reconciliation: when the collapsed word was demoted to
            # `biomarker_dependency_unconfirmed` (both KO-dependency confidence cards contradict the
            # claimed dependency — see run.py reconcile_genomic_verdict), the DEP claim must be surfaced
            # as an UNCONFIRMED caveat here rather than asserted as a clean biomarker-stratified
            # dependency, so this most-read summary line can't over-read the verdict.
            if h.get("genomic_alteration_profile") == "biomarker_dependency_unconfirmed":
                base = (
                    base.rstrip(".")
                    + " — biomarker dependency UNCONFIRMED (orthogonal KO-dependency evidence contradicts)."
                )
            else:
                base = base.rstrip(".") + ", biomarker-stratified dependency."
        return base

    return build_key_signals(
        vec,
        rank_keys=(SNV, CN, FUS, SPL, DEP),
        support_fns={SNV: sup_snv, CN: sup_cn, FUS: sup_fus, SPL: sup_spl, DEP: sup_dep},
        # DEP first: the decision-critical caveat for a genomic call is "the alteration is a passenger /
        # confers no dependency"; then the class drivers.
        critical_keys=(DEP, SNV, CN, FUS, SPL),
        caveat_fns={SNV: cav_snv, CN: cav_cn, FUS: cav_cn, SPL: cav_spl, DEP: cav_dep},
        headline_fn=head,
    )


__all__ = ["genomic_claim_vector", "genomic_key_signals", "GENOMIC_CLAIM_SPEC"]
