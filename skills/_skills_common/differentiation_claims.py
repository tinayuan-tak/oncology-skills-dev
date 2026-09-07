"""differentiation_claims — differentiation-landscape's CLAIM VECTOR + KEY SIGNALS: a verdict-INERT
projection of the differentiation / patient-selection cards into (signal × corroboration) per claim.

A concrete claim_vector_core instance. Four DESCRIPTIVE axes (signal = strength of a
differentiation-relevant pattern; DIRECTION lives in the atom, not the tier):

  COMUT     co-mutation / mutual-exclusivity — Fisher co-occurrence landscape (patient-selection).
  SURVIVAL  expression↔clinical outcome      — KM/log-rank survival association.
  PROGNOSIS PRECOG meta prognostic           — pan-cohort prognostic meta-z.
  NODE      pathway-node leverage            — dominant vs dominated network node.

Signals + atoms read from the SOURCE card summaries. Verdict-INERT (differentiation-landscape is
descriptive; this never feeds a resolver).
"""
from __future__ import annotations

from _skills_common.claim_vector_core import (ClaimSpec, build_claim_vector, build_key_signals,
                                              bump_corroboration, cap_corroboration,
                                              corr as _corr, signal_from_class as _sig)

# co-occurrence: a significant pattern (either direction) is a signal; direction carried in the atom.
_COMUT_SIGNAL = {"strong_cooccurring": "strong", "strong_mutually_exclusive": "strong",
                 "modest_cooccurring": "moderate", "modest_mutually_exclusive": "moderate",
                 "both_patterns_present": "moderate", "ns": "absent", "data_unavailable": "unmeasured"}
# survival / prognosis: an association (either direction) is a signal; worse/better is in the atom.
_SURVIVAL_SIGNAL = {"expression_high_worse_survival": "strong", "expression_high_better_survival": "moderate",
                    "no_survival_association": "absent", "insufficient_survival_data": "unmeasured",
                    "data_unavailable": "unmeasured"}
_PROGNOSIS_SIGNAL = {"expression_high_worse_survival": "strong", "expression_high_better_survival": "moderate",
                     "no_prognostic_association": "absent", "data_unavailable": "unmeasured"}
_NODE_SIGNAL = {"dominant_node": "strong", "dominated_but_tractability_edge": "moderate",
                "dominated_node": "weak", "weak_and_uncontested": "weak",
                "no_node_set": "absent", "data_unavailable": "unmeasured"}

_INFORMS = {
    "COMUT": "co-mutation / mutual-exclusivity — patient-selection + combination-biology context",
    "SURVIVAL": "expression↔survival association — prognostic / patient-stratification context",
    "PROGNOSIS": "PRECOG meta prognostic — cross-cohort prognostic corroboration",
    "NODE": "pathway-node leverage — is the target a dominant network node vs a dominated one",
}


from _skills_common.claim_vector_core import build_summary_atom  # shared atom builder (Group D)


def _atom(card_id, summary, keys, read):
    return build_summary_atom(card_id=card_id, summary=summary, keys=keys, read=read,
                              entity={"measurement_type": "differentiation_landscape", "grain": "target_indication"})


def _mk_atom(card, field, keys):
    def fn(h, c):
        return _atom(card, c.get(card) or {}, keys, (c.get(card) or {}).get(field))
    return fn


_C_COMUT, _C_SURV = "co-mutation-and-mutual-exclusivity", "expression-clinical-association"
_C_PROG, _C_NODE = "precog-prognostic-association", "pathway-node-leverage"

_SURV_WORSE, _SURV_BETTER = "expression_high_worse_survival", "expression_high_better_survival"


