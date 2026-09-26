"""selectivity_claims — tumor-selectivity's CLAIM VECTOR + KEY SIGNALS: a verdict-INERT projection of
the selectivity cards into (signal × corroboration) per orthogonal claim.

A concrete instance of the shared claim_vector_core contract. Declares tumor-selectivity's four axes as a ClaimSpec list:

  WIN  tumor-vs-normal window   — the core selectivity signal (tumor-vs-origin DESeq2 class + effect
                                  size); corroboration = fraction of normal comparators agreeing.
  DIST distributional separation — per-sample tumor-vs-normal percentile crossing; corroboration =
                                  tumor/normal distribution overlap (low overlap = clean separation).
  INT  tumor-cell-intrinsic     — is the selective signal malignant-cell-intrinsic or stroma/purity-
                                  confounded? (single-cell malignant detection + CAF/purity); a
                                  microenvironment-driven signal is a FALSE window (→ `negative`).
  SAFE normal-tissue window     — the therapeutic-window liability / veto instrument: a clean normal
                                  side supports selectivity (strong), a critical-organ normal expression
                                  refutes it (`negative`, the veto). SAFETY VERDICT is owned by
                                  on-target-safety-liability; this is window FRAMING, not a safety call.

FIT: unlike presence's entangled A/B/C/D, selectivity's claims are cleanly SEPARABLE (signal from a
class field, corroboration from a distinct provenance number), so they map onto the core's
signal_fn / corroboration_fn ClaimSpec contract directly.

Verdict-INERT: reads the ALREADY-computed _headline; never feeds the selectivity resolver or the
normal-breadth veto. The CEACAM5/TACSTD2 offline replay guard freezes selectivity_class byte-stable.
All inputs are read from `headline` (populated by run.py::_headline via card_summary/get_card_field);
the `cards` param is accepted for contract-uniformity but unused here.
"""

from __future__ import annotations

import math

from _skills_common.claim_vector_core import (
    ClaimSpec,
    arm_from_class,
    build_claim_vector,
    build_key_signals,
    cap_corroboration,
    corroboration_from_arms,
    sig_ge,
)

# ── enum → tier maps (grounded in the target-contracts card summary_fields_vocabulary) ────────────
# tumor-vs-normal-selectivity.selectivity_class (raw pre-veto tumor-vs-origin class)
_WIN_SIGNAL = {
    "strong_tumor_selective": "strong",
    "modest_tumor_selective": "moderate",
    "field_effect_tumor_selective": "weak",  # selective vs DISTANT normal, not adjacent → weak window
    "selective_but_broadly_normal": "weak",  # selective signal but broad normal → window liability
    "discordant_across_comparators": "weak",
    "not_selective": "absent",  # a MEASURED negative
    "not_informative": "unmeasured",
    "data_unavailable": "unmeasured",
}
# tumor-vs-normal-percentile-crossing.selectivity_class
_DIST_SIGNAL = {
    "strongly_tumor_enriched": "strong",
    "enriched_subset": "moderate",
    "minimally_enriched": "weak",
    "not_enriched": "absent",
    "data_unavailable": "unmeasured",
}
# tumor-scrna-celltype-expression.sc_expression_class (tumor side)
_INT_SIGNAL = {
    "malignant_broadly_detected": "strong",
    "malignant_subset_detected": "moderate",
    "microenvironment_dominant": "negative",  # signal is stroma-driven → a FALSE selectivity window
    "broadly_low": "absent",
    "data_unavailable": "unmeasured",
}
# sc-normal-celltype-expression.sc_normal_safety_essential_class — INVERSE-liability: a clean normal
# side is a STRONG selectivity-window signal; a critical-organ liability is a NEGATIVE (the veto).
_SAFE_SIGNAL = {
    "none": "strong",
    "origin_tissue_liability": "weak",
    "critical_organ_liability": "negative",
    "data_unavailable": "unmeasured",
}

_INFORMS = {
    "WIN": "tumor-vs-normal window — the core selectivity signal (therapeutic index)",
    "DIST": "distributional separation — per-sample, patient-level selectivity",
    "INT": "tumor-cell-intrinsic — informs tumor-cell-targeted modalities (ADC/TCE/CAR); a stroma-driven signal is a false window",
    "SAFE": "normal-tissue window — the therapeutic-window liability (veto instrument); the safety VERDICT is owned by on-target-safety-liability",
}


def _f(v, nd=2):
    return f"{v:.{nd}f}" if isinstance(v, (int, float)) else "n/a"


# ── multi-platform corroboration of the tumor-vs-normal WINDOW (verdict-inert helpers) ─────────────
# selectivity's most dangerous false positive is an RNA "window" that no other platform sees. Two extra
# lanes the collapsed axis-A class hides: (1) the PROTEIN layer (CPTAC TMT + TPHP DIA-MS tumor-vs-normal),
# and (2) the per-comparator ADJACENT-vs-DISTANT split. Both are already in the headline; these fold them
# into the WIN axis so the claim vector (which the narrator LEADS with) is quorum-aware, not RNA-only.
_PROTEIN_CORROBORATED = "rna_protein_concordant"
_PROTEIN_CONTRADICTED = "rna_protein_discordant"
# LOCAL, never emitted: the token an off-indication TPHP row is relabelled to inside the quorum. It
# matches NEITHER voting constant above, which is the whole point — the arm keeps its place in the
# denominator while losing both votes. Not a card enum value; nothing outside this module sees it.
_PROTEIN_OFF_INDICATION = "protein_off_indication_cohort"


