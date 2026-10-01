"""safety_claims — on-target-safety-liability's CLAIM VECTOR + KEY SIGNALS: a verdict-INERT projection
of the human-genetics safety cards into (signal × corroboration) per orthogonal claim.

A concrete instance of the shared claim_vector_core contract. Declares EIGHT safety axes as a ClaimSpec list (five human-genetics + two
added in the 2026-08-21 data-utilization expansion + one verdict-INERT clinical-context axis added in the
2026-09-04 signal-surfacing):

  CONSTRAINT    gnomAD LoF constraint  — pLI / LOEUF / obs-vs-exp LoF; the core LoF-intolerance signal.
  BURDEN        population gene-burden — Open Targets LoF-risk-phenotype vs protective.
  DOSAGE        ClinGen dosage         — haploinsufficiency (autosomal-dominant loss).
  CLINVAR       germline pathogenicity — germline-pathogenic variant burden (+ the confident variant COUNT).
  MOUSE_KO      mouse-KO phenotype     — lethality / severe-organ phenotype on knockout (+ ORGAN systems).
  PAN_ESSENTIAL DepMap pan-essentiality — common_essential across the panel → broad normal-tissue tox.
  NORMAL_TISSUE HPA-IHC essential-tissue protein — on-target-off-tumor liability for a full-KO agent.
  PHARMACOVIGILANCE  on-target clinical warnings — FDA black-box/withdrawn + toxicity classes of drugs that
                     ENGAGE the target (OT drug-warning ⋈ MoA + OnSIDES boxed ADEs). VERDICT-INERT CONTEXT
                     — on/off-target-confounded, corroboration capped, orients-not-holds; the rich toxicity
                     sub-field the capsule projection carried but the narrator never surfaced.

LIABILITY SEMANTICS (inverse-valence, like selectivity's SAFE axis): a STRONG signal here is a strong
safety CONCERN (LoF-intolerant / risk phenotype / haploinsufficient / pathogenic / KO-lethal), NOT a
good thing. A MEASURED tolerant read (LoF-tolerant, dosage-sufficient, no-phenotype) is `absent`
(measured negative concern); a burden that is PROTECTIVE is `negative` (measured opposite direction).
`unmeasured` (indeterminate / no-entry / insufficient) is a data GAP, never evidence of safety.

MECHANISM CONDITIONING: for a mutant-selective GoF (alteration-role functional_direction=activating) the
WT-loss concern is MODALITY-CONDITIONAL — an allele-selective agent need not fully inhibit the WT gene.
That downgrade was RETIRED from the scalar resolver (safety.resolver 2.0.0, 2026-08-24); it now lives in
the per-modality safety verdict (safety_verdict_by_modality: small_molecule may be `conditional`). The
SCALAR safety verdict is the honest raw WT-loss concern and is NOT downgraded. This projection surfaces
the modality-conditionality as a CONSTRAINT `conflict` tension (pointing at the per-modality verdict); it
never re-computes the verdict (owned by the shared safety resolver). Verdict-INERT: reads the ALREADY-
computed safety _headline; the EGFR/FLT3 replay guards freeze the safety verdict byte-stable with or
without this.
"""

from __future__ import annotations

from _skills_common.claim_vector_core import (
    ClaimSpec,
    build_claim_vector,
    build_key_signals,
    bump_corroboration,
    cap_corroboration,
    cards_by_id,
    corroboration_from_arms,
    sig_ge,
)
from _skills_common.source_properties_core import build_source_properties  # shared L2a recipe loop (#2373)

# ── enum → LIABILITY tier maps (grounded in the target-contracts card summary_fields_vocabulary) ────
_CONSTRAINT_SIGNAL = {
    "highly_constrained": "strong",
    "moderately_constrained": "moderate",
    "tolerant": "absent",  # MEASURED: LoF-tolerant → no constraint concern
    "indeterminate": "unmeasured",
}
_BURDEN_SIGNAL = {
    "lof_risk_phenotype": "strong",
    "direction_unresolved": "weak",
    "protective": "negative",  # MEASURED opposite direction (LoF protective) → not a liability
    "no_burden_signal": "absent",
    "insufficient": "unmeasured",
}
_DOSAGE_SIGNAL = {
    "autosomal_dominant_loss": "strong",  # haploinsufficiency
    "unresolved": "weak",
    "dosage_sufficient": "absent",
    "no_clingen_entry": "unmeasured",
    "insufficient": "unmeasured",
}
_CLINVAR_SIGNAL = {
    "germline_pathogenic": "strong",
    "germline_pathogenic_low_review": "moderate",
    "somatic_only": "weak",  # somatic, not germline-LoF → weaker on-target-safety read
    "no_pathogenic_signal": "absent",
    "no_clinvar_entry": "unmeasured",
    "insufficient": "unmeasured",
}
_MOUSEKO_SIGNAL = {
    "lethal_ko": "strong",
    "severe_organ_phenotype": "strong",
    "developmental_only": "moderate",  # developmental lethality — less relevant to adult dosing
    "mild_phenotype": "weak",
    "no_phenotype": "absent",
    "insufficient": "unmeasured",
}
# DepMap pan-essentiality as a BROAD-TOX liability (data-util expansion 2026-08-21): common_essential =
# required across the whole panel → a full-KO agent kills normal cells too. A SELECTIVE dependency
# (strongly_selective / non_dependent) is `absent` here — that is a therapeutic WINDOW, not a safety
# concern. Underpowered rungs are a coverage gap.
_PANESS_SIGNAL = {
    "common_essential": "strong",
    # #1794 (card 3.1.0): well-powered >=85% strongly-dependent fraction whose curated core-essential
    # ANCHOR was unreachable — the measured fraction IS the liability signal (the anchor is the missing
    # EXCULPATORY corroboration, not the missing evidence), and the resolver HOLDs it with the same
    # token as the curated arm. The evidence string discloses the anchor outage (unverified ≠ refuted).
    "common_essential_unanchored": "strong",
    "broadly_dependent": "moderate",  # dependent in many (not pan) lineages — partial breadth
    "common_essential_underpowered": "weak",
    "strongly_selective": "absent",  # MEASURED: selective → a window exists (not a broad-tox liability)
    "non_dependent": "absent",
    "non_dependent_underpowered": "unmeasured",
    "data_unavailable": "unmeasured",
}
# HPA-IHC essential-tissue protein liability (data-util expansion 2026-08-21): protein detected in a
# curated essential normal tissue → on-target-off-tumor tox for a full-KO SM/degrader. Scalar flag.
_NORMALTISSUE_SIGNAL = {
    "present": "strong",  # essential-tissue protein expression
    "absent": "absent",  # MEASURED: no essential-tissue expression
}
# On-target clinical PHARMACOVIGILANCE (2026-09-04 literature/signal-surfacing): do drugs that ENGAGE the
# target carry FDA black-box / withdrawn warnings, and what toxicity CLASSES (OT drug-warning ⋈ MoA +
# OnSIDES label ADEs)? This is the CLINICAL corroboration of the human-genetics WT-loss liability — the
# rich sub-field (toxicity_classes / boxed-warning terms) the capsule projection carried (in the headline +
# _synthesis_facet) but the claim vector / narrator leading-signal never surfaced. CONFOUNDED (a
# drug-name→gene join with class-wide recall cannot separate on- from off-target), so it is VERDICT-INERT
# CONTEXT — corroboration is CAPPED (never `high`) and it ORIENTS the reader, never a resolver HOLD (the
# scalar safety verdict does not read it; matches the drug-warning-safety / onsides-adverse-event-safety
# cards' no-resolver-rung posture). A withdrawn / black-box class is a STRONG clinical liability SIGNAL.
_PHARMACOVIGILANCE_SIGNAL = {
    "withdrawn_drug": "strong",  # an engaging drug was WITHDRAWN (strongest pharmacovigilance flag)
    "black_box_warned": "strong",  # an engaging drug carries an FDA black-box warning
    "other_warning": "moderate",  # engaging drug(s) warned, neither withdrawn nor black-box
    "no_warning": "absent",  # MEASURED: engaging drug(s) exist, none warned
    "no_targeted_drug": "unmeasured",  # coverage gap: no OT-MoA drug engages the target
    "insufficient": "unmeasured",
}

_INFORMS = {
    "CONSTRAINT": "LoF constraint — the core on-target LoF-tolerance signal (degrader / full-KO risk)",
    "BURDEN": "population gene-burden — human-genetics LoF phenotype risk",
    "DOSAGE": "dosage sensitivity — haploinsufficiency (partial-inhibition risk)",
    "CLINVAR": "germline pathogenicity — clinical LoF-variant evidence",
    "MOUSE_KO": "mouse-KO phenotype — organismal essentiality of loss",
    "PAN_ESSENTIAL": "DepMap pan-essentiality — broad normal-tissue tox of full loss (no therapeutic window)",
    "NORMAL_TISSUE": "HPA-IHC essential-tissue protein — on-target-off-tumor liability for a full-KO agent",
    "PHARMACOVIGILANCE": "on-target clinical pharmacovigilance — FDA warnings / toxicity classes of drugs "
    "that engage the target (confounded CONTEXT, orients not holds)",
}
# EVERY claim is a LIABILITY: a strong signal is a RISK the safety VERDICT owns, not a nomination win.
_LIABILITY_NOTE = " (LIABILITY — a strong signal is a safety CONCERN; verdict owned by the safety resolver)"
# PHARMACOVIGILANCE is verdict-INERT CONTEXT (like the drug-warning-safety card): a strong signal ORIENTS
# the reader but never HOLDs — the scalar safety verdict does not read it, and the on-/off-target confound
# means the corroboration is capped.
_CONTEXT_NOTE = " (verdict-INERT CONTEXT — orients the reader, never a resolver HOLD; confounded on/off-target)"


