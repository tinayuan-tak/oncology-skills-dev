"""surface_claims — surface-modality-fit's CLAIM VECTOR + KEY SIGNALS: a verdict-INERT projection of the
surface / ADC-TCE cards into (signal × corroboration) per orthogonal claim.

The EIGHTH concrete over claim_vector_core (dependency / genomic / selectivity / presence / safety /
tractability / differentiation are the first seven). Five surface axes as a ClaimSpec list:

  FIT       ADC/TCE modality fit    — the composed surface-modality call (adc-tce-modality-fit).
  TOPOLOGY  surface topology / ECD  — extracellular-domain engineerability (surface-topology-and-ptm).
  DENSITY   antigen abundance       — surface copies/cell density class (surface-abundance-density).
  SAFETY    normal-tissue window    — normal-tissue breadth (normal-tissue-liability).
  SHED      ectodomain shedding     — membrane-retained vs shed (shed-ectodomain-liability).

UNIFORM valence: a STRONG signal is a BETTER surface-modality substrate (viable modality / large
engineerable ECD / high antigen density / clean normal-tissue window / membrane-retained). A MEASURED
adverse read is `negative` — a real LIABILITY the reasoner must weigh: broad normal-tissue expression
(SAFETY) or clinically-shed ectodomain (SHED). A MEASURED no-substrate read (neither_viable /
no_extracellular_domain / very_low density) is `absent`. `unmeasured` is a data GAP, never a substrate.

Verdict-INERT: reads the ALREADY-computed surface cards; the surface verdict is owned by the shared
resolver and stays byte-stable with or without this projection.
"""
from __future__ import annotations

from _skills_common.claim_vector_core import ClaimSpec, build_claim_vector, build_key_signals, corr as _corr

# ── enum → substrate-strength tier maps (grounded in the target-contracts summary vocabularies) ──────
_FIT_SIGNAL = {
    "ADC_preferred": "strong", "TCE_preferred": "strong", "both_viable": "strong",
    "modality_ambiguous": "moderate", "isoform_dependent_undefined": "weak",
    "neither_viable": "absent", "data_unavailable": "unmeasured",
}
_TOPOLOGY_SIGNAL = {   # ecd_engineerability_class — accessible ECD to engineer a binder against
    "large_ecd": "strong", "moderate_ecd": "moderate", "minimal_ecd": "weak",
    "no_extracellular_domain": "absent", "data_unavailable": "unmeasured",
}
_DENSITY_SIGNAL = {    # surface_density_class — antigen copies/cell
    "high": "strong", "moderate": "moderate", "low": "weak", "very_low": "absent",
    "unmeasured": "unmeasured",
}
_SAFETY_SIGNAL = {     # normal_tissue_breadth_class — clean window = strong; broad = measured LIABILITY
    "not_detected_in_normal": "strong", "restricted_normal_expression": "moderate",
    "moderate_normal_expression": "weak", "broad_normal_expression": "negative",
    "data_unavailable": "unmeasured",
}
_SHED_SIGNAL = {       # shed_liability_class — membrane-retained = strong; clinically-shed = measured LIABILITY
    "not_shed_membrane_retained": "strong", "secretome_proxy_shed": "weak",
    "clinically_shed": "negative", "indeterminate": "unmeasured",
}

_INFORMS = {
    "FIT": "ADC/TCE modality fit — the composed surface-modality call (viable modality vs neither)",
    "TOPOLOGY": "surface topology / ECD engineerability — is there an accessible extracellular domain to bind",
    "DENSITY": "antigen abundance — surface copies/cell density (ADC/TCE payload-floor viability)",
    "SAFETY": "normal-tissue window — restricted normal expression is favourable; broad is a LIABILITY",
    "SHED": "ectodomain shedding — membrane-retained is favourable; clinically-shed is a LIABILITY (sink / decoy)",
}


def _sig(card, field, smap):
    def fn(h, c):
        cls = (c.get(card) or {}).get(field)
        return smap.get(cls, "unmeasured"), f"{card}: {cls or 'data_unavailable'}", None
    return fn


def _atom(card_id, summary, keys, entity, read):
    vals = {k: summary[k] for k in keys if summary.get(k) is not None}
    if not vals:
        return None
    return {"read": read, "values": vals, "cite": {"card_id": card_id, "fields": sorted(vals)}, "entity": entity}


def _mk_atom(card, field, keys, entity):
    def fn(h, c):
        return _atom(card, c.get(card) or {}, keys, entity, (c.get(card) or {}).get(field))
    return fn


_C_FIT, _C_TOP = "adc-tce-modality-fit", "surface-topology-and-ptm"
_C_DEN, _C_SAFE, _C_SHED = "surface-abundance-density", "normal-tissue-liability", "shed-ectodomain-liability"

_E_TI = {"measurement_type": "surface_modality_fit", "grain": "target_indication"}
_E_T = {"measurement_type": "surface_protein_biophysics", "grain": "target"}
_E_SAFE = {"measurement_type": "normal_tissue_surface_liability", "grain": "target", "valence": "liability"}
_E_SHED = {"measurement_type": "ectodomain_shedding_liability", "grain": "target", "valence": "liability"}

