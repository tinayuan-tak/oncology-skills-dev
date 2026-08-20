"""safety_claims — on-target-safety-liability's CLAIM VECTOR + KEY SIGNALS: a verdict-INERT projection
of the human-genetics safety cards into (signal × corroboration) per orthogonal claim.

The FIFTH concrete instance of the shared claim_vector_core contract (dependency / genomic / selectivity
/ presence are the first four). Declares five safety axes as a ClaimSpec list:

  CONSTRAINT gnomAD LoF constraint    — pLI / LOEUF / obs-vs-exp LoF; the core LoF-intolerance signal.
  BURDEN     population gene-burden   — Open Targets LoF-risk-phenotype vs protective.
  DOSAGE     ClinGen dosage           — haploinsufficiency (autosomal-dominant loss).
  CLINVAR    germline pathogenicity   — germline-pathogenic variant burden.
  MOUSE_KO   mouse-KO phenotype       — lethality / severe-organ phenotype on knockout.

LIABILITY SEMANTICS (inverse-valence, like selectivity's SAFE axis): a STRONG signal here is a strong
safety CONCERN (LoF-intolerant / risk phenotype / haploinsufficient / pathogenic / KO-lethal), NOT a
good thing. A MEASURED tolerant read (LoF-tolerant, dosage-sufficient, no-phenotype) is `absent`
(measured negative concern); a burden that is PROTECTIVE is `negative` (measured opposite direction).
`unmeasured` (indeterminate / no-entry / insufficient) is a data GAP, never evidence of safety.

MECHANISM CONDITIONING: the safety VERDICT downgrades the WT-constraint concern for a mutant-selective
GoF (alteration-role functional_direction=activating) — a mutant-selective agent need not fully inhibit
the WT gene. This projection surfaces that as a CONSTRAINT `conflict`; it never re-computes the verdict
(owned by the shared safety resolver). Verdict-INERT: reads the ALREADY-computed safety _headline; the
EGFR/FLT3 replay guards freeze the safety verdict byte-stable with or without this.
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

_INFORMS = {
    "CONSTRAINT": "LoF constraint — the core on-target LoF-tolerance signal (degrader / full-KO risk)",
    "BURDEN": "population gene-burden — human-genetics LoF phenotype risk",
    "DOSAGE": "dosage sensitivity — haploinsufficiency (partial-inhibition risk)",
    "CLINVAR": "germline pathogenicity — clinical LoF-variant evidence",
    "MOUSE_KO": "mouse-KO phenotype — organismal essentiality of loss",
}
# EVERY claim is a LIABILITY: a strong signal is a RISK the safety VERDICT owns, not a nomination win.
_LIABILITY_NOTE = " (LIABILITY — a strong signal is a safety CONCERN; verdict owned by the safety resolver)"


def _f(v, nd=2):
    return f"{v:.{nd}f}" if isinstance(v, (int, float)) else "n/a"


# ── the five claims (signal_fn -> (tier, evidence, conflict); corroboration_fn -> tier) ────────────
def _constraint_signal(h, c):
    cls = h.get("constraint_class")
    sig = _CONSTRAINT_SIGNAL.get(cls, "unmeasured")
    conflict = None
    # mechanism conditioning: a mutant-selective GoF downgrades the WT-constraint concern (the verdict
    # applies this; surfaced here as a tension, tier unchanged — this is the SIGNAL, not the verdict).
    if sig_ge(sig, "moderate") and h.get("alteration_functional_direction") == "activating":
        conflict = ("WT LoF-constraint concern is DOWNGRADED for a mutant-selective / activating-GoF "
                    "mechanism — a mutant-selective agent need not fully inhibit WT (see safety verdict)")
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
    return _CLINVAR_SIGNAL.get(cls, "unmeasured"), ev, None


def _clinvar_corr(h, c):
    return "moderate" if _CLINVAR_SIGNAL.get(h.get("clinvar_pathogenic_class"), "unmeasured") != "unmeasured" else "unmeasured"


def _mouseko_signal(h, c):
    cls = h.get("mouse_ko_phenotype_class")
    ev = f"mouse-KO: {cls or 'data_unavailable'}, lethal={h.get('mouse_ko_top_lethal')}"
    return _MOUSEKO_SIGNAL.get(cls, "unmeasured"), ev, None


def _mouseko_corr(h, c):
    return "moderate" if _MOUSEKO_SIGNAL.get(h.get("mouse_ko_phenotype_class"), "unmeasured") != "unmeasured" else "unmeasured"


# ── citable evidence atoms (read from the source card summaries; cite each card) ────────────────────
def _atom(card_id, summary, keys, entity, read):
    vals = {k: summary[k] for k in keys if summary.get(k) is not None}
    if not vals:
        return None
    return {"read": read, "values": vals, "cite": {"card_id": card_id, "fields": sorted(vals)}, "entity": entity}


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


SAFETY_CLAIM_SPEC = [
    ClaimSpec("CONSTRAINT", "gnomAD LoF constraint", _constraint_signal, _constraint_corr, _INFORMS["CONSTRAINT"] + _LIABILITY_NOTE, _constraint_atom),
    ClaimSpec("BURDEN", "population gene-burden", _burden_signal, _burden_corr, _INFORMS["BURDEN"] + _LIABILITY_NOTE, _burden_atom),
    ClaimSpec("DOSAGE", "ClinGen dosage sensitivity", _dosage_signal, _dosage_corr, _INFORMS["DOSAGE"] + _LIABILITY_NOTE, _dosage_atom),
    ClaimSpec("CLINVAR", "germline pathogenicity", _clinvar_signal, _clinvar_corr, _INFORMS["CLINVAR"] + _LIABILITY_NOTE, _clinvar_atom),
    ClaimSpec("MOUSE_KO", "mouse-KO phenotype", _mouseko_signal, _mouseko_corr, _INFORMS["MOUSE_KO"] + _LIABILITY_NOTE, _mouseko_atom),
]

_DISCLAIMER = (
    "Modality-blind, verdict-INERT projection of the on-target-safety cards into orthogonal LIABILITY "
    "claims (CONSTRAINT / BURDEN / DOSAGE / CLINVAR / MOUSE_KO), each signal×corroboration. INVERSE "
    "valence: a strong signal is a safety CONCERN, not a win; a measured tolerant read is `absent`; a "
    "protective burden is `negative`. Claims are NOT averaged. Never feeds the safety verdict (owned by "
    "the shared safety resolver, which also applies the mutant-selective-GoF WT-constraint downgrade).")


def safety_claim_vector(headline: dict, cards: list) -> dict:
    """The verdict-INERT safety liability claim vector {CONSTRAINT,BURDEN,DOSAGE,CLINVAR,MOUSE_KO:
    {signal, corroboration, evidence, conflict, informs, evidence_atom?}, _disclaimer}."""
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
               "MOUSE_KO": f"KO phenotype: {h.get('mouse_ko_phenotype_class')} ({h.get('mouse_ko_top_lethal')}) [mouse-ko-phenotype]"}
        return lambda claim: lbl.get(k)

    return build_key_signals(
        vec, rank_keys=("CONSTRAINT", "BURDEN", "DOSAGE", "CLINVAR", "MOUSE_KO"),
        support_fns={k: sup(k) for k in ("CONSTRAINT", "BURDEN", "DOSAGE", "CLINVAR", "MOUSE_KO")},
        critical_keys=("CONSTRAINT", "BURDEN", "DOSAGE"),
        caveat_fns={}, headline_fn=lambda v, s: (
            "Human-genetics safety LIABILITY present." if s else
            "No strong safety liability signal (or largely unmeasured)."),
        fallback_caveat_fn=lambda: None)


__all__ = ["safety_claim_vector", "safety_key_signals", "SAFETY_CLAIM_SPEC"]