def _f(v, nd=2):
    return f"{v:.{nd}f}" if isinstance(v, (int, float)) else "n/a"


# ── the five claims (signal_fn -> (tier, evidence, conflict); corroboration_fn -> tier) ────────────
def _constraint_signal(h, c):
    cls = h.get("constraint_class")
    sig = _CONSTRAINT_SIGNAL.get(cls, "unmeasured")
    conflict = None
    # mechanism conditioning: for a mutant-selective GoF the WT-loss concern is MODALITY-CONDITIONAL. The
    # scalar downgrade was retired (safety.resolver 2.0.0); it now lives in the per-modality safety verdict,
    # NOT the scalar. Surfaced here as a tension (tier unchanged — this is the SIGNAL, not the verdict).
    if sig_ge(sig, "moderate") and h.get("alteration_functional_direction") == "activating":
        conflict = (
            "activating (GoF) driver: the WT LoF-constraint concern is MODALITY-CONDITIONAL — an "
            "allele-selective small molecule may spare WT protein (see the per-modality safety "
            "verdict); the scalar safety verdict is the raw concern and is NOT downgraded"
        )
    ev = (
        f"gnomAD: {cls or 'data_unavailable'}, pLI={_f(h.get('pli_score'))}, LOEUF={_f(h.get('loeuf_score'))}, "
        f"obs/exp LoF={h.get('obs_lof_count')}/{_f(h.get('exp_lof_count'), 1)}"
    )
    return sig, ev, conflict


# s_het (GeneBayes) classes that AGREE with a gnomAD-constrained call vs the one that CONTRADICTS it.
_SHET_CONSTRAINED = {"high_intolerance", "moderate_intolerance"}
_SHET_TOLERANT = {"tolerant"}


def _constraint_corr(h, c):
    if _CONSTRAINT_SIGNAL.get(h.get("constraint_class"), "unmeasured") == "unmeasured":
        return "unmeasured"
    # gnomAD pLI+LOEUF is ONE source → base corroboration. s_het (GeneBayes dominant-LoF selection
    # coefficient, Zeng 2024) is a genuinely INDEPENDENT second arm: an AGREEING s_het (intolerant) bumps
    # corroboration, a CONTRADICTING s_het (gnomAD-constrained yet LoF-tolerant) caps it. Previously this was
    # pinned 'high' on pLI+LOEUF presence ALONE — a dead-constant column; s_het makes it carry real
    # cross-source agreement. Verdict-INERT (the safety verdict is the resolver's, not this projection's).
    # ONE arm either way: whether pLI/LOEUF carry numbers is WITHIN-arm detail, not a second opinion,
    # and certainly not a conflict (the old `low` fell into the ledger's disagreement set). An agreeing
    # s_het below then makes this genuinely two-armed and lifts it to `high`.
    base = "single_arm"
    shet = h.get("shet_class")
    if shet in _SHET_CONSTRAINED:  # independent agreeing arm → moderate→high (low→moderate)
        return bump_corroboration(base, True)
    if shet in _SHET_TOLERANT and sig_ge(_CONSTRAINT_SIGNAL.get(h.get("constraint_class")), "moderate"):
        return cap_corroboration(base, "low")  # gnomAD-constrained but s_het-tolerant → conflict caps
    return base  # s_het indeterminate / absent → ONE arm, nothing to agree with


def _gof_germline_caveat(h, sig):
    """#993 pt2: for an activating (GoF) driver, a germline-pathogenicity / population LoF-risk leg is
    NOT WT-LoF-intolerance corroboration — the germline associations are with ACTIVATING variants (GoF
    syndromes; e.g. RASopathy/Noonan, activating mosaic), not loss-of-function. Surfaced as a tension so
    the leg is not counted as LoF-corroboration and the synthesis does not propagate the mislabel. Mirrors
    the CONSTRAINT/PANESS mechanism-conditioning; verdict-INERT (tier unchanged — the scalar safety verdict
    is the resolver's raw concern and is NOT downgraded; direction lives per-modality)."""
    if sig_ge(sig, "moderate") and h.get("alteration_functional_direction") == "activating":
        return (
            "activating (GoF) driver: this germline / population LoF-risk association is with ACTIVATING "
            "germline variants (GoF syndrome), NOT WT loss-of-function — do NOT count as LoF-intolerance "
            "corroboration; any WT-loss reading is MODALITY-CONDITIONAL (see the per-modality safety "
            "verdict). The scalar safety verdict is the raw concern and is NOT downgraded."
        )
    return None


def _burden_signal(h, c):
    cls = h.get("burden_safety_class")
    ev = f"gene-burden: {cls or 'data_unavailable'}, min_p={h.get('burden_min_pvalue')}, disease={h.get('burden_top_disease')}"
    sig = _BURDEN_SIGNAL.get(cls, "unmeasured")
    return sig, ev, _gof_germline_caveat(h, sig)


def _burden_corr(h, c):
    if _BURDEN_SIGNAL.get(h.get("burden_safety_class"), "unmeasured") == "unmeasured":
        return "unmeasured"
    # ONE arm (the burden test itself). The p-value grades how STRONG that arm is, which is a signal
    # question, not a corroboration one — there is no second arm here to agree or disagree, so the old
    # p<1e-6 -> `high` reported maximal cross-source agreement from a single test. See the follow-up
    # noted in claim_vector_core: single-arm strength belongs on the SIGNAL axis.
    return "single_arm"


def _dosage_signal(h, c):
    cls = h.get("dosage_sensitivity_class")
    ev = f"ClinGen dosage: {cls or 'data_unavailable'}, inheritance={h.get('germline_inheritance_mode')}"
    sig = _DOSAGE_SIGNAL.get(cls, "unmeasured")
    return sig, ev, _gof_germline_caveat(h, sig)


def _dosage_corr(h, c):
    return (
        "single_arm"
        if _DOSAGE_SIGNAL.get(h.get("dosage_sensitivity_class"), "unmeasured") != "unmeasured"
        else "unmeasured"
    )


def _clinvar_signal(h, c):
    cls = h.get("clinvar_pathogenic_class")
    ev = f"ClinVar: {cls or 'data_unavailable'}, disease={h.get('clinvar_top_disease')}"
    # Surface the confident germline-pathogenic variant COUNT — the rich sub-field the capsule projection
    # ignored (was class + top_disease only). "N confident germline-pathogenic variants" is far more
    # informative than the bare `germline_pathogenic` class for a clinical LoF-liability read.
    n = h.get("clinvar_n_pathogenic_germline_confident")
    if isinstance(n, int) and n > 0:
        ev += f", confident-germline-pathogenic-variants={n}"
    sig = _CLINVAR_SIGNAL.get(cls, "unmeasured")
    return sig, ev, _gof_germline_caveat(h, sig)


def _clinvar_corr(h, c):
    return (
        "single_arm"
        if _CLINVAR_SIGNAL.get(h.get("clinvar_pathogenic_class"), "unmeasured") != "unmeasured"
        else "unmeasured"
    )


def _mouseko_signal(h, c):
    cls = h.get("mouse_ko_phenotype_class")
    ev = f"mouse-KO: {cls or 'data_unavailable'}, lethal={h.get('mouse_ko_top_lethal')}"
    # Surface the affected ORGAN SYSTEMS — the rich sub-field the capsule projection ignored (was class +
    # top_lethal_label only). Which organ systems a KO perturbs (hematopoietic / cardiovascular / etc.) is
    # the safety-relevant detail beneath a bare `lethal_ko`.
    organs = h.get("mouse_ko_organ_systems")
    if organs:
        ev += f", organ-systems={list(organs) if not isinstance(organs, str) else organs}"
    # Finer lethality bins beneath the coarse class (#1893 signal-wire): the adult vs developmental
    # lethal-row COUNTS and the distinct lethal STAGES that drive `top_lethal_label`. Adult/postnatal
    # lethality is the dosing-relevant liability; developmental-only lethality is less relevant to adult
    # dosing (mirrors the _MOUSEKO_SIGNAL 'developmental_only' -> moderate weighting). Additive display.
    n_adult = h.get("mouse_ko_n_adult_lethal")
    n_dev = h.get("mouse_ko_n_developmental_lethal")
    if n_adult or n_dev:
        ev += f", lethal-rows(adult={n_adult or 0}/developmental={n_dev or 0})"
    stages = h.get("mouse_ko_lethal_stages")
    if stages:
        ev += f", lethal-stages={list(stages) if not isinstance(stages, str) else stages}"
    # IMPC top-level organ systems — the IMPC-direct twin of the OT-MGI organ_classes above (the finer
    # organ-system profile behind the coarse IMPC viability class read just below).
    impc_systems = h.get("mouse_ko_impc_top_level_systems")
    if impc_systems:
        ev += f", IMPC-systems={list(impc_systems) if not isinstance(impc_systems, str) else impc_systems}"
    sig = _MOUSEKO_SIGNAL.get(cls, "unmeasured")
    conflict = None
    # #1001: surface the IMPC preweaning-viability read. The coarse ko_phenotype_class collapses a
    # constitutive embryonic-lethal to developmental_only, or the gene is simply ABSENT from IMPC
    # (-> no_phenotype / insufficient) — so the highest-WT-loss-liability genes read as a COVERAGE GAP,
    # not as a phenotype. When IMPC recorded a lethal/subviable call but the coarse class went
    # unmeasured/no_phenotype/insufficient, surface it + flag the gap. VERDICT-INERT (tier unchanged; a
    # verdict-moving 'essentiality_implied_lethal' promotion is deferred as it needs a panel backtest).
    impc = h.get("impc_viability_class")
    if impc and impc not in ("viable", "unmeasured"):
        ev += f", IMPC-viability={impc}"
        if sig == "unmeasured" or cls in ("no_phenotype", "insufficient"):
            conflict = (
                f"mouse-KO phenotype class reads '{cls or 'data_unavailable'}' but the IMPC preweaning "
                f"screen is '{impc}': a constitutive embryonic-lethal is the hardest to phenotype, so this "
                f"is a COVERAGE GAP — NOT evidence of no phenotype (the highest-WT-loss-liability genes "
                f"read here)."
            )
    return sig, ev, conflict