def _protein_window_quorum(h, c) -> dict:
    """Quorum over the TWO independent tumor-vs-normal PROTEIN platforms (CPTAC TMT-MS +
    TPHP DIA-MS): does the protein layer corroborate the RNA window? Returns {status, n_measured, cap,
    note}. status ∈ {corroborated, mixed, not_corroborated, contradicted, unmeasured}. `cap` is the
    corroboration ceiling a non-corroborating protein layer imposes (None = no cap). Verdict-INERT —
    reads the two rna_protein_tvn_concordance_* projections the headline already carries, plus the TPHP
    card's OWN two censoring fields off `c` (the same card-summary channel _field_effect_note uses).

    ★ THIS QUORUM ONLY EVER PENALISES, SO DROPPING AN ARM IS THE PERMISSIVE DIRECTION. The
    `not_corroborated` cap is `"low" if n >= 2 else "moderate"` — an ABSOLUTE count — so shrinking n
    RELAXES it (measured on a 22-pair panel: collapsing the TPHP arm moved 5 tiers, 5/5 UPWARD). The two
    guards below are therefore split by whether the arm is EVIDENCE AT ALL, which is the only principled
    way to carry a censoring finding into a penalty instrument without it becoming a back-door relaxation:
      * a PAN-CANCER-EXTREMUM row is not this indication's answer, so it loses BOTH votes — but it is
        LABELLED, NOT DROPPED. It stays in the denominator, because "this platform was asked and did not
        corroborate THIS indication's window" is TRUE of it. Dropping it instead was measured over the
        225-cell input space and RELAXED 30 cells while tightening 0 — a penalty instrument that fires
        LESS the less trustworthy its input, the same defect as a safety gate that drops an organ
        instead of labelling it ([[feedback_safety_support_gate_must_label_not_drop]]).
      * a CENSORED row IS evidence of non-corroboration but NOT of direction, so it keeps its place and
        its corroboration vote and loses only its vote on the `contradicted` branch. This one DOES
        relax, and that is the fix: a `low` cap resting only on a direction the card calls unreliable
        was never supported. It is the card's own instruction, not a convenience.
    Both fire only on a POSITIVE mismatch. Both fields are null only on the card's data_unavailable
    path, where the arm is already `protein_unmeasured` and excluded anyway — so a null cannot reach
    these guards in live data, and a fixture that omits them keeps the pre-existing behaviour."""
    tphp = c.get("tumor-vs-normal-protein-abundance-tphp") or {}
    cptac_read = h.get("rna_protein_tvn_concordance")
    tphp_read = h.get("rna_protein_tvn_concordance_tphp")
    # Guard 1 — the CARD'S OWN predicate (warning tphp_tvn_pan_cancer_extremum): a cohort_pick_basis
    # other than `indication_mapped` means the row is the pan-cancer argmax over |log2fc|, "a
    # most-extreme-cohort readout, NOT an indication-scoped answer ... Do not attribute it to
    # {indication.label}". Such a row can neither corroborate nor contradict THIS indication's window.
    basis = tphp.get("cohort_pick_basis")
    tphp_measured = bool(tphp_read) and tphp_read != "protein_unmeasured"
    off_indication = tphp_measured and basis is not None and basis != "indication_mapped"
    # Guard 2 — the CARD'S OWN predicate (warning tphp_tvn_detection_incomplete): a false
    # protein_detection_complete means protein_effect_size is a median over DETECTED samples only,
    # "confounded by missing-not-at-random censoring, biased toward tumor-DOWN (3.60:1 down:up vs
    # 1.50:1 on complete rows). Read the DIRECTION as unreliable, not as loss." A down-biased arm inside
    # an instrument that can only penalise is a systematically pessimistic vote: on the 22-pair panel
    # 8/12 measured TPHP arms were incomplete, the quorum lowered the WIN tier on 6 of those 8, and ALL
    # 3 TPHP discordant calls sat on censored rows — one (MKI67/LUAD) contradicting CPTAC, which read
    # `concordant` on complete data. Two reads of one measurement cannot have opposite signs.
    censored = tphp.get("protein_detection_complete") is False
    # (read, direction_trustworthy) per SURVIVING arm. CPTAC carries no censoring fields of its own, so
    # its direction is taken as given — that asymmetry is in the DATA, not in how we treat the arms.
    arms = [(cptac_read, True)] if cptac_read and cptac_read != "protein_unmeasured" else []
    if tphp_measured:
        # Relabelled, not removed: `_PROTEIN_OFF_INDICATION` matches neither voting constant, so the arm
        # counts toward `n` and toward NOTHING else. `off_indication` implies `tphp_measured`, so the
        # `n == 0` branch below can never be reached with a dropped arm — nothing goes silent there.
        arms.append((_PROTEIN_OFF_INDICATION if off_indication else tphp_read, not (off_indication or censored)))
    n = len(arms)
    if n == 0:
        return {"status": "unmeasured", "n_measured": 0, "cap": None, "note": None}
    n_conc = sum(r == _PROTEIN_CORROBORATED for r, _ in arms)
    n_disc = sum(r == _PROTEIN_CONTRADICTED and trusted for r, trusted in arms)
    n_discounted = sum(r == _PROTEIN_CONTRADICTED and not trusted for r, trusted in arms)
    plat = "platform" if n == 1 else "platforms"
    # SAY it when a vote is withheld: either withholding can move the tier by two rungs, and a discount
    # nobody can see is how a deferral becomes invisible. These two are mutually exclusive by
    # construction (an off-indication arm is relabelled before `censored` could matter to it).
    aside = ""
    if n_discounted:
        aside += (
            f"; {n_discounted}/{n} MS {plat} read tumor-vs-normal protein DOWN on a CENSORED row "
            "(protein_detection_complete=false) — direction discounted, NOT counted as a contradiction"
        )
    if off_indication:
        aside += (
            f"; the TPHP arm counts as NON-corroborating only — cohort_pick_basis={basis} makes it a "
            "pan-cancer extremum, so neither its agreement nor its direction is attributable here"
        )
    if n_disc:
        note = f"protein layer CONTRADICTS the RNA window (tumor-vs-normal protein down; {n_disc}/{n} MS {plat})"
        return {"status": "contradicted", "n_measured": n, "cap": "low", "note": note + aside}
    if n_conc == n:  # every SURVIVING platform confirms
        return {"status": "corroborated", "n_measured": n, "cap": None, "note": aside.lstrip("; ") or None}
    if n_conc:  # some confirm, some silent
        note = f"protein corroboration MIXED — {n_conc}/{n} MS {plat} confirm the RNA window"
        return {"status": "mixed", "n_measured": n, "cap": "moderate", "note": note + aside}
    # all SURVIVING platforms non-significant
    note = f"protein layer does NOT corroborate the RNA window (not significant on {n} MS {plat})"
    cap = "low" if n >= 2 else "moderate"
    return {"status": "not_corroborated", "n_measured": n, "cap": cap, "note": note + aside}


def _field_effect_note(c) -> str | None:
    """Split the collapsed multi-comparator class into its ADJACENT-vs-DISTANT signature from the
    per-cell log2FCs the aggregate class hides. Normal tissue-of-origin is often ALREADY high (the
    EPCAM/CEACAM epithelial-marker archetype), so tumor-vs-ADJACENT (cell A) reads flat/down while
    tumor-vs-DISTANT GTEx (cell C) reads up — a HIGH-NORMAL-BASELINE FIELD EFFECT: a genuine but NARROW
    window, NOT noise. Verdict-INERT; None when the per-cell fields are absent (synthetic/older summaries)."""
    s = c.get("tumor-vs-normal-selectivity") or {}
    a, cc = s.get("log2fc_cell_a"), s.get("log2fc_cell_c")
    if not isinstance(a, (int, float)) or not isinstance(cc, (int, float)):
        return None
    if a <= 0.5 and cc >= 1.0 and (cc - a) >= 1.0:
        return (
            f"high-normal-baseline field effect: tumor≈adjacent-normal (log2FC {a:.1f}) "
            f"but tumor>distant-normal (log2FC {cc:.1f})"
        )
    return None


# ── the four claims (signal_fn -> (tier, evidence, conflict); corroboration_fn -> tier) ───────────
def _win_signal(h, c):
    cls = h.get("axis_a_selectivity_class")
    sig = _WIN_SIGNAL.get(cls, "unmeasured")
    conflict = None
    if h.get("discordant") or cls == "discordant_across_comparators":
        conflict = "normal comparators DISAGREE on the tumor-vs-normal direction"
    elif cls == "selective_but_broadly_normal":
        conflict = "selective vs origin but broadly expressed in normal — therapeutic-window liability"
    ev = (
        f"tumor-vs-normal: {cls or 'data_unavailable'}, max|log2FC|={_f(h.get('max_abs_log2fc'), 1)}, "
        f"{h.get('cells_supporting')}/{h.get('cells_ran')} comparators"
    )
    # Adjacent-vs-distant field-effect signature (surfaces the per-comparator split the class collapses).
    fe = _field_effect_note(c)
    if fe:
        ev += f"; {fe}"
        conflict = f"{conflict} ({fe})" if conflict else fe
    # PROTEIN-layer corroboration quorum (CPTAC + TPHP): an RNA window the protein layer fails to
    # corroborate (or contradicts) is a weaker window — surface it as a WIN conflict. The tier cap is
    # applied in _win_corroboration. Verdict-INERT.
    pq = _protein_window_quorum(h, c)
    if pq["note"]:
        conflict = f"{conflict}; {pq['note']}" if conflict else pq["note"]
    return sig, ev, conflict


