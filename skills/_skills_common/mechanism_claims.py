"""mechanism_claims — mechanism-and-pharmacology's CLAIM VECTOR + KEY SIGNALS: a verdict-INERT
projection of the mechanism / pharmacology cards into orthogonal (signal × corroboration) claims with
citable atoms.

The ELEVENTH concrete over claim_vector_core. Five mechanism axes:

  NETWORK        signaling-network topology + MoA hooks  (signaling-network-mechanism)
  PHOSPHO        phospho-ACTIVITY beyond abundance        (phospho-pathway-activity)   [the real signal]
  PATHWAY        cohort-relative pathway activity         (pathway-activity-context)
  PERTURBATION   target-ENGAGEMENT under drug perturbation (tahoe-drug-perturbation)   [engagement != dependency]
  PREDICTABILITY dependency predictability (omics-driven)  (dependency-predictability)

MOSTLY DESCRIPTIVE (differentiation-style, direction/meaning in the atom). The one genuinely
decision-grade POSITIVE signal is PHOSPHO (measured activation beyond abundance). HONESTY TRAP:
NETWORK's `network_class` is an ANNOTATION-DENSITY measure (SIGNOR edge count = curation, not target
biology), so it is deliberately CAPPED at `moderate` — never `strong`. `absent` = a measured
"axis-doesn't-apply" / no-standout (e.g. `not_phosphoprotein` for a GTPase — a real biological N/A);
`unmeasured` = a coverage gap. No axis has a natural `negative` tier.

Verdict-INERT: the mechanism resolver keys ONLY on signaling-network-mechanism (network_class +
has_pd_marker); this projection reads the already-computed cards and never feeds it.
"""
from __future__ import annotations

from _skills_common.claim_vector_core import ClaimSpec, build_claim_vector, build_key_signals, corr as _corr

# network_class = ANNOTATION DENSITY, not biological strength → CAPPED at moderate (never strong).
_NETWORK_SIGNAL = {
    "well_characterized": "moderate", "partial": "weak", "sparse": "weak", "data_unavailable": "unmeasured",
}
# phospho ACTIVITY beyond abundance — the real activation signal (positive valence).
_PHOSPHO_SIGNAL = {
    "phospho_active": "strong", "phospho_present": "moderate", "phospho_low": "weak",
    "not_phosphoprotein": "absent",             # MEASURED biological N/A (e.g. a GTPase) — not a gap
    "data_unavailable": "unmeasured",
}
_PATHWAY_SIGNAL = {
    "relatively_high": "moderate", "profiled": "absent",   # profiled but no standout = measured no-signal
    "data_unavailable": "unmeasured",
}
_PERTURBATION_SIGNAL = {   # engagement (direction in atom); NOT dependency
    "drug_suppressed": "moderate", "drug_induced": "moderate", "bidirectionally_perturbed": "moderate",
    "weakly_perturbed": "weak", "not_measured": "absent", "data_unavailable": "unmeasured",
}
_PREDICTABILITY_SIGNAL = {
    "own_omics_driven": "moderate", "context_or_driver_dependent": "moderate",
    "weakly_predictable": "weak", "unpredictable": "absent", "data_unavailable": "unmeasured",
}

_INFORMS = {
    "NETWORK": ("signaling-network topology + MoA hooks — ANNOTATION density (SIGNOR/Reactome edges), a "
                "context measure NOT biological strength (capped at moderate)"),
    "PHOSPHO": "phospho-ACTIVITY beyond abundance — measured activation / signaling-state (the real signal)",
    "PATHWAY": "cohort-relative pathway activity — which pathways are relatively high (context)",
    "PERTURBATION": "target-ENGAGEMENT under drug perturbation — MoA/engagement, NOT dependency (direction in atom)",
    "PREDICTABILITY": "dependency predictability — is the dependency own-omics/driver-predictable (correlational)",
}

_C_NET = "signaling-network-mechanism"
_C_PHOS = "phospho-pathway-activity"
_C_PATH = "pathway-activity-context"
_C_TAHOE = "tahoe-drug-perturbation"
_C_PRED = "dependency-predictability"

_E_NET = {"measurement_type": "signaling_network_mechanism", "grain": "target"}
_E_PHOS = {"measurement_type": "phospho_pathway_activity", "grain": "target_indication"}
_E_PATH = {"measurement_type": "pathway_activity_context", "grain": "target_indication"}
_E_TAHOE = {"measurement_type": "tahoe_drug_perturbation", "grain": "target"}
_E_PRED = {"measurement_type": "dependency_predictability", "grain": "target"}


def _sig(card, field, smap):
    def fn(h, c):
        cls = (c.get(card) or {}).get(field)
        return smap.get(cls, "unmeasured"), f"{card}: {cls or 'data_unavailable'}", None
    return fn


from _skills_common.claim_vector_core import build_summary_atom  # shared atom builder (Group D)