def _mouseko_corr(h, c):
    return (
        "single_arm"
        if _MOUSEKO_SIGNAL.get(h.get("mouse_ko_phenotype_class"), "unmeasured") != "unmeasured"
        else "unmeasured"
    )


def _paness_signal(h, c):
    cls = h.get("dependency_class")
    sig = _PANESS_SIGNAL.get(cls, "unmeasured")
    conflict = None
    # mechanism conditioning (mirrors CONSTRAINT): for a mutant-selective GoF, WT-sparing makes the
    # broad-tox concern MODALITY-CONDITIONAL. Retired from the scalar verdict; now per-modality only.
    if sig_ge(sig, "moderate") and h.get("alteration_functional_direction") == "activating":
        conflict = (
            "activating (GoF) driver: the broad-tox pan-essential concern is MODALITY-CONDITIONAL — "
            "an allele-selective small molecule may spare WT in normal tissue (see the per-modality "
            "safety verdict); the scalar safety verdict is the raw concern and is NOT downgraded"
        )
    ev = f"DepMap: {cls or 'data_unavailable'}, pan_essential_score={_f(h.get('pan_essential_score'))}"
    # #1794 disclosures — both APPEND-ONLY on the new card 3.1.0 states, so every pre-0.3.0 package
    # (fields/values absent) keeps its evidence string byte-identical.
    if cls == "common_essential_unanchored":
        ev += (
            ", curated core-essential anchor UNREACHABLE — the pan-essential call is UNVERIFIED, not "
            "refuted (a re-run with anchor access resolves it)"
        )
    if h.get("broad_dependency_band") == "partial_broad_band":
        ev += ", broad_dependency_band=partial_broad_band (0.60–0.85 — a PARTIAL broad-tox liability, graded)"
    return sig, ev, conflict


def _paness_corr(h, c):
    return (
        "single_arm"
        if _PANESS_SIGNAL.get(h.get("dependency_class"), "unmeasured") not in ("unmeasured",)
        else "unmeasured"
    )


# When the ESSENTIAL-tissue flag is indeterminate (`unknown`) but the card DID measure normal-tissue
# breadth, fall back to breadth so a MEASURED on-target-off-tumor liability is not reported as a data gap
# (`unmeasured`). Broad normal expression = broad off-tumor liability for a full-KO agent (measured,
# moderate); tumor-restricted / not-detected-in-normal is the clean case (owned by the `absent` flag).
_NORMALTISSUE_BREADTH_FALLBACK = {"broad_normal_expression": "moderate"}

# ★ #1793 (organ-coverage spine, pin-coupled with TC safety.resolver 2.3.0): the TPHP DIA-MS HPA-BLIND
# vital-organ read — the vital-organ protein view SCOPED to the organs HPA-IHC structurally CANNOT
# represent (nerve / blood / adrenal_gland / thyroid / pituitary; HPA's closed 16-name vocabulary has
# no name for them). `vital_organ_abundant` is a MEASURED essential-organ protein liability carried by
# the ONE protein panel that covers those organs, and it fires a verdict-bearing resolver rung
# (tphp-hpa-blind-vital-organ-protein-safety-warning → normal_tissue_protein_safety_concern), so the
# claim axis must not read "clean"/"unmeasured" where the resolver HOLDs. It PROMOTES the signal to
# `strong` even over an HPA `absent` read — not a contradiction: the organ sets are DISJOINT, so the
# HPA measured-clear is scope-limited to HPA-representable organs (disclosed as `conflict`). Absence
# claims stay owned by the HPA flag: `no_vital_organ_signal` / `vital_organ_low` / `data_unavailable`
# NEVER count as a clean corroborator (no_vital_organ_signal is not a clean sweep — coverage is the
# whole point of hpa_blind_vital_organs_uncovered). None-stable: field absent → behavior byte-identical.
_TPHP_BLIND_LIABILITY = "vital_organ_abundant"


def _tphp_blind_liability(h) -> bool:
    return h.get("tphp_hpa_blind_vital_organ_liability_class") == _TPHP_BLIND_LIABILITY


def _normaltissue_sig(h) -> str:
    """Resolved NORMAL_TISSUE liability signal: essential-tissue flag first, else measured breadth;
    a measured TPHP HPA-blind vital-organ liability (#1793) lifts the resolved signal to `strong`."""
    sig = _NORMALTISSUE_SIGNAL.get(h.get("essential_tissue_flag"), "unmeasured")
    if sig == "unmeasured":
        sig = _NORMALTISSUE_BREADTH_FALLBACK.get(h.get("normal_tissue_breadth_class"), "unmeasured")
    if _tphp_blind_liability(h) and not sig_ge(sig, "strong"):
        sig = "strong"
    return sig


def _normaltissue_signal(h, c):
    ev = (
        f"HPA-IHC: essential_tissue_flag={h.get('essential_tissue_flag') or 'data_unavailable'}, "
        f"tissues={h.get('essential_tissues_flagged')}, breadth={h.get('normal_tissue_breadth_class')}"
    )
    conflict = None
    tphp_cls = h.get("tphp_hpa_blind_vital_organ_liability_class")
    if tphp_cls:
        ev += (
            f"; TPHP DIA-MS (HPA-blind vital organs, #1793): {tphp_cls}"
            f", above_floor={h.get('hpa_blind_vital_organs_above_floor')}"
            f", uncovered={h.get('hpa_blind_vital_organs_uncovered')}"
        )
    if tphp_cls == _TPHP_BLIND_LIABILITY and h.get("essential_tissue_flag") == "absent":
        conflict = (
            "HPA-IHC reads measured-clear over its closed 16-name tissue vocabulary, but TPHP DIA-MS "
            "quantifies the protein at/above the abundance floor in HPA-blind vital organ(s) "
            f"{h.get('hpa_blind_vital_organs_above_floor')} — DISJOINT organ sets, not a contradiction: "
            "the HPA clear is scope-limited to HPA-representable organs, and the measured blind-organ "
            "liability drives the resolver HOLD (tphp-hpa-blind-vital-organ-protein-safety-warning)"
        )
    return _normaltissue_sig(h), ev, conflict


# GTEx normal-tissue liability_class directions (independent RNA atlas) vs the HPA-IHC protein call.
_GTEX_LIABILITY = {"critical_organ_liability", "broadly_expressed_normal"}
_GTEX_CLEAN = {"restricted_normal", "moderate_normal_breadth"}


def _normaltissue_corr(h, c):
    # HPA-IHC essential-tissue protein (the signal source) is ONE assay → base corroboration. The GTEx
    # normal-tissue RNA atlas (normal-tissue-liability-gtex, a verdict-bearing decision card that fired
    # normal-liability rules but was invisible to this claim) is a genuinely INDEPENDENT second arm: a
    # same-direction GTEx call (both flag a normal-tissue liability, or both read clean) bumps
    # corroboration; a contradicting one caps it. Was single-source (dead-constant moderate). Verdict-INERT.
    sig = _normaltissue_sig(h)
    if sig == "unmeasured":
        return "unmeasured"
    hpa_liability = sig_ge(sig, "moderate")  # present/broad = liability; absent = clean
    gtex = (c.get("normal-tissue-liability-gtex") or {}).get("liability_class")
    if gtex in _GTEX_LIABILITY:
        return bump_corroboration("moderate", True) if hpa_liability else cap_corroboration("moderate", "low")
    if gtex in _GTEX_CLEAN:
        return bump_corroboration("moderate", True) if not hpa_liability else cap_corroboration("moderate", "low")
    return "single_arm"  # GTEx unavailable / indeterminate → ONE arm, nothing to agree with


# ── L2b-3 cross-source normal-tissue safety-liability concordance (SK#1546) ───────────────────────
# Three genuinely INDEPENDENT normal-tissue liability measurements, integrated by an EXPLICIT
# DETERMINISTIC rule (no LLM — L2b is reproducible by contract). Each source resolves a per-source
# liability DIRECTION: 'high' (a clear normal-tissue liability), 'clean' (a measured low/absent read),
# or None (unavailable / ambiguous — abstains from the vote, raw value still recorded for fidelity).
#
# APPLES-TO-APPLES (SK#1575): the scRNA arm reads the ORGAN-AWARE `sc_normal_safety_essential_class`
# (critical_organ_liability / origin_tissue_liability / none), NOT the organ-agnostic breadth field
# `sc_normal_expression_class`. GTEx `liability_class` (curated critical-organ OR ≥70% breadth) and HPA
# `essential_tissue_flag` (curated essential normal tissue) both resolve an ORGAN/essential-tissue
# liability; the breadth field's HIGH_LIABILITY fired on strong detection in ANY queried normal cell type
# — incl. non-critical / tissue-of-origin epithelium — so it voted 'high' on a systematically broader
# basis than the two organ-aware arms and could MANUFACTURE a cross-source (dis)concordance. The graded
# veto sibling `sc_normal_essential_veto_grade` folds SEVERITY into the token, which would conflate the
# directional liability read with the veto's own strength ladder — the categorical class is the direct
# organ-aware analogue of the GTEx/HPA categorical calls, so it is the apples-to-apples choice.
_LIAB_SC_HIGH = frozenset({"critical_organ_liability"})
_LIAB_SC_CLEAN = frozenset({"none"})
# (source_key, property, assay, card_id, field) — fixed order; the arm list & payload follow it.
_LIAB_SOURCES = (
    (
        "gtex_bulk_rna",
        "normal_tissue_liability_rna_bulk",
        "gtex_bulk",
        "normal-tissue-liability-gtex",
        "liability_class",
    ),
    (
        "sc_normal_rna",
        "normal_tissue_liability_rna_singlecell",
        "sc_normal_celltype",
        "sc-normal-celltype-expression",
        "sc_normal_safety_essential_class",
    ),
    (
        "hpa_ihc_protein",
        "normal_tissue_liability_protein_ihc",
        "hpa_ihc",
        "normal-tissue-liability",
        "essential_tissue_flag",
    ),
)