def _win_corroboration(h, c):
    cs, cr = h.get("cells_supporting"), h.get("cells_ran")
    if not isinstance(cr, (int, float)) or not cr:
        return "unmeasured"
    frac = (cs or 0) / cr
    # `cells_supporting/cells_ran` counts CELLS, not independent arms — and the comment below already
    # says cells A and B are two votes of the SAME comparison. So the fraction grades one comparator
    # family's strength; the genuine cross-arm question is `comparator_concordance`, handled just below.
    # A fully-corroborating multi-family read is what earns `high`, via the concordance branch.
    base = "high" if frac >= 0.8 and cr >= 3 and h.get("comparator_concordance") == "concordant" else "single_arm"
    # cells_supporting counts cells A (TCGA-adjacent raw) and B (its ComBat re-run) as TWO votes of the
    # SAME tumor-vs-adjacent comparison, so a 3/3 support count can rest on a SINGLE independent
    # comparator family with the GTEx family (cell C) silent. Cap the WIN corroboration by the GENUINE
    # cross-comparator agreement (comparator_concordance: adjacent family vs GTEx family) so an
    # adjacent-only call cannot read "high" as if 3 independent comparators concurred. Verdict-INERT
    # (corroboration tier only; selectivity_class + the resolver — which never key on this — untouched).
    conc = h.get("comparator_concordance")
    if conc == "discordant":
        base = cap_corroboration(base, "low")  # the two families disagree
    # `single_comparator` deliberately gets NO cap of its own. It names exactly ONE independent
    # comparator family, which is why `base` above is already `single_arm` — the `high` rung requires
    # `concordant`. The old `cap(base, "moderate")` here read like a guard but could not bind: the
    # one-armed rung sits BELOW `moderate` on the ladder, so the cap was a no-op on the only value it
    # could ever see. Keeping it would leave a decorative guard whose reason no longer describes the
    # behaviour; the arm count is now stated where it is computed, one line up.
    if h.get("discordant"):
        base = cap_corroboration(base, "low")  # disagreeing comparators cap corroboration
    # PROTEIN-layer quorum: an independent proteomic platform that FAILS to corroborate (or CONTRADICTS)
    # the RNA tumor-vs-normal window caps the WIN corroboration (2 non-corroborating platforms → low;
    # 1 → moderate; a significant OPPOSITE direction → low). A fully corroborating protein layer imposes
    # no cap (agreement is not inflated here — the RNA comparator agreement already carries the positive
    # case). This closes the gap where WIN corroboration was RNA-comparator-only and blind to the two
    # tumor-vs-normal protein cards the headline already computes. Verdict-INERT.
    pq = _protein_window_quorum(h, c)
    if pq["cap"]:
        base = cap_corroboration(base, pq["cap"])
    return base


def _dist_signal(h, c):
    cls = h.get("percentile_crossing_class")
    fa = h.get("fraction_tumor_above_normal_p95")
    ev = f"per-sample crossing: {cls or 'data_unavailable'}" + (
        f", {_f((fa or 0) * 100, 0)}% of tumours > normal p95" if isinstance(fa, (int, float)) else ""
    )
    return _DIST_SIGNAL.get(cls, "unmeasured"), ev, None


def _dist_corroboration(h, c):
    if _DIST_SIGNAL.get(h.get("percentile_crossing_class"), "unmeasured") == "unmeasured":
        return "unmeasured"
    ov = h.get("distribution_overlap_tumor_normal")
    if not isinstance(ov, (int, float)):
        return "single_arm"
    # ONE arm (the tumour-vs-normal distribution). Overlap grades that arm's SEPARATION — a signal
    # property — so it cannot buy cross-source agreement. A wide overlap is a weak measurement, not a
    # disagreement between arms, which is why the old `low` was wrong twice over: it both over-claimed
    # (`high` from one arm) and mislabelled thinness as conflict.
    return "single_arm"


def _purity_underpowered(h) -> bool:
    """AM#736 honest power qualifier: a `purity_independent` call resting on a NARROW high-purity band
    (paired-purity IQR < MIN_PURITY_IQR) is underpowered to resolve a confound at all, so it must
    ABSTAIN rather than reassure. The method emits `purity_spread_underpowered` as an advisory bool
    beside the (unchanged) class; a genuine wide-spread `purity_independent` leaves it false and reads
    exactly as before. Only qualifies `purity_independent` — a positive `microenvironment_confounded`
    detection is not weakened by spread, and other classes carry no purity reassurance to withdraw."""
    return h.get("purity_confound_class") == "purity_independent" and bool(h.get("purity_spread_underpowered"))


def _int_signal(h, c):
    cls = h.get("sc_tumor_expression_class")
    sig = _INT_SIGNAL.get(cls, "unmeasured")
    purity = h.get("purity_confound_class")
    conflict = None
    if purity == "microenvironment_confounded":
        conflict = "bulk selectivity may be microenvironment-confounded (purity) — the signal is not clearly tumor-cell-intrinsic"
        if sig_ge(sig, "moderate"):
            sig = "weak"  # purity contradicts an apparent intrinsic single-cell signal → downgrade
    elif _purity_underpowered(h) and sig_ge(sig, "moderate"):
        # AM#736: an underpowered-narrow-purity `purity_independent` is ABSENCE of a confound signal,
        # not evidence AGAINST one. Do NOT downgrade the single-cell signal (no confound was measured —
        # a downgrade would be conservative-to-a-fault), but do NOT let it silently read as a confirmed
        # clean intrinsic call either: flag the caveat so a moderate+ signal is not treated as clean.
        conflict = (
            "purity_independent rests on a narrow high-purity band (underpowered to resolve a confound) "
            "— the intrinsic single-cell signal is not confirmed purity-independent"
        )
    ev = (
        f"single-cell: {cls or 'data_unavailable'}, malignant frac {_f(h.get('sc_malignant_detection_fraction'))}, "
        f"CAF={h.get('sc_caf_vs_malignant_class')}, purity={purity}"
        f"{' (narrow-purity band, underpowered)' if _purity_underpowered(h) else ''}"
    )
    # In-situ SPATIAL region-RNA is a deconvolution-free read of the SAME malignant-compartment question.
    # Surface it in the evidence, and flag a conflict when it DISAGREES with an apparent intrinsic signal.
    spatial = h.get("spatial_rna_class")
    if spatial and spatial != "data_unavailable":
        ev += f", in-situ spatial={spatial}"
        if spatial == "tme_enriched_rna" and sig_ge(sig, "moderate"):
            conflict = conflict or (
                "in-situ spatial RNA is TME-enriched — the malignant-compartment attribution is not confirmed spatially"
            )
    return sig, ev, conflict


