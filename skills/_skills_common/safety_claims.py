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


def _normaltissue_sig(h) -> str:
    """Resolved NORMAL_TISSUE liability signal: essential-tissue flag first, else measured breadth."""
    sig = _NORMALTISSUE_SIGNAL.get(h.get("essential_tissue_flag"), "unmeasured")
    if sig == "unmeasured":
        sig = _NORMALTISSUE_BREADTH_FALLBACK.get(h.get("normal_tissue_breadth_class"), "unmeasured")
    return sig


def _normaltissue_signal(h, c):
    ev = (
        f"HPA-IHC: essential_tissue_flag={h.get('essential_tissue_flag') or 'data_unavailable'}, "
        f"tissues={h.get('essential_tissues_flagged')}, breadth={h.get('normal_tissue_breadth_class')}"
    )
    return _normaltissue_sig(h), ev, None


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
_LIAB_SC_HIGH = frozenset({"HIGH_LIABILITY"})
_LIAB_SC_CLEAN = frozenset({"LOW_LIABILITY", "NOT_EXPRESSED"})
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
        "sc_normal_expression_class",
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
    MODERATE_LIABILITY) is a TRUTHY string that must stay OUT of the resolved buckets.

    scRNA `MODERATE_LIABILITY` deliberately ABSTAINS: its threshold (median_det>0.20 OR donor_frac>0.30)
    does NOT line up with the GTEx tissue-breadth `moderate_normal_breadth` (a CLEAN narrow-window call),
    so voting it either way would fabricate a cross-source (dis)agreement. It abstains; its raw token
    still rides in the payload (recoverable)."""
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
      * scRNA cell-type (sc-normal-celltype-expression.sc_normal_expression_class) — single-cell atlas
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
    per-modality safety verdicts stay byte-stable. Returns None — key omitted — when NO source resolves."""
    raw = {sk: (c.get(cid) or {}).get(field) for sk, _prop, _assay, cid, field in _LIAB_SOURCES}
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
    return {
        "concordance_class": concordance,
        "corroboration": corroboration,
        # DETERMINISTIC, reproducible-by-contract: an explicit rule over three tokens, never an LLM.
        "integration_method": "explicit_deterministic",
        "source_support": source_support,
        "sources_resolved": sorted(resolved),
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
                {"property": prop, "assay": assay, "card_id": cid, "fields": {field: raw[sk]}}
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


def _atom(card_id, summary, keys, entity, read):
    return build_summary_atom(card_id=card_id, summary=summary, keys=keys, read=read, entity=entity)


def _constraint_atom(h, c):
    cid = "gnomad-lof-constraint"
    return _atom(
        cid,
        c.get(cid) or {},
        ("constraint_class", "pli_score", "loeuf_score", "mis_z_score", "obs_lof_count", "exp_lof_count"),
        {"measurement_type": "gnomad_lof_constraint", "grain": "target", "valence": "liability"},
        (c.get(cid) or {}).get("constraint_class"),
    )


def _burden_atom(h, c):
    cid = "gene-burden-safety"
    return _atom(
        cid,
        c.get(cid) or {},
        ("burden_safety_class", "min_pvalue", "top_disease"),
        {"measurement_type": "gene_burden_safety", "grain": "target", "valence": "liability"},
        (c.get(cid) or {}).get("burden_safety_class"),
    )


def _dosage_atom(h, c):
    cid = "clingen-dosage"
    return _atom(
        cid,
        c.get(cid) or {},
        ("dosage_sensitivity_class", "germline_inheritance_mode", "top_disease"),
        {"measurement_type": "dosage_sensitivity_safety", "grain": "target", "valence": "liability"},
        (c.get(cid) or {}).get("dosage_sensitivity_class"),
    )


def _clinvar_atom(h, c):
    cid = "clinvar-pathogenicity-safety"
    return _atom(
        cid,
        c.get(cid) or {},
        ("clinvar_pathogenic_class", "top_disease"),
        {"measurement_type": "clinvar_germline_pathogenicity_safety", "grain": "target", "valence": "liability"},
        (c.get(cid) or {}).get("clinvar_pathogenic_class"),
    )


def _mouseko_atom(h, c):
    cid = "mouse-ko-phenotype"
    return _atom(
        cid,
        c.get(cid) or {},
        ("ko_phenotype_class", "top_lethal_label"),
        {"measurement_type": "mouse_ko_phenotype_safety", "grain": "target", "valence": "liability"},
        (c.get(cid) or {}).get("ko_phenotype_class"),
    )


def _paness_atom(h, c):
    cid = "pan-cancer-crispr-dependency-distribution"
    return _atom(
        cid,
        c.get(cid) or {},
        ("dependency_class", "pan_essential_score", "distribution_shape"),
        {"measurement_type": "crispr_lof_dependency", "grain": "target", "valence": "liability"},
        (c.get(cid) or {}).get("dependency_class"),
    )


def _normaltissue_atom(h, c):
    cid = "normal-tissue-liability"
    return _atom(
        cid,
        c.get(cid) or {},
        ("essential_tissue_flag", "essential_tissues_flagged", "normal_tissue_breadth_class"),
        {"measurement_type": "normal_tissue_protein_breadth", "grain": "target", "valence": "liability"},
        (c.get(cid) or {}).get("essential_tissue_flag"),
    )


def _pharmacovigilance_atom(h, c):
    cid = "drug-warning-safety"
    return _atom(
        cid,
        c.get(cid) or {},
        ("drug_warning_class", "has_black_box", "toxicity_classes", "warning_types", "n_targeted_warned_drugs"),
        {"measurement_type": "drug_warning_safety", "grain": "target", "valence": "liability"},
        (c.get(cid) or {}).get("drug_warning_class"),
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
    _liab = _normal_liability_concordance_claim(cards_by_id(cards))
    if _liab is not None:
        vec["normal_liability_concordance"] = _liab
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
            "NORMAL_TISSUE": f"Essential-tissue protein ({h.get('essential_tissues_flagged')}) [normal-tissue-liability]",
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