def _liab_direction(source_key: str, token) -> "str | None":
    """One source's normal-tissue liability token → 'high' | 'clean' | None (abstain: unavailable/ambiguous).

    Membership tests, NOT `if token:` — every abstain sentinel here (data_unavailable, unknown,
    origin_tissue_liability) is a TRUTHY string that must stay OUT of the resolved buckets.

    scRNA `origin_tissue_liability` deliberately ABSTAINS (SK#1575): it is essential-cell expression
    CONFINED to the tumour's tissue of origin — on-tissue, window-ARBITRATED, explicitly NOT a hard
    safety veto (a validated ADC target must survive it). The GTEx and HPA arms do not resolve a
    tissue-of-origin call as either a critical-organ liability or a clean read, so voting it 'high' would
    manufacture discordance against them and voting it 'clean' would deny a real essential-cell read.
    It abstains — the direct analogue of the GTEx `moderate_normal_breadth` narrow-window abstain — and
    its raw token still rides in the payload (recoverable)."""
    if source_key == "gtex_bulk_rna":
        if token in _GTEX_LIABILITY:
            return "high"
        if token in _GTEX_CLEAN:
            return "clean"
        return None
    if source_key == "sc_normal_rna":
        if token in _LIAB_SC_HIGH:
            return "high"
        if token in _LIAB_SC_CLEAN:
            return "clean"
        return None
    # hpa_ihc_protein: essential_tissue_flag present=liability, absent=clean, unknown/None=abstain (a gap,
    # never reassurance — mirrors the card's `unknown` semantics).
    if token == "present":
        return "high"
    if token == "absent":
        return "clean"
    return None


def _normal_liability_concordance_claim(c: dict) -> "dict | None":
    """L2b-3 CROSS-SOURCE integration claim: `normal_liability_concordance` (SK#1546).

    Integrates THREE genuinely INDEPENDENT normal-tissue safety-liability measurements by an EXPLICIT
    DETERMINISTIC rule (no LLM — L2b is reproducible by contract):
      * GTEx bulk RNA   (normal-tissue-liability-gtex.liability_class)         — pooled tissue transcriptome
      * scRNA cell-type (sc-normal-celltype-expression.sc_normal_safety_essential_class) — single-cell atlas
      * HPA-IHC protein (normal-tissue-liability.essential_tissue_flag)        — antibody protein staining

    Each resolves a liability DIRECTION (high / clean / None-abstain). Then:
      * liability_concordant_high    — >=2 sources resolve and ALL agree there IS a normal-tissue liability;
      * liability_concordant_low     — >=2 resolve and ALL agree the target reads clean;
      * liability_assay_discordant   — resolved sources DISAGREE (payload names which flag liability vs
        read clean — e.g. GTEx bulk-high but scRNA cell-type-resolved clean = possible bulk contamination
        vs cell-type-resolved safety; RNA-high but protein IHC clean = possible non-translated transcript);
      * liability_single_source_only — exactly ONE source resolves, the other two are gaps: the degraded
        read that names the resolved arm (recoverable), NOT a concordance claim.

    Corroboration on the shared MEASURED-ARM frame: agreeing arms → high, any disagreement → low, one
    measured arm → single_arm. A single-source mutation only DEGRADES the read to
    `liability_single_source_only`; ERASING the conclusion (key omitted, byte-stable) takes defeating ALL
    THREE supplies (the M3 fidelity / reach discipline).

    VERDICT-INERT: carries NO `signal` key (never a chip, never a tier, never averaged), reads no verdict,
    feeds no rule. The sc-normal card's own veto (tvn-sc-normal-critical-organ-veto) is NOT a
    safety.resolver rung nor in the wt_loss_safety_conditioning modality contract, so both the scalar and
    per-modality safety verdicts stay byte-stable. The scRNA arm reads `sc_normal_safety_essential_class`
    (SK#1575), which no interpretation rule keys on for ANY axis — it is a DISPLAY class (every gate reads
    the graded `sc_normal_essential_veto_grade`), so repointing onto it neither routes the claim nor moves
    a verdict. Returns None — key omitted — when NO source resolves."""
    raw = {sk: (c.get(cid) or {}).get(field) for sk, _prop, _assay, cid, field in _LIAB_SOURCES}

    # ── scRNA off-origin split provenance echo (TC#882/F12; #1770) ──────────────────────────────────
    # VERDICT-INERT provenance: the indication that was resolved to the tumour tissue(s)-of-origin the
    # scRNA off-origin split was computed against — the very basis for the scRNA arm's
    # `origin_tissue_liability` ABSTAIN (see `_liab_direction`: essential-cell expression CONFINED to the
    # tumour's own tissue of origin is on-tissue and deliberately not voted). Surfacing it makes the
    # abstain auditable ("abstained because the essential cells sit in ORIGIN tissue X, resolved from
    # indication Y") instead of an unexplained non-vote. Read by a LITERAL card-id subscript alias so
    # `field_disposition.census` sees the (card, field) pairs (this closes the fleet-aperture orphan the
    # 468c3dc echo fields open — census reach, blind to the ledger); NOT a literal `get_card_field`, so
    # `test_card_field_conformance` (run.py-only, literal-only) is not tripped while the fields are not
    # yet declared on the pinned card. Guarded on card presence with each key OMITTED when its echo is
    # absent (a pre-echo pinned card, or a genuine data gap), so the claim stays BYTE-STABLE wherever the
    # fields are not emitted. Routes nothing: pure provenance, no signal / tier / rule.
    scrna_off_origin_split: dict = {}
    if "sc-normal-celltype-expression" in c:
        _scn = c["sc-normal-celltype-expression"]
        _scn_indication = _scn.get("indication")
        _scn_origin_tissues = _scn.get("origin_tissues")
        if _scn_indication is not None:
            scrna_off_origin_split["indication"] = _scn_indication
        if _scn_origin_tissues is not None:
            scrna_off_origin_split["origin_tissues"] = _scn_origin_tissues

    dirs = {sk: _liab_direction(sk, raw[sk]) for sk in raw}
    resolved = {sk: d for sk, d in dirs.items() if d is not None}
    # Neither source resolves → no claim (key omitted → byte-stable). The ONLY erasing state: it takes
    # defeating ALL THREE supplies, matching the atom discipline for the other liability axes.
    if not resolved:
        return None

    if len(resolved) == 1:
        concordance = "liability_single_source_only"
    elif all(d == "high" for d in resolved.values()):
        concordance = "liability_concordant_high"
    elif all(d == "clean" for d in resolved.values()):
        concordance = "liability_concordant_low"
    else:
        concordance = "liability_assay_discordant"

    # Arms in fixed source order: an unresolved source is None (dropped before counting). For a discordance
    # a 'high' source AGREES a liability is present (True) and a 'clean' source DISAGREES (False) → any
    # disagreement drops corroboration to `low`. For a concordance / single, each resolved source agrees
    # with the consensus (True): [T,T,None]→high, [T,None,None]→single_arm.
    def _arm(sk: str) -> "bool | None":
        d = dirs[sk]
        if d is None:
            return None
        if concordance == "liability_assay_discordant":
            return d == "high"
        return True

    corroboration = corroboration_from_arms([_arm(sk) for sk, *_ in _LIAB_SOURCES])

    flagged = sorted(sk for sk, d in dirs.items() if d == "high")
    read_clean = sorted(sk for sk, d in dirs.items() if d == "clean")
    if concordance == "liability_assay_discordant":
        source_support = {"liability_flagged_by": flagged, "read_clean_by": read_clean}
    elif concordance == "liability_single_source_only":
        sk = next(iter(resolved))
        source_support = {"resolved_by": sk, "resolved_call": raw[sk], "resolved_direction": resolved[sk]}
    else:
        source_support = {"agreed_direction": next(iter(resolved.values())), "sources_agree": sorted(resolved)}

    _PHRASE = {
        "liability_concordant_high": "AGREE the target carries a normal-tissue safety liability",
        "liability_concordant_low": "AGREE the target reads clean in normal tissue",
        "liability_assay_discordant": "DISAGREE on the normal-tissue liability call",
        "liability_single_source_only": "only one normal-tissue source resolves",
    }

    # ── PRESENTATION-SUPPORT fields (SK#1582 G3.2, mirroring G3.1 #1578) ────────────────────────────
    # Structured directional fields so a question_table answer can SURFACE the integrated read without
    # prose-parsing `evidence`. UNLIKE G3.1's coverage-concordance (always-positive 2-directional shape),
    # the safety valence is CLASS-DEPENDENT / 3-arm: the ENCOURAGING direction is a CLEAN read
    # (concordant_low) and every other class is a QUALIFYING caveat (a corroborated liability, a
    # cross-source disagreement, or a thin single arm) — so exactly ONE of positive/qualifying is non-null.
    # These are PRESENTATION-support ONLY: no signal tier, no polarity, no drives_rule_id, route NOTHING.
    #
    # BOUNDARY-SENSITIVITY (deterministic read of the already-computed corroboration, NOT a new
    # threshold/calibration): the class is corroborated only when >=2 independent lenses AGREE in direction
    # (corroboration `high`). A single measured arm (`single_arm`) or a cross-source disagreement (`low`)
    # leaves the class resting on an uncorroborated / contradicted read — a near-boundary perturbation
    # could flip it, so the alarming classes must never be asserted flatly.
    boundary_sensitive = corroboration != "high"
    if concordance == "liability_concordant_low":
        positive_signal = {
            "statement": (
                f"All resolving normal-tissue lenses ({', '.join(sorted(resolved))}) AGREE the target reads "
                "CLEAN in normal tissue — a low-liability read corroborated across genuinely independent "
                "bulk-RNA / single-cell-RNA / protein-IHC lenses."
            ),
            "source": "normal_liability_concordant_clean",
            "provenance_ref": "source_support.sources_agree",
        }
        qualifying_signal = None
    else:
        positive_signal = None
        if concordance == "liability_concordant_high":
            qualifying_signal = {
                "statement": (
                    f"All resolving normal-tissue lenses ({', '.join(sorted(resolved))}) AGREE the target "
                    "carries a normal-tissue safety liability — a corroborated on-target/off-tumour concern "
                    "(broad normal expression = broad off-tumour liability for a full-KO agent)."
                ),
                "source": "normal_liability_concordant_high",
                "provenance_ref": "source_support.sources_agree",
            }
        elif concordance == "liability_assay_discordant":
            qualifying_signal = {
                "statement": (
                    f"Normal-tissue lenses DISAGREE: {', '.join(flagged)} flag a liability while "
                    f"{', '.join(read_clean)} read clean — a localised artifact (bulk contamination vs "
                    "cell-type-resolved safety, or transcript vs protein), not a settled call."
                ),
                "source": "normal_liability_assay_discordant",
                "provenance_ref": "source_support.liability_flagged_by",
            }
        else:  # liability_single_source_only
            sk = next(iter(resolved))
            qualifying_signal = {
                "statement": (
                    f"Only {sk} resolves ({raw[sk]} → {resolved[sk]}); the other normal-tissue lenses are "
                    "data gaps — a thin single-arm read, not a cross-source concordance."
                ),
                "source": "normal_liability_single_source_only",
                "provenance_ref": "source_support.resolved_by",
            }
    boundary_note = (
        "the normal-tissue concordance rests on a single measured arm or a cross-source disagreement "
        "(corroboration != high) — treat as near-boundary, not a flat assertion"
        if boundary_sensitive
        else "corroborated by >=2 independent normal-tissue lenses agreeing in direction"
    )

    return {
        "concordance_class": concordance,
        "corroboration": corroboration,
        # DETERMINISTIC, reproducible-by-contract: an explicit rule over three tokens, never an LLM.
        "integration_method": "explicit_deterministic",
        # NO `reliability` facet on this L2b island (#2306): the locked shape derives an arm's reliability
        # FROM THAT ARM'S OWN anchors and does not restate the L2a values. This island reads only
        # categorical per-source DIRECTION tokens (GTEx/scRNA/HPA liability calls) with no per-arm anchor
        # list, so there is nothing to derive from → the facet is honestly OMITTED (byte-stable), not a
        # thin restate of the L2a `powered`. Per-arm L2b reliability lands at the presence-style islands
        # that carry per-arm anchors/retained_quantitative (a later #2306 step).
        "source_support": source_support,
        "sources_resolved": sorted(resolved),
        # PRESENTATION-SUPPORT (surface-consumption, NOT verdict-routing) — see block above.
        "positive_signal": positive_signal,
        "qualifying_signal": qualifying_signal,
        "boundary_sensitive": boundary_sensitive,
        "boundary_note": boundary_note,
        "informs": (
            "cross-source normal-tissue safety-liability concordance — an on-target/off-tumor liability seen "
            "across genuinely INDEPENDENT normal-tissue lenses (bulk RNA, cell-type-resolved single-cell RNA, "
            "protein IHC) is far more credible than a single-lens call; a DISCORDANCE localises the artifact "
            "(bulk contamination vs cell-type-resolved safety; transcript vs protein)"
        ),
        "evidence": (
            f"GTEx-bulk {raw['gtex_bulk_rna'] or 'data_unavailable'} × "
            f"scRNA-normal {raw['sc_normal_rna'] or 'data_unavailable'} × "
            f"HPA-IHC {raw['hpa_ihc_protein'] or 'data_unavailable'}: " + _PHRASE[concordance]
        ),
        # Provenance graph: ALL THREE source properties + an independence note. NOT the reserved single-card
        # `evidence_atom` key — this records THREE-card cross-source provenance and carries each source's raw
        # token so the VALUES (not just the key) are recoverable.
        "provenance": {
            "sources": [
                {
                    "property": prop,
                    "assay": assay,
                    "card_id": cid,
                    "fields": {field: raw[sk]},
                    # scRNA arm only: the off-origin split the liability call was computed against
                    # (indication → tissue(s)-of-origin). Omitted when the echo is absent → byte-stable.
                    **(
                        {"off_origin_split": scrna_off_origin_split}
                        if sk == "sc_normal_rna" and scrna_off_origin_split
                        else {}
                    ),
                }
                for sk, prop, assay, cid, field in _LIAB_SOURCES
            ],
            "independence_note": (
                "GTEx bulk RNA (pooled tissue transcriptome), sc-normal cell-type-resolved single-cell RNA "
                "(a DIFFERENT resolution — the cell-type medians the bulk pool dilutes), and HPA-IHC protein "
                "(an ORTHOGONAL antibody protein readout) are three independent normal-tissue liability "
                "measurements; the bulk/single-cell pair shares the RNA modality but differs in resolution, "
                "while IHC is a genuinely orthogonal protein lens — so their (dis)agreement is a real "
                "cross-source corroboration, not a within-assay restatement."
            ),
        },
        "_disclaimer": (
            "L2b CROSS-SOURCE integration claim (deterministic, no LLM) — verdict-INERT provenance: never a "
            "signal tier, never averaged into a claim, never feeds the safety verdict (scalar or per-modality)."
        ),
    }


