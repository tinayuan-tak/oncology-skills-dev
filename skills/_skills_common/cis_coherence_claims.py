"""cis_coherence_claims — cis-feature-coherence's CLAIM VECTOR + KEY SIGNALS: a verdict-INERT LEG
decomposition of the locus→expression→dependency coherence cross-tab into orthogonal (signal ×
corroboration) claims with citable atoms.

A concrete claim_vector_core instance. The cis_coherence VERDICT is a 2×2 INTERACTION (cross-tab
of separable legs), so the claim_vector is the LEG DECOMPOSITION — NOT a verdict echo. Four axes:

  CIS_DOSAGE   leg-1 GoF: CN → own-expression cis-dosage       (cis-feature-expression-coherence)
  SILENCING    leg-1 LoF: promoter methylation → LOW expression (cellline-methylation-expression-coherence)
  EXPR_DEP     leg-2:     expression → dependency correlation    (expression-dependency-correlation)
  CONJOINT     leg-2:     amp∩overexpr conjoint addiction        (amp-expr-stratified-dependency)

DISTINCTIVE — a REAL corroboration arm: unlike the flat "moderate-if-measured" of other concretes,
CIS_DOSAGE and SILENCING draw corroboration from the pre-computed cross-grain PATIENT agreement
booleans (does the TCGA patient arm replicate the cell-line call?) — a genuine second evidence leg.

VALENCE: CIS_DOSAGE / EXPR_DEP / CONJOINT are positive (cis-driven addiction); SILENCING is DESCRIPTIVE
(a coherent silencing signal is therapeutically INVERSE — LoF / SL-reactivation, not direct inhibition;
meaning in the atom). `absent` = measured uncoupled / no-correlation; `negative` = a MEASURED wrong-
direction read (positive_anomaly / amp_expr_negative_more_dependent — paralog compensation / masking);
`unmeasured` = invariant/untestable panel or gap (the resolver ABSTAINS here — never `absent`).

Verdict-INERT: reads the already-computed _headline (+ source cards) and never feeds resolve_or_raise.
"""
from __future__ import annotations

from _skills_common.claim_vector_core import (ClaimSpec, build_claim_vector, build_key_signals,
                                              corr as _plain_corr)

_CIS_DOSAGE_SIGNAL = {
    "cn_dosage_coupled_strong": "strong", "cn_dosage_coupled_moderate": "moderate",
    "cn_dosage_uncoupled": "absent",            # MEASURED: expression is CN-independent
    "cn_invariant_panel": "unmeasured",          # untestable (no CN variation) — resolver abstains
    "data_unavailable": "unmeasured",
}
_SILENCING_SIGNAL = {
    "silencing_coupled_strong": "strong", "silencing_coupled_moderate": "moderate",
    "methylation_uncoupled": "absent",
    "methylation_invariant_panel": "unmeasured", "data_unavailable": "unmeasured",
}
_EXPR_DEP_SIGNAL = {
    "strong_negative": "strong", "moderate_negative": "moderate", "weak_negative": "weak",
    "no_correlation": "absent",
    "positive_anomaly": "negative",              # MEASURED wrong direction (paralog compensation)
    "data_unavailable": "unmeasured",
}
_CONJOINT_SIGNAL = {
    "amplified_overexpressed_strongly_dependent": "strong",
    "amplified_overexpressed_moderately_dependent": "moderate",
    "not_amp_expr_stratified": "absent",
    "amp_expr_negative_more_dependent": "negative",   # MEASURED: amp-expr subset is LESS dependent
    "insufficient_amp_expr_rate": "unmeasured", "data_unavailable": "unmeasured",
}

_INFORMS = {
    "CIS_DOSAGE": "leg-1 GoF — CN→own-expression cis-dosage coupling (amplification-driven expression)",
    "SILENCING": ("leg-1 LoF — promoter-methylation→LOW-expression silencing (therapeutically INVERSE: "
                  "SL/reactivation hypothesis, not direct inhibition)"),
    "EXPR_DEP": "leg-2 — expression→dependency correlation (higher expression ⇒ more dependent)",
    "CONJOINT": "leg-2 — amp∩overexpr conjoint addiction (the amplified-overexpressed subset is more dependent)",
}

_C_CIS = "cis-feature-expression-coherence"
_C_METH = "cellline-methylation-expression-coherence"
_C_CORR = "expression-dependency-correlation"
_C_AMPX = "amp-expr-stratified-dependency"

_E_CIS = {"measurement_type": "cis_feature_expression_coherence", "grain": "target_indication", "sample_context": "cell_line"}
_E_METH = {"measurement_type": "methylation_expression_coherence", "grain": "target_indication", "sample_context": "cell_line"}
_E_CORR = {"measurement_type": "expression_dependency_correlation", "grain": "target_indication", "sample_context": "cell_line"}
_E_AMPX = {"measurement_type": "amp_expr_stratified_dependency", "grain": "target_indication", "sample_context": "cell_line"}


def _sig(card, field, smap, neg_conflict=None):
    def fn(h, c):
        cls = (c.get(card) or {}).get(field)
        tier = smap.get(cls, "unmeasured")
        conflict = neg_conflict if (tier == "negative" and neg_conflict) else None
        return tier, f"{card}: {cls or 'data_unavailable'}", conflict
    return fn


def _patient_corr(card, field, smap, agree_key):
    """Corroboration from the cross-grain PATIENT agreement boolean (a real second leg): base moderate
    when the cell-line call is measured, bumped to high when the TCGA patient arm AGREES, capped low on
    explicit DISAGREEMENT; unmeasured when the cell-line class is a gap. Never manufactures confidence
    from a missing patient arm (agree_key is None → stays moderate)."""
    def fn(h, c):
        if smap.get((c.get(card) or {}).get(field), "unmeasured") == "unmeasured":
            return "unmeasured"
        agree = h.get(agree_key)
        if agree is True:
            return "high"
        if agree is False:
            return "low"
        return "moderate"
    return fn


