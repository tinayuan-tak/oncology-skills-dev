"""translational_readiness_claims — the CLAIM VECTOR + KEY SIGNALS for the translational-readiness
skill: a verdict-INERT projection of the four public translational legs into orthogonal
(signal × corroboration) claims. translational-readiness is GATELESS (verdict_fn=None) — model
availability + genotype match + ex-vivo / in-vivo reproduction inform CONFIDENCE, never a gate.

The four legs (each keyed on the class the composed card emits):
  MODEL      HCMI patient-derived model availability   (target-model-availability, INDICATION-grain)
  GENOTYPE   does an available model carry THIS target's alteration? (target-genotype-matched-model)
  ORGANOID   does the dependency REPRODUCE ex-vivo?     (organoid-crispr-dependency, DepMap 3D CRISPR)
  PDX        does the tractability reproduce IN VIVO?    (target-pdx-drug-response, Novartis PDXE)

VALENCE — all four are POSITIVE readiness legs: a strong signal = translationally validatable. `absent`
= a MEASURED negative (a real coverage or reproduction negative, e.g. genotype `none` = no matched
model, PDX `pdx_no_objective_response`, organoid `not_organoid_dependent`); `unmeasured` = a coverage
gap (`data_unavailable` / an un-mapped lane — NEVER evidence against readiness). The signal TIERS are
DISPLAY tiers for a descriptive skill (they feed the deterministic key_signals headline + the archetype
vectoriser + the reader chips); they are never a gate and are never averaged.
"""
from __future__ import annotations

from _skills_common.claim_vector_core import (ClaimSpec, build_claim_vector, build_key_signals,
                                              build_atom)

# ── class → signal-tier maps (grounded in each composed card's emitted vocabulary) ─────────────────
# MODEL: HCMI model-availability coverage (hcmi_model_availability._availability_class thresholds).
_MODEL_SIGNAL = {
    "deep_model_coverage": "strong", "moderate_model_coverage": "moderate",
    "sparse_model_coverage": "weak", "data_unavailable": "unmeasured",
}
# GENOTYPE: does an available model carry a functional alteration in THIS gene? (genotype_matched_class).
# `none` is an HONEST measured negative (gene in an indication WITH models, but none altered); a
# non-crosswalked indication is `data_unavailable` (a gap), disambiguated upstream in the method.
_GENOTYPE_SIGNAL = {
    "matched_deep": "strong", "matched_sparse": "moderate",
    "none": "absent", "data_unavailable": "unmeasured",
}
# ORGANOID: ex-vivo dependency reproduction (organoid_dependency_precompute.classify_dependency on
# frac_dependent). pan/broad = reproduces broadly (strong translational reproduction), selective =
# moderate, rare = weak, not_organoid_dependent = a MEASURED non-reproduction.
_ORGANOID_SIGNAL = {
    "pan_organoid_essential": "strong", "broad_organoid_dependency": "strong",
    "selective_organoid_dependency": "moderate", "rare_organoid_dependency": "weak",
    "not_organoid_dependent": "absent", "data_unavailable": "unmeasured",
}
# PDX: in-vivo drug-response reproduction (pdxe_drug_response). objective responders = strong; no
# objective response = MEASURED negative; response/data unavailable = a gap.
_PDX_SIGNAL = {
    "pdx_objective_responders": "strong", "pdx_no_objective_response": "absent",
    "pdx_response_unavailable": "unmeasured", "data_unavailable": "unmeasured",
}

_INFORMS = {  # light-touch downstream routing (NOT a gate) — all four inform preclinical validation
    "MODEL": "translational_validation", "GENOTYPE": "translational_validation",
    "ORGANOID": "translational_validation", "PDX": "translational_validation",
}

# card ids + entity grains
_C_MODEL, _C_GENO = "target-model-availability", "target-genotype-matched-model"
_C_ORG, _C_PDX = "organoid-crispr-dependency", "target-pdx-drug-response"


def _sig(field, smap, evidence_fn):
    """Signal fn reading the class off the ALREADY-computed headline (hl) field, mapping it to a tier,
    and composing a short evidence string. No conflict (the legs are independent readiness reads)."""
    def fn(h, _c):
        cls = h.get(field)
        return smap.get(cls, "unmeasured"), evidence_fn(h, cls), None
    return fn


def _corr(field, smap, corr_fn):
    """Corroboration fn: `unmeasured` when the leg is an open-world gap; otherwise the leg-specific
    support-quality tier (coverage depth / cohort size). A measured-but-thin leg is `low`, not absent."""
    def fn(h, _c):
        tier = smap.get(h.get(field), "unmeasured")
        return "unmeasured" if tier == "unmeasured" else corr_fn(h)
    return fn


def _atom(card, field, value_keys, entity):
    """Citable evidence atom for one leg: the class + the leg's count/fraction fields bound to the
    source {card_id, fields}. None when the class is absent (byte-stable — no evidence_atom key)."""
    def fn(h, _c):
        vals = {field: h.get(field)}
        for k in value_keys:
            vals[k] = h.get(k)
        return build_atom(card_id=card, values=vals, read=h.get(field), entity=entity)
    return fn


def _model_ev(h, cls):
    n = h.get("n_patient_derived_models")
    return f"{cls or 'data_unavailable'}" + (f" (n={n} HCMI models)" if n is not None else "")


def _geno_ev(h, cls):
    n = h.get("n_models_with_alteration")
    return f"{cls or 'data_unavailable'}" + (f" ({n} models carry a functional alteration)" if n is not None else "")