_PHARMACOVIGILANCE_CAVEAT = (
    "CONFOUNDED on-target-vs-off-target (drug-name→gene join, class-wide recall) — pharmacovigilance "
    "CONTEXT that ORIENTS the reader; the scalar safety verdict does not read it"
)


def _pharmacovigilance_signal(h, c):
    """On-target clinical pharmacovigilance liability: OT drug-warning class (primary) enriched with the
    OnSIDES boxed-warning ADEs. Surfaces the specific TOXICITY CLASSES + boxed-warning terms the capsule
    projection carried but the claim vector never rendered. Confounded → the caveat rides in the conflict
    slot so the narrator downgrades it to context, never a hard liability."""
    dwc = h.get("drug_warning_class")
    sig = _PHARMACOVIGILANCE_SIGNAL.get(dwc, "unmeasured")
    # OnSIDES fallback: a boxed-warning ADE profile is a strong clinical signal even when the OT
    # drug-warning leg is thin/absent (different join coverage). Never DOWNGRADES a drug-warning signal.
    if sig in ("unmeasured", "absent") and h.get("onsides_has_boxed_warning"):
        sig = "moderate"
    tox = h.get("drug_warning_toxicity_classes") or []
    boxed = h.get("onsides_example_boxed_warning_terms")
    parts = [f"drug-warning: {dwc or 'data_unavailable'}"]
    if h.get("drug_warning_has_black_box"):
        parts.append("black-box")
    if tox:
        parts.append(f"tox-classes={list(tox)}")
    if boxed:
        parts.append(f"boxed-ADE=[{boxed}]")
    ev = ", ".join(parts)
    # flag the confound only when a signal actually fires (so a clean `no_warning`/gap stays uncluttered)
    conflict = _PHARMACOVIGILANCE_CAVEAT if sig_ge(sig, "moderate") else None
    return sig, ev, conflict


def _pharmacovigilance_corr(h, c):
    measured = _PHARMACOVIGILANCE_SIGNAL.get(h.get("drug_warning_class"), "unmeasured") != "unmeasured" or bool(
        h.get("onsides_has_boxed_warning")
    )
    # CAP at `moderate` — the on/off-target confound means a black-box hit is never a high-corroboration read.
    return "single_arm" if measured else "unmeasured"


# ── citable evidence atoms (read from the source card summaries; cite each card) ────────────────────
from _skills_common.claim_vector_core import build_summary_atom  # shared atom builder (Group D)


def _constraint_atom(h, c):
    cid = "gnomad-lof-constraint"
    return build_summary_atom(
        card_id=cid,
        summary=c.get(cid) or {},
        keys=("constraint_class", "pli_score", "loeuf_score", "mis_z_score", "obs_lof_count", "exp_lof_count"),
        entity={"measurement_type": "gnomad_lof_constraint", "grain": "target", "valence": "liability"},
        read=(c.get(cid) or {}).get("constraint_class"),
    )


def _burden_atom(h, c):
    cid = "gene-burden-safety"
    return build_summary_atom(
        card_id=cid,
        summary=c.get(cid) or {},
        keys=("burden_safety_class", "min_pvalue", "top_disease"),
        entity={"measurement_type": "gene_burden_safety", "grain": "target", "valence": "liability"},
        read=(c.get(cid) or {}).get("burden_safety_class"),
    )


def _dosage_atom(h, c):
    cid = "clingen-dosage"
    return build_summary_atom(
        card_id=cid,
        summary=c.get(cid) or {},
        keys=("dosage_sensitivity_class", "germline_inheritance_mode", "top_disease"),
        entity={"measurement_type": "dosage_sensitivity_safety", "grain": "target", "valence": "liability"},
        read=(c.get(cid) or {}).get("dosage_sensitivity_class"),
    )


def _clinvar_atom(h, c):
    cid = "clinvar-pathogenicity-safety"
    return build_summary_atom(
        card_id=cid,
        summary=c.get(cid) or {},
        keys=("clinvar_pathogenic_class", "top_disease"),
        entity={"measurement_type": "clinvar_germline_pathogenicity_safety", "grain": "target", "valence": "liability"},
        read=(c.get(cid) or {}).get("clinvar_pathogenic_class"),
    )