def _atom(card_id, summary, keys, entity, read):
    return build_summary_atom(card_id=card_id, summary=summary, keys=keys, read=read, entity=entity)


def _mk_atom(card, field, keys, entity):
    def fn(h, c):
        s = c.get(card) or {}
        return _atom(card, s, keys, entity, s.get(field))
    return fn


MECHANISM_CLAIM_SPEC = [
    ClaimSpec("NETWORK", "signaling-network topology", _sig(_C_NET, "network_class", _NETWORK_SIGNAL),
              _corr(_C_NET, "network_class", _NETWORK_SIGNAL), _INFORMS["NETWORK"],
              # MoA hooks fold into the NETWORK atom (same card — not an orthogonal axis)
              _mk_atom(_C_NET, "network_class",
                       ("network_class", "n_upstream_regulators", "n_downstream_effectors",
                        "has_actionable_moa", "moa_classes_present", "moa_ontology_version"), _E_NET)),
    ClaimSpec("PHOSPHO", "phospho-activity", _sig(_C_PHOS, "phospho_activity_class", _PHOSPHO_SIGNAL),
              _corr(_C_PHOS, "phospho_activity_class", _PHOSPHO_SIGNAL), _INFORMS["PHOSPHO"],
              _mk_atom(_C_PHOS, "phospho_activity_class",
                       ("phospho_activity_class", "n_phosphosites", "max_site_detection_fraction",
                        "phospho_exceeds_abundance", "phospho_minus_protein_z", "top_phosphosites"), _E_PHOS)),
    ClaimSpec("PATHWAY", "pathway activity context", _sig(_C_PATH, "pathway_activity_class", _PATHWAY_SIGNAL),
              _corr(_C_PATH, "pathway_activity_class", _PATHWAY_SIGNAL), _INFORMS["PATHWAY"],
              _mk_atom(_C_PATH, "pathway_activity_class",
                       ("pathway_activity_class", "relatively_high_pathways", "target_pathway_membership",
                        "n_pathways_profiled"), _E_PATH)),
    ClaimSpec("PERTURBATION", "drug-perturbation engagement",
              _sig(_C_TAHOE, "tahoe_perturbation_class", _PERTURBATION_SIGNAL),
              _corr(_C_TAHOE, "tahoe_perturbation_class", _PERTURBATION_SIGNAL), _INFORMS["PERTURBATION"],
              _mk_atom(_C_TAHOE, "tahoe_perturbation_class",
                       ("tahoe_perturbation_class", "n_perturbing_drugs", "n_strong_movers",
                        "strongest_mover_drug", "strongest_mover_log2fc"), _E_TAHOE)),
    ClaimSpec("PREDICTABILITY", "dependency predictability",
              _sig(_C_PRED, "predictability_class", _PREDICTABILITY_SIGNAL),
              _corr(_C_PRED, "predictability_class", _PREDICTABILITY_SIGNAL), _INFORMS["PREDICTABILITY"],
              _mk_atom(_C_PRED, "predictability_class",
                       ("predictability_class", "pred_dominant_feature_class", "pred_top_features_rf"), _E_PRED)),
]

_DISCLAIMER = (
    "Modality-blind, verdict-INERT projection of the mechanism-and-pharmacology cards into orthogonal "
    "claims (NETWORK / PHOSPHO / PATHWAY / PERTURBATION / PREDICTABILITY), each signal×corroboration. "
    "MOSTLY DESCRIPTIVE (direction/meaning in the atom); PHOSPHO is the one decision-grade positive signal. "
    "HONESTY: NETWORK is ANNOTATION density (curation, not biology) → capped at `moderate`; PERTURBATION is "
    "engagement, NOT dependency. `absent` = measured axis-N/A / no-standout; `unmeasured` = coverage gap; no "
    "axis has a `negative` tier. Claims are NOT averaged; never feeds the mechanism verdict (owned by the "
    "resolver, which keys only on signaling-network-mechanism).")


def mechanism_claim_vector(headline: dict, cards: list) -> dict:
    return build_claim_vector(MECHANISM_CLAIM_SPEC, headline, cards, _DISCLAIMER)


def mechanism_key_signals(headline: dict, cards: list) -> dict:
    vec = mechanism_claim_vector(headline, cards)
    keys = ("PHOSPHO", "NETWORK", "PATHWAY", "PERTURBATION", "PREDICTABILITY")
    return build_key_signals(
        vec, rank_keys=keys,
        support_fns={k: (lambda cl, _k=k: f"{_k}: {cl['signal']} ({cl['evidence']})") for k in keys},
        critical_keys=("PHOSPHO", "NETWORK"), caveat_fns={},
        headline_fn=lambda v, s: ("Mechanism / pharmacology context present." if s else
                                  "Limited mechanism signal (or largely unmeasured)."),
        fallback_caveat_fn=lambda: None, max_supports=4)


__all__ = ["mechanism_claim_vector", "mechanism_key_signals", "MECHANISM_CLAIM_SPEC"]
