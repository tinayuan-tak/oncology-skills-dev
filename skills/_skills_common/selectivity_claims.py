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


def selectivity_claim_vector(headline: dict, cards: list) -> dict:
    """The verdict-inert claim vector {WIN,DIST,INT,SAFE: {signal, corroboration, evidence, conflict,
    informs}, _disclaimer}. Projection over the computed headline."""
    return build_claim_vector(SELECTIVITY_CLAIM_SPEC, headline, cards, _DISCLAIMER)


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