def _mouseko_atom(h, c):
    cid = "mouse-ko-phenotype"
    return build_summary_atom(
        card_id=cid,
        summary=c.get(cid) or {},
        keys=("ko_phenotype_class", "top_lethal_label"),
        entity={"measurement_type": "mouse_ko_phenotype_safety", "grain": "target", "valence": "liability"},
        read=(c.get(cid) or {}).get("ko_phenotype_class"),
    )


def _paness_atom(h, c):
    cid = "pan-cancer-crispr-dependency-distribution"
    return build_summary_atom(
        card_id=cid,
        summary=c.get(cid) or {},
        # broad_dependency_band added #1794 (VERDICT-BEARING as of safety.resolver 2.4.0) — the atom
        # binds only non-None keys, so pre-0.3.0 packages stay byte-identical.
        keys=("dependency_class", "pan_essential_score", "distribution_shape", "broad_dependency_band"),
        entity={"measurement_type": "crispr_lof_dependency", "grain": "target", "valence": "liability"},
        read=(c.get(cid) or {}).get("dependency_class"),
    )


def _normaltissue_atom(h, c):
    # ★ #1793: when the TPHP HPA-BLIND vital-organ arm is what carries the measured liability (HPA flag
    # NOT `present` — the HPA arm never saw those organs), the axis's citable atom must bind the values
    # that actually drive the signal/resolver rung to THEIR source card, not to the HPA card. When the
    # HPA arm fires (or the TPHP field is absent — every pre-0.5.0 package), the atom is byte-identical
    # to the pre-#1793 HPA-IHC atom.
    cid = "normal-tissue-liability"
    tphp = c.get("normal-tissue-protein-abundance-tphp") or {}
    if (
        tphp.get("tphp_hpa_blind_vital_organ_liability_class") == _TPHP_BLIND_LIABILITY
        and (c.get(cid) or {}).get("essential_tissue_flag") != "present"
    ):
        return build_summary_atom(
            card_id="normal-tissue-protein-abundance-tphp",
            summary=tphp,
            keys=(
                "tphp_hpa_blind_vital_organ_liability_class",
                "n_hpa_blind_vital_organs_above_abundance_floor",
                "hpa_blind_vital_organs_above_floor",
                "hpa_blind_vital_organs_uncovered",
            ),
            entity={"measurement_type": "normal_tissue_protein_abundance", "grain": "target", "valence": "liability"},
            read=tphp.get("tphp_hpa_blind_vital_organ_liability_class"),
        )
    return build_summary_atom(
        card_id=cid,
        summary=c.get(cid) or {},
        keys=("essential_tissue_flag", "essential_tissues_flagged", "normal_tissue_breadth_class"),
        entity={"measurement_type": "normal_tissue_protein_breadth", "grain": "target", "valence": "liability"},
        read=(c.get(cid) or {}).get("essential_tissue_flag"),
    )


def _pharmacovigilance_atom(h, c):
    cid = "drug-warning-safety"
    return build_summary_atom(
        card_id=cid,
        summary=c.get(cid) or {},
        keys=("drug_warning_class", "has_black_box", "toxicity_classes", "warning_types", "n_targeted_warned_drugs"),
        entity={"measurement_type": "drug_warning_safety", "grain": "target", "valence": "liability"},
        read=(c.get(cid) or {}).get("drug_warning_class"),
    )


# ── L2a NAMED source_properties map — SAFETY domain (PR-1a, epic #2210 Wave 1 / #1507) ─────────────
# The safety generalisation of the tumour-presence reference vertical
# (`presence_claims.py::_SOURCE_PROPERTY_RECIPES` :694). The per-source observational (L2a) properties
# existed only IMPLICITLY, embedded inside the eight claim signal blocks; this lifts them into a NAMED,
# typed map — one entry per source/grain — matching the architecture's export shape
# (docs/EVIDENCE_PROPERTY_ARCHITECTURE_L1_L4.md, the `source_properties:` block). Each entry carries the
# card it resolves from, the resolved observational property class (the SAME L2a class the claim axes read
# from that source), the RETAINED quantitative anchors (value + scale/unit + ledger-declared disposition
# typing), and comparability metadata so a downstream reader can tell which entries are commensurable.
#
# It is a PURE PROJECTION over the already-computed card summaries: no LLM, no new measurement, no
# re-derivation, and — like every other L2a/L2b facet on this vector — it carries NO `signal` key, is read
# by no rule/verdict/ladder, and every property is reconstructable to its L1 card field via
# {card_id, field, value}. VERDICT-INERT.
#
# TWO THINGS THIS DOMAIN PILOTS that the presence vertical does not carry:
#
#   (1) `comparability.valence` — the safety-style LIABILITY marker. Safety is inverse-valence: a STRONG
#       read here is a CONCERN, not a win. Without the marker a downstream reader holding only the L2a
#       export cannot tell which direction is bad, and a generic "higher = better" reader silently
#       inverts every safety property. The token reused is the one the safety evidence ATOMS already
#       emit (`entity.valence == "liability"`, 24 sites in this module) — no new vocabulary is minted.
#       ⚠️ It is a ONE-TOKEN vocabulary today and is NOT yet governed by a contracts validator (the
#       property-catalog `ENTRY_KEYS`/`GRAIN_KEYS` allowlists are closed and have no valence slot, and
#       `GRAIN_KEYS` members are all REQUIRED, so adding one there would red the three landed catalogs).
#       Declared in `docs/EVIDENCE_PROPERTY_ENVELOPE_v0.md` § v1.1 (iii); 1b–1e must NOT invent a second
#       token without governing it first — an ungoverned second token is exactly the drift 0b/0d closed.
#
#   (2) `interpretation` — the Wave-0c per-entry resolution provenance
#       ({function_id, version, disjunct_fired}), DECLARED in envelope v1.1 (ii) and until now
#       IMPLEMENTED NOWHERE. Its tumour-presence implementation is #2227, blocked because it would
#       regenerate the presence golden; the safety domain is not golden-blocked, so this is the shape's
#       FIRST live emission. Emitted on the ONE entry whose read this domain resolves through a genuine
#       multi-arm disjunction (`normal_tissue_protein_liability` → `_normaltissue_sig`, a three-arm
#       flag/breadth-fallback/TPHP-promotion OR whose fired arm is otherwise invisible downstream —
#       precisely the loss the envelope doc names). OMITTED on the other seven: their class token is read
#       VERBATIM off the card and the disjunct that produced it was decided upstream in `methods/` and is
#       not recoverable from the card summary. Emitting a fabricated `disjunct_fired` there would be worse
#       than omitting it. Piloted on ONE entry rather than declared universal on the strength of one pass
#       — 0c's discipline.
#       ⚠️ READING TO CONFIRM WITH THE OWNER (surfaced, not settled — it is what 1b–1e replicate):
#       `interpretation` here describes how THIS DOMAIN resolved the source into its liability read, not
#       how the card's own class token was produced. The entry's `property` stays the verbatim card class;
#       `function_id` names the skills-side resolver. The alternative reading — `interpretation` must
#       describe the resolution of the entry's own `property` — would make the field unemittable
#       everywhere in this domain, since every class token is a verbatim card read.

# The scale/unit slot for each retained quantitative anchor (envelope-v0: a raw value + its declared
# scale, never a `decision_weight`/`modality_relevance`). Absent → "raw".
_SAFETY_ANCHOR_SCALE = {
    # gnomAD constraint — each a different statistic, and the units are the whole point: pLI is a
    # posterior probability, LOEUF a ratio-with-CI, mis_z a z-score, and the obs/exp LoF pair are counts.
    "pli_score": "probability",
    "loeuf_score": "obs_exp_ratio_upper_bound",
    "mis_z_score": "z_score",
    "obs_lof_count": "variant_count",
    "exp_lof_count": "variant_count",
    # s_het — a selection coefficient with a 95% credible interval (GeneBayes posterior).
    "shet_score": "selection_coefficient",
    "shet_lower_95": "selection_coefficient",
    "shet_upper_95": "selection_coefficient",
    # population burden — an association p-value, NOT a q-value (the card does not FDR-correct).
    "min_pvalue": "nominal_p_value",
    # ClinVar / ClinGen / mouse-KO — row and variant COUNTS, never rates.
    "n_pathogenic_germline_confident": "variant_count",
    "n_pathogenic_germline": "variant_count",
    "n_lethal": "phenotype_row_count",
    "n_adult_lethal": "phenotype_row_count",
    "n_developmental_lethal": "phenotype_row_count",
    "n_high_confidence": "curated_assertion_count",
    "n_autosomal_dominant": "curated_assertion_count",
    "n_autosomal_recessive": "curated_assertion_count",
    # normal-tissue liability — tissue counts, a breadth FRACTION, and an absolute expression level.
    "n_essential_tissues_with_expression": "tissue_count",
    "n_specific_tissues": "tissue_count",
    "n_tissues_high": "tissue_count",
    "n_tissues_detectable": "tissue_count",
    "n_tissues_tested": "tissue_count",
    "tissue_breadth_fraction": "fraction",
    "critical_organ_max": "log2_tpm",
}