def _int_corroboration(h, c):
    if _INT_SIGNAL.get(h.get("sc_tumor_expression_class"), "unmeasured") == "unmeasured":
        return "unmeasured"
    # Three CORROBORATING arms over the same malignant-compartment attribution, scored on the shared
    # arm frame rather than by hand. `True` leads because the sc-tumour expression read is itself the
    # first arm — the claim being corroborated, which trivially agrees with itself.
    #
    # QUORUM: in-situ spatial region-RNA is an INDEPENDENT, deconvolution-free arm, so it enters the
    # frame as a peer rather than as a bump/cap on a base — an agreeing spatial arm and an agreeing
    # purity arm are the same KIND of support and should not be priced differently.
    #
    # Every arm distinguishes ABSENT from DISAGREEING (`arm_from_class` → None vs False). The prior
    # version conflated them: `purity in (...)` is False both when the purity read contradicts the
    # sc call and when the field was never emitted, so an UNMEASURED confound arm was scored as a
    # contradiction and dragged a clean two-arm agreement down to `low`. Verdict-INERT throughout.
    arms = (
        True,
        arm_from_class(
            h.get("sc_caf_vs_malignant_class"),
            agrees={"malignant_dominant", "caf_low"},
            disagrees={"caf_dominant"},
        ),
        arm_from_class(
            # AM#736: an underpowered-narrow-purity `purity_independent` cannot corroborate — treat it as
            # ABSENT (None), not AGREEING, mirroring the absent-vs-disagreeing discipline above. Passing
            # None here (rather than the class) drops the arm from the frame instead of scoring it as a
            # clean agreeing arm. A wide-spread `purity_independent` (flag false) still corroborates.
            None if _purity_underpowered(h) else h.get("purity_confound_class"),
            agrees={"tumor_intrinsic", "purity_independent"},
            disagrees={"microenvironment_confounded"},
        ),
        arm_from_class(
            h.get("spatial_rna_class"),
            agrees={"tumour_enriched_rna"},
            disagrees={"tme_enriched_rna"},
        ),
    )
    return corroboration_from_arms(arms)


# The modality-therapeutic-window KILL arms: tumor BELOW the worst critical/full normal (the
# housekeeping GAPDH / TROP2 broadly-normal surface archetype). Each fires a normal-breadth veto that
# the resolver clamp downgrades to selective_but_broadly_normal — a normal-side REFUTATION of any
# therapeutic window. The SAFE claim axis must not contradict that KILL by reading `strong` off a clean
# sc-normal side (the B1-02 bug), so a fired window arm floors the SAFE signal at `negative`.
def _window_veto_fired(h) -> bool:
    return (
        h.get("therapeutic_window_class") == "no_therapeutic_window"
        or h.get("full_normal_window_class") == "no_full_normal_window"
    )


def _safe_signal(h, c):
    cls = h.get("sc_normal_safety_essential_class")
    sig = _SAFE_SIGNAL.get(cls, "unmeasured")
    conflict = (
        "critical-organ normal expression — therapeutic-window veto (safety verdict owned by "
        "on-target-safety-liability)"
        if cls == "critical_organ_liability"
        else None
    )
    # Normal-breadth WINDOW veto (modality-therapeutic-window): no therapeutic window vs the worst
    # critical/full normal is a normal-side refutation of the whole window. SAFE cannot read a positive
    # signal against a resolved KILL, so floor it at `negative`. Read from the headline, which the
    # tumor-selectivity _headline now populates via the modality-therapeutic-window fetch.
    if _window_veto_fired(h):
        sig = "negative"
        conflict = conflict or (
            "no therapeutic window vs the worst critical/full normal — "
            "normal-breadth window veto (the housekeeping / broadly-normal KILL)"
        )
    # 4th normal-breadth arm (quantitative normal-PROTEIN abundance, TPHP DIA-MS): a broad_and_abundant
    # normal-protein read is a MEASURED normal-side liability the single-cell-RNA side can miss, so the SAFE
    # claim must not read a clean signal against it — floor at `negative` (a strong liability, same tier as
    # critical_organ_liability). This is the SELECTIVITY-PRESERVING arm (selectivity_veto
    # _TPHP_NORMAL_PROTEIN_VETO_RULE → selective_with_normal_liability), NOT the housekeeping KILL, so it
    # carries its own named-liability note rather than the window-veto KILL text. Read from cards_by_id
    # (the class is not in the headline). Was invisible to the SAFE claim (_window_veto_fired ignored it).
    if (c.get("normal-tissue-protein-abundance-tphp") or {}).get(
        "tphp_normal_protein_liability_class"
    ) == "broad_and_abundant" and sig != "negative":
        sig = "negative"
        conflict = conflict or (
            "broad + abundant normal-tissue protein (TPHP DIA-MS) — a named "
            "normal-protein liability the single-cell-RNA side can miss "
            "(selectivity-preserving; safety verdict owned by on-target-safety-liability)"
        )
    ev = (
        f"normal-tissue: {cls or 'data_unavailable'}, sc_normal={h.get('sc_normal_expression_class')}, "
        f"{h.get('sc_normal_n_cell_types_above_20pct')} normal cell-types >20%"
        + (f", therapeutic_window={h.get('therapeutic_window_class')}" if h.get("therapeutic_window_class") else "")
    )
    return sig, ev, conflict


def _safe_corroboration(h, c):
    ess = h.get("sc_normal_safety_essential_class")
    window_veto = _window_veto_fired(h)
    if _SAFE_SIGNAL.get(ess, "unmeasured") == "unmeasured":
        # The sc-normal read is absent, but a fired window veto is itself a measured normal-side
        # refutation — so this is MEASURED, by exactly ONE arm. It used to return `moderate`, which
        # asserted partial agreement between the veto and an sc-normal read that was never taken.
        return "single_arm" if window_veto else "unmeasured"
    # the two independent normal-side reads (essential-cell class + expression-liability class) agree?
    liab = ess in ("critical_organ_liability", "origin_tissue_liability")
    expr_liab = h.get("sc_normal_expression_class") in ("HIGH_LIABILITY", "MODERATE_LIABILITY")
    base = "high" if liab == expr_liab else "low"  # two measured normal-side reads that DISAGREE
    # a fired window veto + an sc-normal liability both point at a normal-tissue problem → they agree.
    if window_veto and liab:
        base = "high"
    return base


# ── citable evidence atoms (claim_vector_core atom_fn) ──────────────────────────────────────────────
# Bind each selectivity axis's load-bearing VALUES to its source {card_id, fields} + entity, so the
# cross-evidence reasoner can cite the number (effect size + comparator support, distributional
# separation + overlap, malignant fraction, normal-tissue breadth) rather than the bare class label.
# Read from the SOURCE card summaries (cards_by_id) for correct per-card citation; verdict-inert;
# returns None when the source card is absent (axis stays byte-stable — no evidence_atom key).
from _skills_common.claim_vector_core import build_summary_atom  # shared atom builder (Group D)


def _satom(card_id: str, summary: dict, keys: tuple, entity: dict, read) -> dict | None:
    return build_summary_atom(card_id=card_id, summary=summary, keys=keys, read=read, entity=entity)


def _win_atom(h, c):
    cid = "tumor-vs-normal-selectivity"
    return _satom(
        cid,
        c.get(cid) or {},
        (
            "selectivity_class",
            "max_abs_log2fc",
            "cells_supporting",
            "cells_ran",
            "comparator_concordance",
            "dominant_direction",
        ),
        {"measurement_type": "tumor_vs_normal_selectivity", "sample_context": "tumor"},
        (c.get(cid) or {}).get("selectivity_class"),
    )


def _dist_atom(h, c):
    cid = "tumor-vs-normal-percentile-crossing"
    return _satom(
        cid,
        c.get(cid) or {},
        (
            "selectivity_class",
            "fraction_tumor_above_normal_p95",
            "distribution_overlap_tumor_normal",
            "n_tumor_samples",
            "n_normal_samples",
        ),
        {"measurement_type": "tumor_vs_normal_percentile_crossing", "sample_context": "tumor"},
        (c.get(cid) or {}).get("selectivity_class"),
    )