def _org_ev(h, cls):
    lin, frac = h.get("organoid_lineage"), h.get("organoid_lineage_frac_dependent")
    if frac is None:
        frac = h.get("organoid_frac_dependent")
    tail = f" (frac_dependent={frac}{', lineage ' + str(lin) if lin else ''})" if frac is not None else ""
    caveat = " [thin organoid cohort]" if h.get("organoid_lineage_small_cohort") else ""
    return f"{cls or 'data_unavailable'}{tail}{caveat}"


def _pdx_ev(h, cls):
    frac, tx = h.get("pdx_responder_fraction"), h.get("pdx_most_active_treatment")
    tail = f" (responder_fraction={frac}{', most active ' + str(tx) if tx else ''})" if frac is not None else ""
    return f"{cls or 'data_unavailable'}{tail}"


# corroboration is coverage/cohort DEPTH per leg (a descriptive support-quality tier, not a second arm)
def _model_corr(h):
    n = h.get("n_patient_derived_models") or 0
    return "high" if n >= 50 else "moderate" if n >= 15 else "low"


def _geno_corr(h):
    n = h.get("n_models_with_alteration") or 0
    return "high" if n >= 5 else "moderate" if n >= 1 else "low"


def _org_corr(h):
    # a below-floor indication-matched lineage cohort is a low-confidence reproduction read
    return "low" if h.get("organoid_lineage_small_cohort") else "moderate"


def _pdx_corr(h):
    frac = h.get("pdx_responder_fraction")
    return "moderate" if frac is not None else "low"


TRANSLATIONAL_READINESS_CLAIM_SPEC = [
    ClaimSpec("MODEL", "HCMI model availability",
              _sig("model_availability_class", _MODEL_SIGNAL, _model_ev),
              _corr("model_availability_class", _MODEL_SIGNAL, _model_corr), _INFORMS["MODEL"],
              _atom(_C_MODEL, "model_availability_class", ("n_patient_derived_models",), "indication")),
    ClaimSpec("GENOTYPE", "genotype-matched model",
              _sig("genotype_matched_class", _GENOTYPE_SIGNAL, _geno_ev),
              _corr("genotype_matched_class", _GENOTYPE_SIGNAL, _geno_corr), _INFORMS["GENOTYPE"],
              _atom(_C_GENO, "genotype_matched_class", ("n_models_with_alteration",), "gene_indication")),
    ClaimSpec("ORGANOID", "organoid dependency (ex-vivo)",
              _sig("organoid_dependency_class", _ORGANOID_SIGNAL, _org_ev),
              _corr("organoid_dependency_class", _ORGANOID_SIGNAL, _org_corr), _INFORMS["ORGANOID"],
              _atom(_C_ORG, "organoid_dependency_class",
                    ("organoid_frac_dependent", "organoid_lineage", "organoid_lineage_frac_dependent",
                     "organoid_lineage_class", "organoid_lineage_n_screened"), "gene")),
    ClaimSpec("PDX", "PDX drug-response (in-vivo)",
              _sig("pdx_drug_response_class", _PDX_SIGNAL, _pdx_ev),
              _corr("pdx_drug_response_class", _PDX_SIGNAL, _pdx_corr), _INFORMS["PDX"],
              _atom(_C_PDX, "pdx_drug_response_class",
                    ("pdx_responder_fraction", "pdx_most_active_treatment"), "target")),
]

_DISCLAIMER = (
    "Verdict-INERT projection of the four public translational-readiness legs into orthogonal claims "
    "(MODEL / GENOTYPE / ORGANOID / PDX), each signal × corroboration. All four are POSITIVE readiness "
    "legs: a strong signal = the nomination is preclinically validatable. `absent` = a MEASURED negative "
    "(no matched model / no PDX response / not organoid-dependent); `unmeasured` = a coverage gap "
    "(`data_unavailable` / un-mapped lane — never evidence against readiness). Claims are NOT averaged; "
    "translational-readiness is gateless — this never feeds a verdict. The PD-assay, imaging-tracer, and "
    "INTERNAL Takeda model legs remain un-wired (not in data-catalog).")


def translational_readiness_claim_vector(headline: dict, cards: list) -> dict:
    """The verdict-INERT translational claim vector {MODEL,GENOTYPE,ORGANOID,PDX:
    {signal, corroboration, evidence, conflict, informs, evidence_atom?}, _disclaimer}."""
    return build_claim_vector(TRANSLATIONAL_READINESS_CLAIM_SPEC, headline, cards, _DISCLAIMER)


def translational_readiness_key_signals(headline: dict, cards: list) -> dict:
    """A brief, deterministic, CITED read over the translational vector (available without the LLM)."""
    vec = translational_readiness_claim_vector(headline, cards)

    def _support(k):
        return lambda cl: f"{k}: {cl['signal']} ({cl['evidence']})"

    return build_key_signals(
        vec, rank_keys=("MODEL", "GENOTYPE", "ORGANOID", "PDX"),
        support_fns={k: _support(k) for k in ("MODEL", "GENOTYPE", "ORGANOID", "PDX")},
        # MODEL is the load-bearing readiness leg (can I validate at all?); its coverage floors confidence
        critical_keys=("MODEL",),
        caveat_fns={"MODEL": lambda cl: (
            f"sparse patient-derived model coverage ({cl['evidence']}) — thin preclinical validation base")},
        headline_fn=lambda v, s: (
            "Preclinically validatable (patient-derived models + reproduction signal present)." if s else
            "Limited translational-readiness substrate (thin model coverage or un-mapped legs)."),
        fallback_caveat_fn=lambda: None,
        max_supports=4)


__all__ = ["translational_readiness_claim_vector", "translational_readiness_key_signals",
           "TRANSLATIONAL_READINESS_CLAIM_SPEC"]