def _survival_corr(h, c):
    """SURVIVAL corroboration: the per-indication KM/log-rank association (expression-clinical-association,
    the signal source) is ONE cohort read → base corroboration. PRECOG (pan-cancer META-ANALYTIC
    expression→survival, already in the headline) is a genuinely INDEPENDENT second arm — different cohorts
    AND method: a same-direction PRECOG association bumps corroboration, an OPPOSITE-direction one caps it.
    Was the single-source _corr proxy (dead-constant moderate). Verdict-INERT."""
    surv = (c.get(_C_SURV) or {}).get("survival_association_class")
    base = "moderate" if _SURVIVAL_SIGNAL.get(surv, "unmeasured") != "unmeasured" else "unmeasured"
    if base == "unmeasured":
        return "unmeasured"
    precog = h.get("precog_prognostic_class")
    if precog in (_SURV_WORSE, _SURV_BETTER) and surv in (_SURV_WORSE, _SURV_BETTER):
        return bump_corroboration(base, True) if precog == surv else cap_corroboration(base, "low")
    return base                                    # PRECOG no-association / data_unavailable → single-source base

DIFFERENTIATION_CLAIM_SPEC = [
    ClaimSpec("COMUT", "co-mutation landscape", _sig(_C_COMUT, "cooccurrence_class", _COMUT_SIGNAL),
              _corr(_C_COMUT, "cooccurrence_class", _COMUT_SIGNAL), _INFORMS["COMUT"],
              _mk_atom(_C_COMUT, "cooccurrence_class",
                       ("cooccurrence_class", "n_significant_cooccurring", "n_significant_mutually_exclusive",
                        "top_cooccurring", "top_mutually_exclusive", "n_pairs_panel_intersect_eligible"))),
    ClaimSpec("SURVIVAL", "expression↔survival", _sig(_C_SURV, "survival_association_class", _SURVIVAL_SIGNAL),
              _survival_corr, _INFORMS["SURVIVAL"],
              _mk_atom(_C_SURV, "survival_association_class",
                       ("survival_association_class", "logrank_p", "n_patients", "n_events", "n_high_expr", "n_low_expr"))),
    ClaimSpec("PROGNOSIS", "PRECOG prognostic", _sig(_C_PROG, "prognostic_class", _PROGNOSIS_SIGNAL),
              _corr(_C_PROG, "prognostic_class", _PROGNOSIS_SIGNAL), _INFORMS["PROGNOSIS"],
              _mk_atom(_C_PROG, "prognostic_class",
                       ("prognostic_class", "meta_z", "pan_cancer_meta_z", "n_precog_datasets"))),
    ClaimSpec("NODE", "pathway-node leverage", _sig(_C_NODE, "node_leverage_class", _NODE_SIGNAL),
              _corr(_C_NODE, "node_leverage_class", _NODE_SIGNAL), _INFORMS["NODE"],
              _mk_atom(_C_NODE, "node_leverage_class",
                       ("node_leverage_class", "evidence_scope", "paralog_buffering_class", "strongest_buffering_paralog"))),
]

_DISCLAIMER = (
    "Modality-blind, verdict-INERT projection of the differentiation-landscape cards into orthogonal "
    "DESCRIPTIVE claims (COMUT / SURVIVAL / PROGNOSIS / NODE), each signal×corroboration. Signal = "
    "strength of a differentiation pattern; the DIRECTION (co-occurring vs exclusive; worse vs better "
    "survival) lives in the atom, not the tier. Claims are NOT averaged; never feeds a verdict.")


def differentiation_claim_vector(headline: dict, cards: list) -> dict:
    return build_claim_vector(DIFFERENTIATION_CLAIM_SPEC, headline, cards, _DISCLAIMER)


def differentiation_key_signals(headline: dict, cards: list) -> dict:
    vec = differentiation_claim_vector(headline, cards)
    return build_key_signals(
        vec, rank_keys=("COMUT", "SURVIVAL", "PROGNOSIS", "NODE"),
        support_fns={k: (lambda cl, _k=k: f"{_k}: {cl['signal']} ({cl['evidence']})") for k in
                     ("COMUT", "SURVIVAL", "PROGNOSIS", "NODE")},
        critical_keys=("COMUT", "NODE"), caveat_fns={},
        headline_fn=lambda v, s: ("Differentiation / patient-selection signal present." if s else
                                  "Limited differentiation signal."),
        fallback_caveat_fn=lambda: None)


__all__ = ["differentiation_claim_vector", "differentiation_key_signals", "DIFFERENTIATION_CLAIM_SPEC"]