def _int_atom(h, c):
    cid = "tumor-scrna-celltype-expression"
    return _satom(
        cid,
        c.get(cid) or {},
        (
            "sc_expression_class",
            "malignant_detection_fraction",
            "caf_vs_malignant_class",
            "top_microenvironment_compartment",
            "malignant_n_donors",
        ),
        {"measurement_type": "sc_tumor_celltype_expression", "sample_context": "tumor", "grain": "single_cell"},
        (c.get(cid) or {}).get("sc_expression_class"),
    )


def _safe_atom(h, c):
    cid = "sc-normal-celltype-expression"
    return _satom(
        cid,
        c.get(cid) or {},
        (
            "sc_normal_safety_essential_class",
            "sc_normal_expression_class",
            "n_cell_types_above_20pct",
            "max_detection_fraction",
        ),
        {"measurement_type": "sc_normal_celltype_expression", "sample_context": "normal", "grain": "single_cell"},
        (c.get(cid) or {}).get("sc_normal_safety_essential_class"),
    )


SELECTIVITY_CLAIM_SPEC = [
    ClaimSpec("WIN", "tumor-vs-normal window", _win_signal, _win_corroboration, _INFORMS["WIN"], _win_atom),
    ClaimSpec("DIST", "distributional separation", _dist_signal, _dist_corroboration, _INFORMS["DIST"], _dist_atom),
    ClaimSpec("INT", "tumor-cell-intrinsic", _int_signal, _int_corroboration, _INFORMS["INT"], _int_atom),
    ClaimSpec("SAFE", "normal-tissue window", _safe_signal, _safe_corroboration, _INFORMS["SAFE"], _safe_atom),
]

_DISCLAIMER = (
    "Verdict-INERT projection of the selectivity cards into orthogonal claims (WIN tumor-vs-normal "
    "window / DIST distributional separation / INT tumor-cell-intrinsic / SAFE normal-tissue window), "
    "each signal×corroboration. Claims are NOT additive; a weak WIN does not degrade a strong INT. "
    "SAFE is therapeutic-window FRAMING — the safety verdict is owned by on-target-safety-liability. "
    "corroboration is a within-claim support tier, NOT the axis certainty. Never feeds the "
    "selectivity_class or the normal-breadth veto."
)


# ── L2b-5 CROSS-SOURCE integration claim: selectivity_concordance ─────────────────────────────────
# The tumor-vs-normal SELECTIVITY WINDOW resolved from >=2 TRULY INDEPENDENT sources, conforming to
# docs/EVIDENCE_PROPERTY_ENVELOPE_v0.md (the coverage/essentiality/safety/abundance/recurrence family).
# Independent arms (the definitional pair): the BULK-RNA window (recount3 TCGA/GTEx tumor-vs-normal
# DESeq2, `tumor-vs-normal-selectivity`) x the PROTEIN-MS window (CPTAC TMT-MS tumor-vs-normal,
# `tumor-protein-abundance-cptac`). These are independent MOLECULAR LAYERS (transcript vs MS-protein),
# independent cohorts, independent assays. TPHP DIA-MS (`tumor-vs-normal-protein-abundance-tphp`) is a
# SAME-MODALITY partial-cohort-overlap sibling of CPTAC (NOT an independent third arm — two protein-MS
# platforms are ONE protein arm), so it is a declared DEPENDENT WITHIN-GROUP source: preserved as
# evidence (resolved_source_count), never a corroborating independent arm. This is the #1667/#1673/#1674
# arm-commensurability lesson made structural: a same-modality sibling cannot buy an extra independent
# arm for the protein layer. Verdict-INERT (no `signal` key, feeds no rule/veto/resolver rung); the token
# `selectivity_concordance` is read NOWHERE on the selectivity spine (selectivity_veto keys on the
# verdict token + fired rule-ids; risk_projection keys on sv.get("selectivity"); the resolver keys on
# card summary fields). Key OMITTED (byte-stable) when NEITHER independent arm resolves.

# selectivity-window token maps for the two INDEPENDENT arms (each read from its OWN source, never a
# pre-collapsed relational token — the rna_protein_tvn_concordance headline field bakes in the RNA
# direction and is therefore NOT an independent protein call).
_RNA_WINDOW_UP = {  # a tumor-enriched RNA window (any axis-A selective-ish class)
    "strong_tumor_selective",
    "modest_tumor_selective",
    "field_effect_tumor_selective",
    "selective_but_broadly_normal",
}
_RNA_WINDOW_ABSENT = {  # RNA resolved a MEASURED non-selective / internally-discordant read (no clean window)
    "not_selective",
    "discordant_across_comparators",
}
_RNA_WINDOW_UNRESOLVED = {None, "not_informative", "data_unavailable"}


def _fin(v):
    """Demote a NON-FINITE numeric anchor (NaN/±Inf) to None before it enters retained_quantitative:
    ±Inf/NaN are NUMBERS that pass isinstance/isna-style guards and would leak into claim_vectors (the
    emission-invariants non-finite rule). MS-protein effect sizes / q-values are the realistic source of
    a NaN here. A legitimate None stays None; a finite value passes through unchanged (verdict-inert)."""
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _rna_window_call(cls):
    """The bulk-RNA arm's OWN tumor-vs-normal window call. Returns (resolved: bool, has_window: bool|None).
    has_window = True iff RNA resolves a tumor-enriched window; False on a measured non-selective /
    comparator-discordant read; None when unresolved (coverage gap)."""
    if cls in _RNA_WINDOW_UNRESOLVED:
        return False, None
    if cls in _RNA_WINDOW_UP:
        return True, True
    return True, False  # _RNA_WINDOW_ABSENT (or any other measured class): resolved, no clean window


def _protein_window_call(effect, q):
    """A protein-MS arm's OWN tumor-vs-normal window call (mirrors run.py::_rna_protein_tvn_concordance's
    protein logic, applied to the platform's OWN effect/q — not the RNA-relative token). Returns
    (resolved: bool, has_window: bool|None). Unresolved when no protein value (unmeasured); a measured but
    BH q>=0.05 read is a resolved no-window; q<0.05 up = window, q<0.05 down = resolved no-window (an
    anti-selective protein direction is not a tumor-selective window)."""
    if effect is None or effect != effect:  # None or NaN → protein_unmeasured
        return False, None
    if q is None or q != q or q >= 0.05:  # measured but not significant → resolved no-window
        return True, False
    return True, effect > 0  # significant: up = window, down = resolved no-window


