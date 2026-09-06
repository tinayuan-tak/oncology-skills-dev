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

from _skills_common.claim_vector_core import (ClaimSpec, build_claim_vector, build_key_signals,
                                              cap_corroboration, sig_ge)

# ── enum → LIABILITY tier maps (grounded in the target-contracts card summary_fields_vocabulary) ────
_CONSTRAINT_SIGNAL = {
    "highly_constrained": "strong", "moderately_constrained": "moderate",
    "tolerant": "absent",                    # MEASURED: LoF-tolerant → no constraint concern
    "indeterminate": "unmeasured",
}
_BURDEN_SIGNAL = {
    "lof_risk_phenotype": "strong", "direction_unresolved": "weak",
    "protective": "negative",                # MEASURED opposite direction (LoF protective) → not a liability
    "no_burden_signal": "absent", "insufficient": "unmeasured",
}
_DOSAGE_SIGNAL = {
    "autosomal_dominant_loss": "strong",     # haploinsufficiency
    "unresolved": "weak", "dosage_sufficient": "absent",
    "no_clingen_entry": "unmeasured", "insufficient": "unmeasured",
}
_CLINVAR_SIGNAL = {
    "germline_pathogenic": "strong", "germline_pathogenic_low_review": "moderate",
    "somatic_only": "weak",                  # somatic, not germline-LoF → weaker on-target-safety read
    "no_pathogenic_signal": "absent", "no_clinvar_entry": "unmeasured", "insufficient": "unmeasured",
}
_MOUSEKO_SIGNAL = {
    "lethal_ko": "strong", "severe_organ_phenotype": "strong",
    "developmental_only": "moderate",        # developmental lethality — less relevant to adult dosing
    "mild_phenotype": "weak", "no_phenotype": "absent", "insufficient": "unmeasured",
}
# DepMap pan-essentiality as a BROAD-TOX liability (data-util expansion 2026-08-21): common_essential =
# required across the whole panel → a full-KO agent kills normal cells too. A SELECTIVE dependency
# (strongly_selective / non_dependent) is `absent` here — that is a therapeutic WINDOW, not a safety
# concern. Underpowered rungs are a coverage gap.
_PANESS_SIGNAL = {
    "common_essential": "strong",
    "broadly_dependent": "moderate",          # dependent in many (not pan) lineages — partial breadth
    "common_essential_underpowered": "weak",
    "strongly_selective": "absent",           # MEASURED: selective → a window exists (not a broad-tox liability)
    "non_dependent": "absent", "non_dependent_underpowered": "unmeasured",
    "data_unavailable": "unmeasured",
}
# HPA-IHC essential-tissue protein liability (data-util expansion 2026-08-21): protein detected in a
# curated essential normal tissue → on-target-off-tumor tox for a full-KO SM/degrader. Scalar flag.
_NORMALTISSUE_SIGNAL = {
    "present": "strong",                      # essential-tissue protein expression
    "absent": "absent",                       # MEASURED: no essential-tissue expression
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
    "withdrawn_drug":    "strong",            # an engaging drug was WITHDRAWN (strongest pharmacovigilance flag)
    "black_box_warned":  "strong",            # an engaging drug carries an FDA black-box warning
    "other_warning":     "moderate",          # engaging drug(s) warned, neither withdrawn nor black-box
    "no_warning":        "absent",            # MEASURED: engaging drug(s) exist, none warned
    "no_targeted_drug":  "unmeasured",        # coverage gap: no OT-MoA drug engages the target
    "insufficient":      "unmeasured",
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
        conflict = ("activating (GoF) driver: the WT LoF-constraint concern is MODALITY-CONDITIONAL — an "
                    "allele-selective small molecule may spare WT protein (see the per-modality safety "
                    "verdict); the scalar safety verdict is the raw concern and is NOT downgraded")
    ev = (f"gnomAD: {cls or 'data_unavailable'}, pLI={_f(h.get('pli_score'))}, LOEUF={_f(h.get('loeuf_score'))}, "
          f"obs/exp LoF={h.get('obs_lof_count')}/{_f(h.get('exp_lof_count'), 1)}")
    return sig, ev, conflict


def _constraint_corr(h, c):
    if _CONSTRAINT_SIGNAL.get(h.get("constraint_class"), "unmeasured") == "unmeasured":
        return "unmeasured"
    # pLI + LOEUF present = a well-powered constraint read
    return "high" if isinstance(h.get("pli_score"), (int, float)) and isinstance(h.get("loeuf_score"), (int, float)) else "moderate"


def _burden_signal(h, c):
    cls = h.get("burden_safety_class")
    ev = f"gene-burden: {cls or 'data_unavailable'}, min_p={h.get('burden_min_pvalue')}, disease={h.get('burden_top_disease')}"
    return _BURDEN_SIGNAL.get(cls, "unmeasured"), ev, None


def _burden_corr(h, c):
    if _BURDEN_SIGNAL.get(h.get("burden_safety_class"), "unmeasured") == "unmeasured":
        return "unmeasured"
    p = h.get("burden_min_pvalue")
    return "high" if isinstance(p, (int, float)) and p < 1e-6 else "moderate" if isinstance(p, (int, float)) else "low"


def _dosage_signal(h, c):
    cls = h.get("dosage_sensitivity_class")
    ev = f"ClinGen dosage: {cls or 'data_unavailable'}, inheritance={h.get('germline_inheritance_mode')}"
    return _DOSAGE_SIGNAL.get(cls, "unmeasured"), ev, None


def _dosage_corr(h, c):
    return "moderate" if _DOSAGE_SIGNAL.get(h.get("dosage_sensitivity_class"), "unmeasured") != "unmeasured" else "unmeasured"


def _clinvar_signal(h, c):
    cls = h.get("clinvar_pathogenic_class")
    ev = f"ClinVar: {cls or 'data_unavailable'}, disease={h.get('clinvar_top_disease')}"
    # Surface the confident germline-pathogenic variant COUNT — the rich sub-field the capsule projection
    # ignored (was class + top_disease only). "N confident germline-pathogenic variants" is far more
    # informative than the bare `germline_pathogenic` class for a clinical LoF-liability read.
    n = h.get("clinvar_n_pathogenic_germline_confident")
    if isinstance(n, int) and n > 0:
        ev += f", confident-germline-pathogenic-variants={n}"
    return _CLINVAR_SIGNAL.get(cls, "unmeasured"), ev, None


def _clinvar_corr(h, c):
    return "moderate" if _CLINVAR_SIGNAL.get(h.get("clinvar_pathogenic_class"), "unmeasured") != "unmeasured" else "unmeasured"


def _mouseko_signal(h, c):
    cls = h.get("mouse_ko_phenotype_class")
    ev = f"mouse-KO: {cls or 'data_unavailable'}, lethal={h.get('mouse_ko_top_lethal')}"
    # Surface the affected ORGAN SYSTEMS — the rich sub-field the capsule projection ignored (was class +
    # top_lethal_label only). Which organ systems a KO perturbs (hematopoietic / cardiovascular / etc.) is
    # the safety-relevant detail beneath a bare `lethal_ko`.
    organs = h.get("mouse_ko_organ_systems")
    if organs:
        ev += f", organ-systems={list(organs) if not isinstance(organs, str) else organs}"
    return _MOUSEKO_SIGNAL.get(cls, "unmeasured"), ev, None


def _mouseko_corr(h, c):
    return "moderate" if _MOUSEKO_SIGNAL.get(h.get("mouse_ko_phenotype_class"), "unmeasured") != "unmeasured" else "unmeasured"


def _paness_signal(h, c):
    cls = h.get("dependency_class")
    sig = _PANESS_SIGNAL.get(cls, "unmeasured")
    conflict = None
    # mechanism conditioning (mirrors CONSTRAINT): for a mutant-selective GoF, WT-sparing makes the
    # broad-tox concern MODALITY-CONDITIONAL. Retired from the scalar verdict; now per-modality only.
    if sig_ge(sig, "moderate") and h.get("alteration_functional_direction") == "activating":
        conflict = ("activating (GoF) driver: the broad-tox pan-essential concern is MODALITY-CONDITIONAL — "
                    "an allele-selective small molecule may spare WT in normal tissue (see the per-modality "
                    "safety verdict); the scalar safety verdict is the raw concern and is NOT downgraded")
    ev = f"DepMap: {cls or 'data_unavailable'}, pan_essential_score={_f(h.get('pan_essential_score'))}"
    return sig, ev, conflict


def _paness_corr(h, c):
    return "high" if _PANESS_SIGNAL.get(h.get("dependency_class"), "unmeasured") not in ("unmeasured",) else "unmeasured"


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
    ev = (f"HPA-IHC: essential_tissue_flag={h.get('essential_tissue_flag') or 'data_unavailable'}, "
          f"tissues={h.get('essential_tissues_flagged')}, breadth={h.get('normal_tissue_breadth_class')}")
    return _normaltissue_sig(h), ev, None


def _normaltissue_corr(h, c):
    return "moderate" if _normaltissue_sig(h) != "unmeasured" else "unmeasured"


_PHARMACOVIGILANCE_CAVEAT = (
    "CONFOUNDED on-target-vs-off-target (drug-name→gene join, class-wide recall) — pharmacovigilance "
    "CONTEXT that ORIENTS the reader; the scalar safety verdict does not read it")


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
    measured = (_PHARMACOVIGILANCE_SIGNAL.get(h.get("drug_warning_class"), "unmeasured") != "unmeasured"
                or bool(h.get("onsides_has_boxed_warning")))
    # CAP at `moderate` — the on/off-target confound means a black-box hit is never a high-corroboration read.
    return "moderate" if measured else "unmeasured"


# ── citable evidence atoms (read from the source card summaries; cite each card) ────────────────────
from _skills_common.claim_vector_core import build_summary_atom  # shared atom builder (Group D)


def _atom(card_id, summary, keys, entity, read):
    return build_summary_atom(card_id=card_id, summary=summary, keys=keys, read=read, entity=entity)


def _constraint_atom(h, c):
    cid = "gnomad-lof-constraint"
    return _atom(cid, c.get(cid) or {},
                 ("constraint_class", "pli_score", "loeuf_score", "mis_z_score",
                  "obs_lof_count", "exp_lof_count"),
                 {"measurement_type": "gnomad_lof_constraint", "grain": "target", "valence": "liability"},
                 (c.get(cid) or {}).get("constraint_class"))


def _burden_atom(h, c):
    cid = "gene-burden-safety"
    return _atom(cid, c.get(cid) or {}, ("burden_safety_class", "min_pvalue", "top_disease"),
                 {"measurement_type": "gene_burden_safety", "grain": "target", "valence": "liability"},
                 (c.get(cid) or {}).get("burden_safety_class"))


def _dosage_atom(h, c):
    cid = "clingen-dosage"
    return _atom(cid, c.get(cid) or {}, ("dosage_sensitivity_class", "germline_inheritance_mode", "top_disease"),
                 {"measurement_type": "dosage_sensitivity_safety", "grain": "target", "valence": "liability"},
                 (c.get(cid) or {}).get("dosage_sensitivity_class"))


def _clinvar_atom(h, c):
    cid = "clinvar-pathogenicity-safety"
    return _atom(cid, c.get(cid) or {}, ("clinvar_pathogenic_class", "top_disease"),
                 {"measurement_type": "clinvar_germline_pathogenicity_safety", "grain": "target", "valence": "liability"},
                 (c.get(cid) or {}).get("clinvar_pathogenic_class"))


def _mouseko_atom(h, c):
    cid = "mouse-ko-phenotype"
    return _atom(cid, c.get(cid) or {}, ("ko_phenotype_class", "top_lethal_label"),
                 {"measurement_type": "mouse_ko_phenotype_safety", "grain": "target", "valence": "liability"},
                 (c.get(cid) or {}).get("ko_phenotype_class"))


def _paness_atom(h, c):
    cid = "pan-cancer-crispr-dependency-distribution"
    return _atom(cid, c.get(cid) or {}, ("dependency_class", "pan_essential_score", "distribution_shape"),
                 {"measurement_type": "crispr_lof_dependency", "grain": "target", "valence": "liability"},
                 (c.get(cid) or {}).get("dependency_class"))


def _normaltissue_atom(h, c):
    cid = "normal-tissue-liability"
    return _atom(cid, c.get(cid) or {}, ("essential_tissue_flag", "essential_tissues_flagged", "normal_tissue_breadth_class"),
                 {"measurement_type": "normal_tissue_protein_breadth", "grain": "target", "valence": "liability"},
                 (c.get(cid) or {}).get("essential_tissue_flag"))


def _pharmacovigilance_atom(h, c):
    cid = "drug-warning-safety"
    return _atom(cid, c.get(cid) or {}, ("drug_warning_class", "has_black_box", "toxicity_classes",
                                         "warning_types", "n_targeted_warned_drugs"),
                 {"measurement_type": "drug_warning_safety", "grain": "target", "valence": "liability"},
                 (c.get(cid) or {}).get("drug_warning_class"))


SAFETY_CLAIM_SPEC = [
    ClaimSpec("CONSTRAINT", "gnomAD LoF constraint", _constraint_signal, _constraint_corr, _INFORMS["CONSTRAINT"] + _LIABILITY_NOTE, _constraint_atom),
    ClaimSpec("BURDEN", "population gene-burden", _burden_signal, _burden_corr, _INFORMS["BURDEN"] + _LIABILITY_NOTE, _burden_atom),
    ClaimSpec("DOSAGE", "ClinGen dosage sensitivity", _dosage_signal, _dosage_corr, _INFORMS["DOSAGE"] + _LIABILITY_NOTE, _dosage_atom),
    ClaimSpec("CLINVAR", "germline pathogenicity", _clinvar_signal, _clinvar_corr, _INFORMS["CLINVAR"] + _LIABILITY_NOTE, _clinvar_atom),
    ClaimSpec("MOUSE_KO", "mouse-KO phenotype", _mouseko_signal, _mouseko_corr, _INFORMS["MOUSE_KO"] + _LIABILITY_NOTE, _mouseko_atom),
    ClaimSpec("PAN_ESSENTIAL", "DepMap pan-essentiality", _paness_signal, _paness_corr, _INFORMS["PAN_ESSENTIAL"] + _LIABILITY_NOTE, _paness_atom),
    ClaimSpec("NORMAL_TISSUE", "HPA-IHC essential-tissue protein", _normaltissue_signal, _normaltissue_corr, _INFORMS["NORMAL_TISSUE"] + _LIABILITY_NOTE, _normaltissue_atom),
    # verdict-INERT clinical pharmacovigilance CONTEXT (2026-09-04) — surfaces the on-target toxicity classes
    # / boxed-warning ADEs the capsule projection carried but the narrator never led with. Confounded →
    # corroboration capped, never a resolver HOLD (see _pharmacovigilance_signal). Left OUT of the safety
    # HeadlineSpec.axis_keys so headline_block/confidence/hero stay byte-stable.
    ClaimSpec("PHARMACOVIGILANCE", "on-target clinical pharmacovigilance", _pharmacovigilance_signal, _pharmacovigilance_corr, _INFORMS["PHARMACOVIGILANCE"] + _CONTEXT_NOTE, _pharmacovigilance_atom),
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
    "realised in the per-modality safety verdict (safety_verdict_by_modality), not the scalar verdict.")


def safety_claim_vector(headline: dict, cards: list) -> dict:
    """The verdict-INERT safety liability claim vector {CONSTRAINT,BURDEN,DOSAGE,CLINVAR,MOUSE_KO,
    PAN_ESSENTIAL,NORMAL_TISSUE: {signal, corroboration, evidence, conflict, informs, evidence_atom?},
    _disclaimer}."""
    return build_claim_vector(SAFETY_CLAIM_SPEC, headline, cards, _DISCLAIMER)


def safety_key_signals(headline: dict, cards: list) -> dict:
    """A brief, deterministic, CITED read over the safety liability vector (available without the LLM)."""
    vec = safety_claim_vector(headline, cards)
    h = headline

    def sup(k):
        lbl = {"CONSTRAINT": f"LoF-constrained (pLI {_f(h.get('pli_score'))}, LOEUF {_f(h.get('loeuf_score'))}) [gnomad-lof-constraint]",
               "BURDEN": f"Population LoF-risk phenotype ({h.get('burden_top_disease')}) [gene-burden-safety]",
               "DOSAGE": f"Haploinsufficient / dosage-sensitive ({h.get('germline_inheritance_mode')}) [clingen-dosage]",
               "CLINVAR": f"Germline-pathogenic variants ({h.get('clinvar_top_disease')}) [clinvar-pathogenicity-safety]",
               "MOUSE_KO": f"KO phenotype: {h.get('mouse_ko_phenotype_class')} ({h.get('mouse_ko_top_lethal')}) [mouse-ko-phenotype]",
               "PAN_ESSENTIAL": f"Pan-essential: {h.get('dependency_class')} (broad normal-tissue tox) [pan-cancer-crispr-dependency-distribution]",
               "NORMAL_TISSUE": f"Essential-tissue protein ({h.get('essential_tissues_flagged')}) [normal-tissue-liability]",
               "PHARMACOVIGILANCE": f"On-target clinical warnings: {h.get('drug_warning_class')} ({h.get('drug_warning_toxicity_classes')}) [drug-warning-safety]"}
        return lambda claim: lbl.get(k)

    _KEYS = ("CONSTRAINT", "BURDEN", "DOSAGE", "CLINVAR", "MOUSE_KO", "PAN_ESSENTIAL", "NORMAL_TISSUE",
             "PHARMACOVIGILANCE")
    return build_key_signals(
        vec, rank_keys=_KEYS,
        support_fns={k: sup(k) for k in _KEYS},
        critical_keys=("CONSTRAINT", "BURDEN", "DOSAGE", "PAN_ESSENTIAL"),
        caveat_fns={}, headline_fn=lambda v, s: (
            "Human-genetics safety LIABILITY present." if s else
            "No strong safety liability signal (or largely unmeasured)."),
        fallback_caveat_fn=lambda: None)


__all__ = ["safety_claim_vector", "safety_key_signals", "SAFETY_CLAIM_SPEC"]