# Data-driven recipe (keyed by the L2a property name from the architecture's source_properties shape).
# `property_field` is the resolved observational class of that source; `anchors` are its retained
# quantitative anchors, in reading order; `context` fields are retained categorical/label qualifiers that
# orient the anchors but are not themselves quantities. Every `card_id`/`property_field`/anchor/context
# name below was verified against `contracts/cards/<card_id>.card.yaml` `outputs.summary_fields` — the
# plan's table carried `clinvar_n_pathogenic_germline_confident` (the HEADLINE-lifted name); the CARD
# field is `n_pathogenic_germline_confident` and that is what is read here.
#
# A source whose card is absent (or whose property class does not resolve) emits NO entry, and the whole
# `source_properties` key is omitted when nothing resolves — keeping a card-absent run byte-stable,
# matching the claim-axis + concordance atom discipline on this vector.
#
# NOT here, deliberately:
#   * DepMap pan-essentiality is NOT duplicated as a safety L2a property. It is the DEPENDENCY domain's
#     L2a property (1b/#2211), read at LIABILITY valence by this domain's PAN_ESSENTIAL axis. The shared
#     card is recorded in the catalog's `dependence_group`, so the sharing is declared rather than
#     re-minted — duplicating it would make one measurement look like two independent sources.
#   * PHARMACOVIGILANCE (drug-warning-safety / onsides-adverse-event-safety) is on/off-target CONFOUNDED
#     clinical CONTEXT, not an on-target observational property of the target. It is verdict-inert
#     context in the claim vector for that reason and is not an L2a biological property.
_SOURCE_PROPERTY_RECIPES_SAFETY = (
    {
        "name": "germline_lof_constraint",
        "card_id": "gnomad-lof-constraint",
        "property_field": "constraint_class",
        "anchors": ("pli_score", "loeuf_score", "mis_z_score", "obs_lof_count", "exp_lof_count"),
        "context": ("human_ko_observed_class",),
        "comparability": {
            "measurement_type": "gnomad_lof_constraint",
            "sample_context": "population_germline",
            "grain": "target",
            "valence": "liability",
        },
        # NO sample-N anchor: pLI/LOEUF/mis-z are per-gene MLE posteriors, not a sample size → n_effective
        # OMITTED, powered 'unmeasured'. (obs/exp LoF are variant counts describing the fit, not a cohort N.)
        "reliability": {"n_effective_anchor": None, "n_effective_absent_reason": "per_gene_constraint_mle"},
    },
    {
        "name": "dominant_lof_selection",
        "card_id": "shet-lof-intolerance",
        "property_field": "shet_class",
        "anchors": ("shet_score", "shet_lower_95", "shet_upper_95"),
        "context": (),
        "comparability": {
            "measurement_type": "shet_lof_selection",
            "sample_context": "population_germline",
            "grain": "target",
            "valence": "liability",
        },
        # NO sample-N anchor: s_het is a per-gene selection-coefficient MLE + credible interval, not a
        # sample size → n_effective OMITTED, powered 'unmeasured'.
        "reliability": {"n_effective_anchor": None, "n_effective_absent_reason": "per_gene_shet_mle"},
    },
    {
        "name": "population_burden_liability",
        "card_id": "gene-burden-safety",
        "property_field": "burden_safety_class",
        "anchors": ("min_pvalue",),
        "context": ("top_disease", "direction_on_target"),
        "comparability": {
            "measurement_type": "gene_burden_safety",
            "sample_context": "population_cohort",
            "grain": "target",
            "valence": "liability",
        },
        # NO sample-N anchor: the only anchor is min_pvalue (an association p-value), not a cohort size →
        # n_effective OMITTED, powered 'unmeasured'.
        "reliability": {"n_effective_anchor": None, "n_effective_absent_reason": "association_p_value"},
    },
    {
        "name": "germline_pathogenicity",
        "card_id": "clinvar-pathogenicity-safety",
        "property_field": "clinvar_pathogenic_class",
        "anchors": ("n_pathogenic_germline_confident", "n_pathogenic_germline"),
        "context": ("top_disease",),
        "comparability": {
            "measurement_type": "clinvar_germline_pathogenicity_safety",
            "sample_context": "clinical_germline",
            "grain": "target",
            "valence": "liability",
        },
        # n_effective = the review-status-filtered confident pathogenic count (the load-bearing anchor).
        "reliability": {"n_effective_anchor": "n_pathogenic_germline_confident"},
    },
    {
        "name": "dosage_sensitivity",
        "card_id": "clingen-dosage",
        "property_field": "dosage_sensitivity_class",
        "anchors": ("n_high_confidence", "n_autosomal_dominant", "n_autosomal_recessive"),
        "context": ("germline_inheritance_mode", "top_disease"),
        "comparability": {
            "measurement_type": "dosage_sensitivity_safety",
            "sample_context": "clinical_germline",
            "grain": "target",
            "valence": "liability",
        },
        # n_effective = the high-confidence curated-assertion count behind the dosage class.
        "reliability": {"n_effective_anchor": "n_high_confidence"},
    },
    {
        "name": "ko_organismal_phenotype",
        "card_id": "mouse-ko-phenotype",
        "property_field": "ko_phenotype_class",
        "anchors": ("n_lethal", "n_adult_lethal", "n_developmental_lethal"),
        "context": ("organ_classes", "impc_viability_class", "top_lethal_label"),
        "comparability": {
            "measurement_type": "mouse_ko_phenotype_safety",
            "sample_context": "model_organism",
            "grain": "target",
            "valence": "liability",
        },
        # NO sample-N anchor: n_lethal / n_adult_lethal / n_developmental_lethal are curated lethal-OUTCOME
        # counts (MP-term matches), not a sample size → n_effective OMITTED, powered 'unmeasured'.
        "reliability": {"n_effective_anchor": None, "n_effective_absent_reason": "lethal_outcome_counts"},
    },
    {
        "name": "normal_tissue_protein_liability",
        "card_id": "normal-tissue-liability",
        "property_field": "essential_tissue_flag",
        "anchors": ("n_essential_tissues_with_expression", "n_specific_tissues"),
        "context": ("normal_tissue_breadth_class", "hpa_tissue_specificity", "essential_tissues_flagged"),
        "comparability": {
            "measurement_type": "normal_tissue_protein_breadth",
            "sample_context": "normal_tissue",
            "grain": "target",
            "valence": "liability",
        },
        # NO sample-N anchor: n_essential_tissues_with_expression / n_specific_tissues are tissue-BREADTH
        # counts (how many tissues stained), not a sample size → n_effective OMITTED, powered 'unmeasured'.
        "reliability": {"n_effective_anchor": None, "n_effective_absent_reason": "tissue_breadth_counts"},
    },
    {
        "name": "normal_tissue_rna_liability",
        "card_id": "normal-tissue-liability-gtex",
        "property_field": "liability_class",
        "anchors": (
            "tissue_breadth_fraction",
            "n_tissues_high",
            "n_tissues_detectable",
            "n_tissues_tested",
            "critical_organ_max",
        ),
        "context": ("critical_organ_argmax", "highest_tissue"),
        "comparability": {
            "measurement_type": "normal_tissue_rna_breadth",
            "sample_context": "normal_tissue",
            "grain": "target",
            "valence": "liability",
        },
        # n_effective = the number of GTEx tissues TESTED (the denominator behind the breadth fraction).
        "reliability": {"n_effective_anchor": "n_tissues_tested"},
    },
)

_SAFETY_SKILL = "on-target-safety-liability"


# The three arms of `_normaltissue_sig`, as STABLE tokens. The function is a three-way OR whose fired arm
# is invisible from its returned tier alone: two different targets can both read `strong` because the HPA
# essential-tissue flag is `present`, or because TPHP quantified the protein in an organ HPA cannot see —
# a materially different piece of evidence behind the same word. This is the exact loss envelope v1.1 (ii)
# describes; `disjunct_fired` recovers it.
_NORMALTISSUE_INTERPRETATION_VERSION = "1.0.0"
_NORMALTISSUE_DISJUNCTS = (
    "essential_tissue_flag",  # arm 1 — the HPA-IHC flag resolved the tier
    "normal_tissue_breadth_fallback",  # arm 2 — flag indeterminate, MEASURED breadth carried it (#1546 era)
    "tphp_hpa_blind_vital_organ_promotion",  # arm 3 — #1793 promotion over the HPA-blind organ set
    "unmeasured",  # no arm resolved — a data GAP, never a clean read
)


def _normaltissue_interpretation(h) -> dict:
    """Which arm of `_normaltissue_sig`'s three-way disjunction produced this domain's normal-tissue
    liability read (envelope v1.1 (ii), FIRST live emission of the declared shape).

    Mirrors `_normaltissue_sig`'s precedence exactly rather than restating it: the promotion arm is
    reported when it is what LIFTED the tier (so it must both fire and out-rank what came before),
    otherwise the flag arm, otherwise the measured-breadth fallback, otherwise `unmeasured`."""
    flag_sig = _NORMALTISSUE_SIGNAL.get(h.get("essential_tissue_flag"), "unmeasured")
    pre_promotion = (
        flag_sig
        if flag_sig != "unmeasured"
        else _NORMALTISSUE_BREADTH_FALLBACK.get(h.get("normal_tissue_breadth_class"), "unmeasured")
    )
    if _tphp_blind_liability(h) and not sig_ge(pre_promotion, "strong"):
        fired = "tphp_hpa_blind_vital_organ_promotion"
    elif flag_sig != "unmeasured":
        fired = "essential_tissue_flag"
    elif pre_promotion != "unmeasured":
        fired = "normal_tissue_breadth_fallback"
    else:
        fired = "unmeasured"
    return {
        "function_id": "_skills_common.safety_claims._normaltissue_sig",
        "version": _NORMALTISSUE_INTERPRETATION_VERSION,
        "disjunct_fired": fired,
    }


# {property name: interpretation builder}. Present for the ONE entry this domain resolves through a
# multi-arm disjunction; absent everywhere else, where the class token is a verbatim card read whose
# producing disjunct was decided upstream in methods/ and is NOT recoverable from the card summary.
_SAFETY_INTERPRETATION_FNS = {"normal_tissue_protein_liability": _normaltissue_interpretation}