def _selectivity_concordance_claim(h: dict) -> "dict | None":
    """L2b-5 CROSS-SOURCE integration claim: `selectivity_concordance` — the tumor-vs-normal selectivity
    WINDOW integrated from >=2 INDEPENDENT sources (docs/EVIDENCE_PROPERTY_ENVELOPE_v0.md), a foreign
    (expression/proteomics) family for the M3 growth ladder.

    Integrates the two INDEPENDENT arms — BULK-RNA window (`axis_a_selectivity_class`) x PROTEIN-MS
    window (CPTAC `protein_tumor_vs_normal_effect_size`/`_q_value`) — by an EXPLICIT DETERMINISTIC rule
    (no LLM; L2b is reproducible by contract), emitting one of:
      * selectivity_window_concordant     — both INDEPENDENT arms resolve and AGREE (both a tumor-enriched
        window, or both a measured no-window floor); the agreed direction is carried, never collapsed;
      * protein_masks_selectivity_window  — RNA resolves a tumor-enriched window but the PROTEIN-MS layer
        does NOT corroborate it (the dangerous RNA-only false positive: transcript up / protein flat|down);
      * rna_masks_selectivity_window      — the mirror: protein sees a window RNA does not;
      * single_source_only                — exactly ONE independent arm (RNA, or the protein layer)
        resolves — a degraded read that names the resolved layer (recoverable), NOT a concordance claim.

    DEPENDENCE (the slot this family exercises MORE than recurrence): the protein arm is one INDEPENDENT
    arm supplied by a MULTI-MEMBER group `{cptac_tmt, tphp_dia}`. CPTAC TMT-MS is the primary; TPHP DIA-MS
    (`protein_tumor_vs_normal_tphp_*`) is a SAME-MODALITY partial-cohort-overlap sibling — `resolved: yes`,
    `quality_eligible: yes` (it may supply the protein arm's value when CPTAC is a gap), but
    `corroboration_eligible: NO`: two protein-MS platforms are ONE protein arm, never a third independent
    replication. It is preserved in `source_support` and counted in `resolved_source_count` (evidence),
    but NEVER in `corroborating_independent_arm_count` and NEVER resurrects an independent arm beyond the
    protein layer. This is the #1667/#1673/#1674 arm-commensurability lesson made structural.

    Corroboration is on the shared MEASURED-ARM frame over the two INDEPENDENT arms only (RNA + protein):
    two agreeing arms -> high, a disagreement -> low, one measured arm -> single_arm. A single-arm
    mutation only DEGRADES to `single_source_only`; ERASING the claim (key omitted, byte-stable) takes
    defeating BOTH independent arms — and the protein arm survives on EITHER protein-MS source, so
    defeating the protein layer means defeating BOTH CPTAC and TPHP.

    GRAIN is first-class here because the arms DIFFER in grain (assay-modality: bulk-RNA transcript vs
    MS-protein) — carried per-source in `source_support` and in `provenance.independence_note`: a
    transcript-level window need not manifest at the protein layer (post-transcriptional regulation), so a
    discordance is a real biological signal, not necessarily measurement error.

    PRESENTATION-SUPPORT (L2b->L3, mirrors coverage/abundance/recurrence): two-directional structured
    `positive_signal` (always) / `qualifying_signal` (NULL when concordant) + a deterministic
    `boundary_sensitive` flag. These route NOTHING.

    VERDICT-INERT: carries NO `signal` key, reads no verdict, feeds no rule/veto. Returns None — key
    omitted, byte-stable — when NEITHER independent arm resolves."""
    rna_cls = h.get("axis_a_selectivity_class")
    cptac_eff = h.get("protein_tumor_vs_normal_effect_size")
    cptac_q = h.get("protein_tumor_vs_normal_q_value")
    tphp_eff = h.get("protein_tumor_vs_normal_tphp_effect_size")
    tphp_q = h.get("protein_tumor_vs_normal_tphp_q_value")

    rna_res, rna_win = _rna_window_call(rna_cls)
    cptac_res, cptac_win = _protein_window_call(cptac_eff, cptac_q)
    tphp_res, tphp_win = _protein_window_call(tphp_eff, tphp_q)

    # The PROTEIN arm = one independent arm vs RNA, supplied by the protein-MS group. CPTAC is the
    # primary; TPHP (a same-modality dependent sibling) may supply the arm's value when CPTAC is a gap,
    # but adding TPHP NEVER makes a second independent arm — the arm count stays 1 for the protein layer.
    if cptac_res:
        prot_res, prot_win, prot_src = True, cptac_win, "cptac_tmt"
    elif tphp_res:
        prot_res, prot_win, prot_src = True, tphp_win, "tphp_dia"
    else:
        prot_res, prot_win, prot_src = False, None, None

    # Emit iff >=1 INDEPENDENT arm resolves (RNA or the protein layer).
    resolved_indep = [
        (name, win) for name, win, res in (("rna_bulk", rna_win, rna_res), ("protein_ms", prot_win, prot_res)) if res
    ]
    if not resolved_indep:
        return None  # neither independent arm resolves → key omitted (byte-stable)

    if len(resolved_indep) == 1:
        concordance = "single_source_only"
    elif rna_win == prot_win:
        concordance = "selectivity_window_concordant"
    elif rna_win:  # RNA sees a window, protein does not
        concordance = "protein_masks_selectivity_window"
    else:  # protein sees a window, RNA does not
        concordance = "rna_masks_selectivity_window"

    # Corroboration over the two INDEPENDENT arms ONLY. A disagreement points the arms opposite
    # ([True, False] → low); a concordance both agree ([True, True] → high); one arm unresolved leaves the
    # measured arm unopposed ([True, None] → single_arm).
    if concordance in ("protein_masks_selectivity_window", "rna_masks_selectivity_window"):
        rna_arm, prot_arm = True, False
    else:
        rna_arm = True if rna_res else None
        prot_arm = True if prot_res else None
    corroboration = corroboration_from_arms([rna_arm, prot_arm])

    # ── the envelope's TWO COUNTS ──────────────────────────────────────────────────────────────────
    corroborating_independent_arm_count = len(resolved_indep)  # RNA + protein layer only, max 2
    # resolved_source_count counts ALL THREE sources — RNA + CPTAC + TPHP — so the "TPHP is evidence, not
    # a third independent arm" fact is legible in the gap between the two counts (max 3 vs max 2).
    resolved_source_count = (1 if rna_res else 0) + (1 if cptac_res else 0) + (1 if tphp_res else 0)

    _label = {"rna_bulk": rna_cls, "cptac_tmt": None, "tphp_dia": None}
    _label["cptac_tmt"] = "protein_unmeasured" if not cptac_res else ("tumor_up" if cptac_win else "no_window")
    _label["tphp_dia"] = "protein_unmeasured" if not tphp_res else ("tumor_up" if tphp_win else "no_window")
    _label["rna_bulk"] = rna_cls or "data_unavailable"
    _win = {"rna_bulk": rna_win, "cptac_tmt": cptac_win, "tphp_dia": tphp_win}
    _cohort = {
        "rna_bulk": "recount3 TCGA/GTEx bulk-RNA (DESeq2 tumor-vs-normal)",
        "cptac_tmt": "CPTAC TMT-MS tumor-vs-normal protein",
        "tphp_dia": "TPHP DIA-MS tumor-vs-normal protein",
    }
    _grain = {"rna_bulk": "bulk_rna_transcript", "cptac_tmt": "ms_protein", "tphp_dia": "ms_protein"}
    _field = {
        "rna_bulk": "axis_a_selectivity_class",
        "cptac_tmt": "protein_tumor_vs_normal_effect_size",
        "tphp_dia": "protein_tumor_vs_normal_tphp_effect_size",
    }
    _quant = {
        "rna_bulk": {"max_abs_log2fc": _fin(h.get("max_abs_log2fc"))},
        "cptac_tmt": {
            "protein_tumor_vs_normal_effect_size": _fin(cptac_eff),
            "protein_tumor_vs_normal_q_value": _fin(cptac_q),
        },
        "tphp_dia": {
            "protein_tumor_vs_normal_tphp_effect_size": _fin(tphp_eff),
            "protein_tumor_vs_normal_tphp_q_value": _fin(tphp_q),
        },
    }
    _res = {"rna_bulk": rna_res, "cptac_tmt": cptac_res, "tphp_dia": tphp_res}

    def _support(source, group, corroboration_eligible):
        r = _res[source]
        return {
            "source": source,
            "dependence_group": group,
            "grain": _grain[source],  # FIRST-CLASS: the arms DIFFER in grain (bulk-RNA vs MS-protein)
            "value": _label[source],
            "has_window": _win[source],
            # THREE separate source notions — no single overloaded boolean smuggles two meanings.
            "resolved": r,
            "quality_eligible": r,  # a resolved read is usable evidence (may supply its group's arm value)
            "corroboration_eligible": corroboration_eligible,  # eligible to count as INDEPENDENT replication?
            "provenance": {"headline_field": _field[source], "cohort": _cohort[source]},
            "retained_quantitative": _quant[source],
        }

    # Both independent arms ALWAYS appear (the definitional concordance pair — an absent arm shows as
    # resolved:False, keeping the two-count / dependence structure legible). TPHP appears ONLY when it
    # resolves, as the worked same-modality dependent-sibling case.
    source_support = [
        _support("rna_bulk", "rna_bulk", corroboration_eligible=True),
        _support("cptac_tmt", "protein_ms", corroboration_eligible=True),
    ]
    if tphp_res:
        source_support.append(_support("tphp_dia", "protein_ms", corroboration_eligible=False))
    evidence_dependence = {
        "groups": [
            {"members": ["rna_bulk"], "relationship": "independent_modality"},
            {
                "members": ["cptac_tmt"] + (["tphp_dia"] if tphp_res else []),
                "relationship": "same_modality_partial_overlap",
                "note": (
                    "CPTAC TMT-MS and TPHP DIA-MS are BOTH tumor-vs-normal protein-MS platforms with "
                    "partially overlapping cohorts — ONE independent protein arm, NOT two. TPHP is "
                    "corroboration-ineligible (it cannot buy a third independent arm); it may supply the "
                    "protein arm's value as evidence (dependent != ignore)."
                ),
            },
        ],
        "derived_sources": {},
    }

    # which-arm payload — the disagreement or the degraded single arm is NAMED, never collapsed/averaged.
    if concordance in ("protein_masks_selectivity_window", "rna_masks_selectivity_window"):
        win_arm = "rna_bulk" if rna_win else "protein_ms"
        no_arm = "protein_ms" if win_arm == "rna_bulk" else "rna_bulk"
        concordance_support = {"window_in": win_arm, "no_window_in": no_arm}
    elif concordance == "single_source_only":
        name, win = resolved_indep[0]
        concordance_support = {
            "resolved_by": name,
            "resolved_call": rna_cls if name == "rna_bulk" else _label[prot_src],
            "resolved_via_source": "rna_bulk" if name == "rna_bulk" else prot_src,
            "resolved_has_window": win,
        }
    else:
        concordance_support = {"agreed_direction": "tumor_selective_window" if rna_win else "no_selective_window"}

    _PHRASE = {
        "selectivity_window_concordant": "AGREE on the tumor-vs-normal window call",
        "protein_masks_selectivity_window": "DISAGREE — bulk-RNA sees a window, the protein-MS layer does NOT (RNA-only window)",
        "rna_masks_selectivity_window": "DISAGREE — the protein-MS layer sees a window, bulk-RNA does NOT",
        "single_source_only": "only one independent modality arm resolves",
    }
    _ARM_NAME = {"rna_bulk": "bulk-RNA (recount3 TCGA/GTEx)", "protein_ms": "protein-MS (CPTAC TMT-MS)"}

    # ── PRESENTATION-SUPPORT fields (L2b->L3) — surface-consumption, NOT verdict-routing ─────────────
    boundary_sensitive = corroboration != "high"
    if concordance == "selectivity_window_concordant":
        _dir_text = "a tumor-enriched window" if rna_win else "NO tumor-selective window"
        positive_signal = {
            "statement": (
                f"Both INDEPENDENT modalities AGREE on {_dir_text} (bulk-RNA {rna_cls} x "
                f"CPTAC protein {_label['cptac_tmt']}) — a cross-modality-corroborated read."
            ),
            "source": "rna_bulk",
            "provenance_ref": "rna_bulk",
        }
        qualifying_signal = None
    elif concordance in ("protein_masks_selectivity_window", "rna_masks_selectivity_window"):
        win_arm = concordance_support["window_in"]
        no_arm = concordance_support["no_window_in"]
        positive_signal = {
            "statement": f"{_ARM_NAME[win_arm]} reports a tumor-vs-normal window — a selective signal in this modality.",
            "source": win_arm,
            "provenance_ref": win_arm,
        }
        qualifying_signal = {
            "statement": (
                f"{_ARM_NAME[no_arm]} does NOT corroborate the window — the modalities DISAGREE. A "
                "transcript-level window need not manifest at the protein layer (post-transcriptional "
                "regulation); an RNA-only window is the selectivity false-positive this cross-source check exists to surface."
            ),
            "source": no_arm,
            "provenance_ref": no_arm,
        }
    else:  # single_source_only
        name = concordance_support["resolved_by"]
        gap = "protein_ms" if name == "rna_bulk" else "rna_bulk"
        positive_signal = {
            "statement": (
                f"{_ARM_NAME[name]} reports {'a tumor-vs-normal window' if concordance_support['resolved_has_window'] else 'no tumor-selective window'} "
                f"({concordance_support['resolved_call']}) — the sole independent modality arm that resolves."
            ),
            "source": name,
            "provenance_ref": name,
        }
        qualifying_signal = {
            "statement": (
                f"Only {_ARM_NAME[name]} resolves; {_ARM_NAME[gap]} is a gap (unresolved) — a degraded "
                "single-modality read, NOT cross-source corroboration."
            ),
            "source": gap,
            "provenance_ref": gap,
        }

    return {
        "concordance_class": concordance,
        "corroboration": corroboration,
        "integration_method": "explicit_deterministic",
        "grain": "tumor_vs_normal_window (cross-modality: bulk-RNA transcript x MS-protein)",
        "resolved_source_count": resolved_source_count,
        "corroborating_independent_arm_count": corroborating_independent_arm_count,
        "concordance_support": concordance_support,
        "source_support": source_support,
        "positive_signal": positive_signal,
        "qualifying_signal": qualifying_signal,
        "boundary_sensitive": boundary_sensitive,
        "boundary_note": (
            "concordance class rests on a single measured modality arm (single_arm / low corroboration) — "
            "treat as near-boundary, not a flat cross-modality assertion"
            if boundary_sensitive
            else "concordance corroborated by BOTH independent modality arms agreeing"
        ),
        "evidence_dependence": evidence_dependence,
        "informs": (
            "cross-source tumor-vs-normal selectivity-window concordance — a window two INDEPENDENT "
            "molecular layers (bulk-RNA recount3 TCGA/GTEx + MS-protein CPTAC TMT) agree on is far more "
            "credible than an RNA-only window; TPHP DIA-MS is a same-modality sibling preserved as "
            "evidence but never double-counted as a third independent arm"
        ),
        "evidence": (
            f"bulk-RNA {rna_cls or 'data_unavailable'} x protein-MS {_label['cptac_tmt']}: " + _PHRASE[concordance]
        ),
        "provenance": {
            "sources": source_support,
            "independence_note": (
                "Bulk-RNA (recount3 TCGA/GTEx DESeq2 tumor-vs-normal) and CPTAC TMT-MS protein are "
                "genuinely INDEPENDENT molecular layers, cohorts and assays, so their agreement is real "
                "cross-source corroboration. TPHP DIA-MS is a SAME-MODALITY partial-cohort-overlap sibling "
                "of CPTAC (two protein-MS platforms are ONE protein arm), so it is corroboration-ineligible "
                "— never an independent third arm. GRAIN CAVEAT: the arms differ in grain (transcript vs "
                "MS-protein); a transcript-level window need not manifest at the protein layer "
                "(post-transcriptional regulation), so a discordance is a real biological signal, not "
                "necessarily measurement error."
            ),
        },
        "_disclaimer": (
            "L2b CROSS-SOURCE integration claim (deterministic, no LLM) — verdict-INERT provenance: never "
            "a signal tier, never averaged into a claim, never feeds the selectivity_class, the "
            "normal-breadth veto, or risk_projection."
        ),
    }