SURFACE_CLAIM_SPEC = [
    ClaimSpec("FIT", "ADC/TCE modality fit", _sig(_C_FIT, "fit_class", _FIT_SIGNAL),
              _corr(_C_FIT, "fit_class", _FIT_SIGNAL), _INFORMS["FIT"],
              _mk_atom(_C_FIT, "fit_class",
                       ("fit_class", "fit_rationale", "endocytosis_confidence", "surface_family_class",
                        "is_adc_topology_favorable", "is_tce_topology_favorable"), _E_TI)),
    ClaimSpec("TOPOLOGY", "surface topology / ECD", _sig(_C_TOP, "ecd_engineerability_class", _TOPOLOGY_SIGNAL),
              _corr(_C_TOP, "ecd_engineerability_class", _TOPOLOGY_SIGNAL), _INFORMS["TOPOLOGY"],
              _mk_atom(_C_TOP, "ecd_engineerability_class",
                       ("topology_class", "ecd_engineerability_class", "tm_pass_count",
                        "extracellular_residue_count", "ecd_orientation", "signal_peptide_present"), _E_T)),
    ClaimSpec("DENSITY", "antigen abundance", _sig(_C_DEN, "surface_density_class", _DENSITY_SIGNAL),
              _corr(_C_DEN, "surface_density_class", _DENSITY_SIGNAL), _INFORMS["DENSITY"],
              _mk_atom(_C_DEN, "surface_density_class",
                       ("surface_density_class", "density_evidence_level", "estimated_copies_per_cell_median",
                        "estimated_copies_per_cell_lower", "estimated_copies_per_cell_upper",
                        "hpa_ihc_intensity_class", "is_tce_viable", "is_adc_high_payload_viable"), _E_TI)),
    ClaimSpec("SAFETY", "normal-tissue window", _sig(_C_SAFE, "normal_tissue_breadth_class", _SAFETY_SIGNAL),
              _corr(_C_SAFE, "normal_tissue_breadth_class", _SAFETY_SIGNAL), _INFORMS["SAFETY"],
              _mk_atom(_C_SAFE, "normal_tissue_breadth_class",
                       ("normal_tissue_breadth_class", "essential_tissue_flag", "hpa_tissue_specificity",
                        "n_essential_tissues_with_expression", "essential_tissues_flagged", "n_specific_tissues"), _E_SAFE)),
    ClaimSpec("SHED", "ectodomain shedding", _sig(_C_SHED, "shed_liability_class", _SHED_SIGNAL),
              _corr(_C_SHED, "shed_liability_class", _SHED_SIGNAL), _INFORMS["SHED"],
              _mk_atom(_C_SHED, "shed_liability_class",
                       ("shed_liability_class", "shed_evidence_tier", "serum_marker", "shed_product",
                        "shedding_protease", "measured_shed_class", "media_mean_npx"), _E_SHED)),
]

_DISCLAIMER = (
    "Modality-blind, verdict-INERT projection of the surface-modality-fit cards into orthogonal claims "
    "(FIT / TOPOLOGY / DENSITY / SAFETY / SHED), each signal×corroboration. UNIFORM valence: a strong "
    "signal is a BETTER surface-modality substrate; a MEASURED adverse read (broad normal expression, "
    "clinically-shed ectodomain) is `negative` (a real liability); a measured no-substrate read is "
    "`absent`; `unmeasured` is a data gap. Claims are NOT averaged; never feeds the surface verdict.")


def surface_claim_vector(headline: dict, cards: list) -> dict:
    """The verdict-INERT surface claim vector {FIT,TOPOLOGY,DENSITY,SAFETY,SHED:
    {signal, corroboration, evidence, conflict, informs, evidence_atom?}, _disclaimer}."""
    return build_claim_vector(SURFACE_CLAIM_SPEC, headline, cards, _DISCLAIMER)


def surface_key_signals(headline: dict, cards: list) -> dict:
    """A brief, deterministic, CITED read over the surface claim vector (available without the LLM).
    SAFETY / SHED emit an explicit caveat when their MEASURED read is an adverse `negative` liability."""
    vec = surface_claim_vector(headline, cards)

    def _liability_caveat(label):
        def fn(claim):
            return f"{label} is a MEASURED liability ({claim['evidence']})" if claim.get("signal") == "negative" else None
        return fn

    return build_key_signals(
        vec, rank_keys=("FIT", "DENSITY", "TOPOLOGY", "SAFETY", "SHED"),
        support_fns={k: (lambda cl, _k=k: f"{_k}: {cl['signal']} ({cl['evidence']})") for k in
                     ("FIT", "DENSITY", "TOPOLOGY", "SAFETY", "SHED")},
        critical_keys=("FIT", "DENSITY", "SAFETY", "SHED"),
        caveat_fns={"SAFETY": _liability_caveat("normal-tissue breadth"),
                    "SHED": _liability_caveat("ectodomain shedding")},
        headline_fn=lambda v, s: ("Surface / modality-fit substrate present." if s else
                                   "Limited surface / modality-fit substrate (or largely unmeasured)."),
        fallback_caveat_fn=lambda: None)


__all__ = ["surface_claim_vector", "surface_key_signals", "SURFACE_CLAIM_SPEC"]