from _skills_common.claim_vector_core import build_summary_atom  # shared atom builder (Group D)


def _atom(card_id, summary, keys, entity, read):
    return build_summary_atom(card_id=card_id, summary=summary, keys=keys, read=read, entity=entity)


def _mk_atom(card, field, keys, entity):
    def fn(h, c):
        s = c.get(card) or {}
        return _atom(card, s, keys, entity, s.get(field))
    return fn


CIS_COHERENCE_CLAIM_SPEC = [
    ClaimSpec("CIS_DOSAGE", "CN→expression cis-dosage", _sig(_C_CIS, "cis_dosage_class", _CIS_DOSAGE_SIGNAL),
              _patient_corr(_C_CIS, "cis_dosage_class", _CIS_DOSAGE_SIGNAL, "patient_dosage_agrees_with_cellline"),
              _INFORMS["CIS_DOSAGE"],
              _mk_atom(_C_CIS, "cis_dosage_class",
                       ("cis_dosage_class", "cn_expr_spearman_r", "cn_expr_spearman_p",
                        "cn_expr_slope_log2tpm_per_cn", "delta_log2tpm_amplified_vs_neutral",
                        "n_amplified", "relative_cn_iqr", "evidence_scope", "n_cell_lines_evaluated"), _E_CIS)),
    ClaimSpec("SILENCING", "methylation→low-expression", _sig(_C_METH, "methylation_silencing_class", _SILENCING_SIGNAL),
              _patient_corr(_C_METH, "methylation_silencing_class", _SILENCING_SIGNAL, "patient_silencing_agrees_with_cellline"),
              _INFORMS["SILENCING"],
              _mk_atom(_C_METH, "methylation_silencing_class",
                       ("methylation_silencing_class", "silencing_driver", "subset_median_delta_log2tpm",
                        "subset_mannwhitney_p", "methyl_expr_spearman_r", "n_hypermethylated"), _E_METH)),
    ClaimSpec("EXPR_DEP", "expression→dependency", _sig(_C_CORR, "correlation_class", _EXPR_DEP_SIGNAL,
                   neg_conflict=("positive_anomaly — expression correlates with LESS dependency (wrong direction; "
                                 "possible paralog compensation), NOT a cis-driven addiction")),
              _plain_corr(_C_CORR, "correlation_class", _EXPR_DEP_SIGNAL), _INFORMS["EXPR_DEP"],
              _mk_atom(_C_CORR, "correlation_class",
                       ("correlation_class", "pearson_r", "pearson_p", "spearman_r",
                        "delta_chronos_top_vs_bottom_quartile", "n_cell_lines_evaluated"), _E_CORR)),
    ClaimSpec("CONJOINT", "amp∩overexpr addiction", _sig(_C_AMPX, "amp_expr_stratification_class", _CONJOINT_SIGNAL,
                   neg_conflict=("amp_expr_negative_more_dependent — the amplified-overexpressed subset is LESS "
                                 "dependent (wrong direction), NOT conjoint addiction")),
              _plain_corr(_C_AMPX, "amp_expr_stratification_class", _CONJOINT_SIGNAL), _INFORMS["CONJOINT"],
              _mk_atom(_C_AMPX, "amp_expr_stratification_class",
                       ("amp_expr_stratification_class", "delta_chronos_amp_expr_vs_rest", "amp_expr_mannwhitney_q",
                        "amp_expr_effect_size", "n_amplified_overexpressed", "n_comparator", "evidence_scope"), _E_AMPX)),
]

_DISCLAIMER = (
    "Modality-blind, verdict-INERT LEG DECOMPOSITION of the cis-coherence cross-tab into orthogonal claims "
    "(CIS_DOSAGE / SILENCING / EXPR_DEP / CONJOINT), each signal×corroboration. The cis_coherence VERDICT is "
    "an INTERACTION of these legs (owned by the resolver) — this is the decomposition + citable atoms, NOT a "
    "verdict echo. CIS_DOSAGE/SILENCING corroboration draws on the cross-grain TCGA patient-agreement arm "
    "(a real second leg). SILENCING is therapeutically INVERSE (LoF/reactivation). `absent` = measured "
    "uncoupled/no-correlation; `negative` = a measured WRONG-direction read; `unmeasured` = invariant/untestable "
    "or gap (the resolver abstains, never `absent`). Claims are NOT averaged; never feeds the verdict.")


def cis_coherence_claim_vector(headline: dict, cards: list) -> dict:
    return build_claim_vector(CIS_COHERENCE_CLAIM_SPEC, headline, cards, _DISCLAIMER)


def cis_coherence_key_signals(headline: dict, cards: list) -> dict:
    vec = cis_coherence_claim_vector(headline, cards)
    keys = ("CIS_DOSAGE", "CONJOINT", "EXPR_DEP", "SILENCING")
    return build_key_signals(
        vec, rank_keys=keys,
        support_fns={k: (lambda cl, _k=k: f"{_k}: {cl['signal']} ({cl['evidence']})") for k in keys},
        critical_keys=("CIS_DOSAGE", "EXPR_DEP"), caveat_fns={},
        headline_fn=lambda v, s: ("Cis-coherence leg substrate present." if s else
                                  "Limited cis-coherence leg signal (or untestable/unmeasured panel)."),
        fallback_caveat_fn=lambda: None, max_supports=4)


__all__ = ["cis_coherence_claim_vector", "cis_coherence_key_signals", "CIS_COHERENCE_CLAIM_SPEC"]