def selectivity_claim_vector(headline: dict, cards: list) -> dict:
    """The verdict-inert claim vector {WIN,DIST,INT,SAFE: {signal, corroboration, evidence, conflict,
    informs}, _disclaimer}. Projection over the computed headline."""
    vec = build_claim_vector(SELECTIVITY_CLAIM_SPEC, headline, cards, _DISCLAIMER)
    # L2b-5 cross-source integration claim (SK#1752): bulk-RNA x protein-MS tumor-vs-normal window
    # concordance. Carries NO `signal` key → not a chip, not a tier; OMITTED (byte-stable) unless >=1
    # independent modality arm resolves. Reads only ALREADY-READ headline window/protein fields, so it
    # perturbs no census aperture and no verdict. Mirrors the presence/dependency/safety/genomic L2b
    # concordance pattern.
    _sc = _selectivity_concordance_claim(headline)
    if _sc is not None:
        vec["selectivity_concordance"] = _sc
    return vec


def selectivity_key_signals(headline: dict, cards: list) -> dict:
    """A brief, direct, CITED read (deterministic; available without the LLM)."""
    vec = selectivity_claim_vector(headline, cards)
    h = headline

    def sup_win(claim):
        return (
            f"Tumor-selective vs normal — {h.get('axis_a_selectivity_class')} "
            f"(max|log2FC| {_f(h.get('max_abs_log2fc'), 1)}, {h.get('cells_supporting')}/{h.get('cells_ran')} comparators) "
            f"[tumor-vs-normal-selectivity]"
        )

    def sup_dist(claim):
        return (
            f"Distributionally separated — {_f((h.get('fraction_tumor_above_normal_p95') or 0) * 100, 0)}% of tumours "
            f"> normal p95 (overlap {_f(h.get('distribution_overlap_tumor_normal'))}) [percentile-crossing]"
        )

    def sup_int(claim):
        return (
            f"Tumor-cell-intrinsic — {_f((h.get('sc_malignant_detection_fraction') or 0) * 100, 0)}% of malignant cells, "
            f"{h.get('sc_caf_vs_malignant_class')} (purity {h.get('purity_confound_class')}) [single-cell + purity]"
        )

    def cav_win(claim):
        return (
            f"Weak tumor-vs-adjacent window — {h.get('axis_a_selectivity_class')} "
            f"({h.get('cells_supporting')}/{h.get('cells_ran')} comparators agree) [tumor-vs-normal-selectivity]"
        )

    def cav_dist(claim):
        return f"Poor distributional separation — {h.get('percentile_crossing_class')} [percentile-crossing]"

    def cav_int(claim):
        if h.get("purity_confound_class") == "microenvironment_confounded":
            return "Selectivity may be microenvironment-driven, not tumor-cell-intrinsic [single-cell + purity]"
        return f"Weak tumor-cell-intrinsic signal — {h.get('sc_tumor_expression_class')} [single-cell]"

    def cav_safe(claim):
        return (
            f"Normal-tissue expression → therapeutic-window liability — {h.get('sc_normal_safety_essential_class')} "
            f"(sc_normal {h.get('sc_normal_expression_class')}) [sc-normal comparators]"
        )

    def head(v, supports):
        win, dist, intr, safe = (v["WIN"]["signal"], v["DIST"]["signal"], v["INT"]["signal"], v["SAFE"]["signal"])
        # A normal-tissue liability (SAFE negative) is only a "Selective signal, but …" headline when a
        # selective signal ACTUALLY exists (WIN or DIST >= moderate). Without this gate the SAFE-negative
        # branch fired FIRST unconditionally, so measured-negative / discordant targets whose only
        # "signal" was the normal-side liability were mislabeled "Selective signal, but …". A critical-
        # organ normal liability is near-universal (GAPDH/KRAS/PECAM1/VWF all trip
        # sc_normal_safety_essential_class == critical_organ_liability), so the bug fired broadly — the
        # key_signals headline contradicted BOTH the resolved selectivity_class (e.g. not_selective) and
        # its sibling headline_block. Verdict-INERT: only this human-facing summary string changes; the
        # selectivity_class spine + normal-breadth veto are untouched. Selective cases (WIN/DIST >=
        # moderate, incl. the CEACAM5 field-effect fixture whose DIST is strong) keep the prior wording
        # byte-for-byte — only the non-selective SAFE-negative cases are corrected.
        has_selective = sig_ge(win, "moderate") or sig_ge(dist, "moderate")
        if safe == "negative" and has_selective:
            base = "Selective signal, but a critical-organ normal-tissue liability."
        elif sig_ge(win, "strong") or (sig_ge(dist, "strong") and sig_ge(intr, "moderate")):
            base = "Tumor-selective."
        elif sig_ge(win, "moderate") or sig_ge(dist, "moderate"):
            base = "Tumor-selective, with caveats."
        elif win == "absent" and dist == "absent":
            base = "Not tumor-selective."
        else:
            base = "Selectivity largely unmeasured or not distinguishing."
        # SAFE negative but no selective signal to lead with: the target is not selective / not
        # distinguishing — say so, then carry the normal-tissue liability as a TRAILING caveat rather
        # than announcing a selectivity the WIN/DIST axes do not support.
        if safe == "negative" and not has_selective:
            base = base.rstrip(".") + " — with a normal-tissue liability."
        if intr == "negative":
            base = base.rstrip(".") + " — but the signal may be microenvironment-driven."
        return base

    return build_key_signals(
        vec,
        # SAFE is a LIABILITY axis, not a positive support — a clean normal side is the absence of a
        # liability, not headline-worthy selectivity evidence. So it drives CAVEATS (critical_keys)
        # but is excluded from the positive SUPPORTS (rank_keys). WIN/DIST/INT carry the positive case.
        rank_keys=("WIN", "DIST", "INT"),
        support_fns={"WIN": sup_win, "DIST": sup_dist, "INT": sup_int},
        # SAFE first so a normal-tissue window liability wins ties as the surfaced caveat (the
        # decision-critical caveat for a selectivity call is the therapeutic-window threat).
        critical_keys=("SAFE", "WIN", "INT", "DIST"),
        caveat_fns={"WIN": cav_win, "DIST": cav_dist, "INT": cav_int, "SAFE": cav_safe},
        headline_fn=head,
    )


__all__ = ["selectivity_claim_vector", "selectivity_key_signals", "SELECTIVITY_CLAIM_SPEC"]