def _source_properties(h: dict, c: dict, *, skills_root=None) -> "dict | None":
    """The NAMED, typed L2a source_properties map for the SAFETY domain (PR-1a): one entry per
    source/grain, lifting the per-source observational properties out of the eight claim signal blocks
    into an explicit, recoverable object. Returns None when no source resolves (whole key omitted →
    byte-stable), matching the atom discipline on this vector. Pure projection, verdict-inert, carries no
    signal tier.

    Takes BOTH the headline and the cards-by-id map: the entries themselves are projected from the CARD
    summaries (`c`), while the `interpretation` provenance reports a disjunction evaluated over the
    HEADLINE (`h`) — the same input `_normaltissue_sig` reads in production, so the reported arm is the
    arm that actually fired rather than one re-derived from differently-named card fields.

    The recipe loop + the ledger-sourced `reach_map` / `typed_anchor` now live in the shared
    source_properties_core (#2373); safety passes its own recipe table + anchor-scale map + skill, and —
    uniquely — the `interpretation_fns` map (keyed on recipe name) that reports the normal-tissue
    disjunction arm evaluated over the headline `h`. The `property_field` is NAMED on each entry (a
    divergence from the presence reference) because `normal_tissue_protein_liability` reads
    `essential_tissue_flag`, whose bare `present` token is not self-describing without it; so every entry
    reconstructs to L1 as {card_id, property_field, property}."""
    return build_source_properties(
        c,
        _SOURCE_PROPERTY_RECIPES_SAFETY,
        anchor_scale=_SAFETY_ANCHOR_SCALE,
        skill=_SAFETY_SKILL,
        skills_root=skills_root,
        headline=h,
        interpretation_fns=_SAFETY_INTERPRETATION_FNS,
    )


SAFETY_CLAIM_SPEC = [
    ClaimSpec(
        "CONSTRAINT",
        "gnomAD LoF constraint",
        _constraint_signal,
        _constraint_corr,
        _INFORMS["CONSTRAINT"] + _LIABILITY_NOTE,
        _constraint_atom,
    ),
    ClaimSpec(
        "BURDEN",
        "population gene-burden",
        _burden_signal,
        _burden_corr,
        _INFORMS["BURDEN"] + _LIABILITY_NOTE,
        _burden_atom,
    ),
    ClaimSpec(
        "DOSAGE",
        "ClinGen dosage sensitivity",
        _dosage_signal,
        _dosage_corr,
        _INFORMS["DOSAGE"] + _LIABILITY_NOTE,
        _dosage_atom,
    ),
    ClaimSpec(
        "CLINVAR",
        "germline pathogenicity",
        _clinvar_signal,
        _clinvar_corr,
        _INFORMS["CLINVAR"] + _LIABILITY_NOTE,
        _clinvar_atom,
    ),
    ClaimSpec(
        "MOUSE_KO",
        "mouse-KO phenotype",
        _mouseko_signal,
        _mouseko_corr,
        _INFORMS["MOUSE_KO"] + _LIABILITY_NOTE,
        _mouseko_atom,
    ),
    ClaimSpec(
        "PAN_ESSENTIAL",
        "DepMap pan-essentiality",
        _paness_signal,
        _paness_corr,
        _INFORMS["PAN_ESSENTIAL"] + _LIABILITY_NOTE,
        _paness_atom,
    ),
    ClaimSpec(
        "NORMAL_TISSUE",
        "HPA-IHC essential-tissue protein",
        _normaltissue_signal,
        _normaltissue_corr,
        _INFORMS["NORMAL_TISSUE"] + _LIABILITY_NOTE,
        _normaltissue_atom,
    ),
    # verdict-INERT clinical pharmacovigilance CONTEXT (2026-09-04) — surfaces the on-target toxicity classes
    # / boxed-warning ADEs the capsule projection carried but the narrator never led with. Confounded →
    # corroboration capped, never a resolver HOLD (see _pharmacovigilance_signal). Left OUT of the safety
    # HeadlineSpec.axis_keys so headline_block/confidence/hero stay byte-stable.
    ClaimSpec(
        "PHARMACOVIGILANCE",
        "on-target clinical pharmacovigilance",
        _pharmacovigilance_signal,
        _pharmacovigilance_corr,
        _INFORMS["PHARMACOVIGILANCE"] + _CONTEXT_NOTE,
        _pharmacovigilance_atom,
    ),
]

_DISCLAIMER = (
    "Modality-blind, verdict-INERT projection of the on-target-safety cards into orthogonal LIABILITY "
    "claims (CONSTRAINT / BURDEN / DOSAGE / CLINVAR / MOUSE_KO / PAN_ESSENTIAL / NORMAL_TISSUE + the "
    "confounded clinical-PHARMACOVIGILANCE context axis), each "
    "signal×corroboration. INVERSE "
    "valence: a strong signal is a safety CONCERN, not a win; a measured tolerant read is `absent`; a "
    "protective burden is `negative`. Claims are NOT averaged. Never feeds the safety verdict (owned by "
    "the shared safety resolver) — PHARMACOVIGILANCE is doubly inert (on/off-target-confounded CONTEXT that "
    "orients, never holds). The mutant-selective-GoF WT-loss downgrade is MODALITY-CONDITIONAL — "
    "realised in the per-modality safety verdict (safety_verdict_by_modality), not the scalar verdict."
)


def safety_claim_vector(headline: dict, cards: list) -> dict:
    """The verdict-INERT safety liability claim vector {CONSTRAINT,BURDEN,DOSAGE,CLINVAR,MOUSE_KO,
    PAN_ESSENTIAL,NORMAL_TISSUE: {signal, corroboration, evidence, conflict, informs, evidence_atom?},
    _disclaimer}."""
    vec = build_claim_vector(SAFETY_CLAIM_SPEC, headline, cards, _DISCLAIMER)
    # L2b-3 cross-source integration claim (SK#1546): GTEx bulk × scRNA-normal × HPA-IHC normal-tissue
    # liability concordance. Carries NO `signal` key → not a chip, not a tier; OMITTED (byte-stable) unless
    # at least ONE source resolves — the full concordance/discordance read needs >=2. Reads the three source
    # cards directly (the NORMAL_TISSUE axis reads HPA off the headline + GTEx as one corroboration arm; this
    # integrates all three independently and never perturbs them). Mirrors the dependency L2b-2
    # (`crispr_rnai_essentiality_concordance`) pattern.
    _c = cards_by_id(cards)
    _liab = _normal_liability_concordance_claim(_c)
    if _liab is not None:
        vec["normal_liability_concordance"] = _liab
    # L2a NAMED source_properties map (PR-1a, #2210): the per-source observational properties lifted out
    # of the eight claim signal blocks into a named, typed, L1-reconstructable object. Carries NO `signal`
    # key on any entry → not a chip, not a tier, read by no rule/verdict/ladder. OMITTED entirely
    # (byte-stable) when no source resolves, matching the concordance-claim discipline directly above.
    _props = _source_properties(headline, _c)
    if _props is not None:
        vec["source_properties"] = _props
    return vec


def safety_key_signals(headline: dict, cards: list) -> dict:
    """A brief, deterministic, CITED read over the safety liability vector (available without the LLM)."""
    vec = safety_claim_vector(headline, cards)
    h = headline

    def sup(k):
        lbl = {
            "CONSTRAINT": f"LoF-constrained (pLI {_f(h.get('pli_score'))}, LOEUF {_f(h.get('loeuf_score'))}) [gnomad-lof-constraint]",
            "BURDEN": f"Population LoF-risk phenotype ({h.get('burden_top_disease')}) [gene-burden-safety]",
            "DOSAGE": f"Haploinsufficient / dosage-sensitive ({h.get('germline_inheritance_mode')}) [clingen-dosage]",
            "CLINVAR": f"Germline-pathogenic variants ({h.get('clinvar_top_disease')}) [clinvar-pathogenicity-safety]",
            "MOUSE_KO": f"KO phenotype: {h.get('mouse_ko_phenotype_class')} ({h.get('mouse_ko_top_lethal')}) [mouse-ko-phenotype]",
            "PAN_ESSENTIAL": f"Pan-essential: {h.get('dependency_class')} (broad normal-tissue tox) [pan-cancer-crispr-dependency-distribution]",
            # #1793: when the TPHP HPA-blind arm carries the liability (HPA flag not `present`), the
            # leading label must NAME the blind organs and cite the card that measured them; the HPA
            # label (and its citation) is byte-stable whenever the HPA arm fires or the field is absent.
            "NORMAL_TISSUE": (
                f"Vital-organ protein in HPA-blind organ(s) {h.get('hpa_blind_vital_organs_above_floor')} "
                "[normal-tissue-protein-abundance-tphp]"
                if _tphp_blind_liability(h) and h.get("essential_tissue_flag") != "present"
                else f"Essential-tissue protein ({h.get('essential_tissues_flagged')}) [normal-tissue-liability]"
            ),
            "PHARMACOVIGILANCE": f"On-target clinical warnings: {h.get('drug_warning_class')} ({h.get('drug_warning_toxicity_classes')}) [drug-warning-safety]",
        }
        return lambda claim: lbl.get(k)

    _KEYS = (
        "CONSTRAINT",
        "BURDEN",
        "DOSAGE",
        "CLINVAR",
        "MOUSE_KO",
        "PAN_ESSENTIAL",
        "NORMAL_TISSUE",
        "PHARMACOVIGILANCE",
    )
    return build_key_signals(
        vec,
        rank_keys=_KEYS,
        support_fns={k: sup(k) for k in _KEYS},
        critical_keys=("CONSTRAINT", "BURDEN", "DOSAGE", "PAN_ESSENTIAL"),
        caveat_fns={},
        headline_fn=lambda v, s: (
            "Human-genetics safety LIABILITY present."
            if s
            else "No strong safety liability signal (or largely unmeasured)."
        ),
        fallback_caveat_fn=lambda: None,
    )


__all__ = ["safety_claim_vector", "safety_key_signals", "SAFETY_CLAIM_SPEC"]
