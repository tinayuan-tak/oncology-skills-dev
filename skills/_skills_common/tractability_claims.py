"""tractability_claims — tractability-small-molecule's CLAIM VECTOR + KEY SIGNALS: a verdict-INERT
projection of the small-molecule druggability cards into (signal × corroboration) per orthogonal claim.

The SIXTH concrete over claim_vector_core (dependency / genomic / selectivity / presence / safety are
1–5). Five POSITIVE-valence axes (strong = strong druggability evidence):

  POTENCY   measured binding      — ChEMBL/BindingDB measured potency (pChEMBL / neglog M).
  ACTIVITY  functional compound   — PRISM cell-kill activity + clinical phase.
  STRUCT    ligandable pocket      — experimental/predicted ligandability, PDB/AlphaFold coverage.
  DRUG      known-drug pharmacology— approved-drug / druggable-genome tractability.
  DEGRADER  degrader feasibility   — E3-substrate evidence + degrader precedent.

Signals + atoms are read from the SOURCE card summaries (cards_by_id) for correct per-card citation.
Verdict-INERT: never feeds the druggability resolver; frozen by the skill's replay guards.
"""
from __future__ import annotations

from _skills_common.claim_vector_core import ClaimSpec, build_claim_vector, build_key_signals

_POTENCY_SIGNAL = {"potent_measured_ligand": "strong", "weak_measured_ligand": "moderate",
                   "no_measured_activity": "absent", "data_unavailable": "unmeasured"}
_ACTIVITY_SIGNAL = {"clinically_active": "strong", "clinical_precedent_only": "moderate",
                    "tool_compound_only": "moderate", "weakly_active": "weak",
                    "no_compounds_found": "absent", "data_unavailable": "unmeasured"}
_STRUCT_SIGNAL = {"experimental_ligandable": "strong", "predicted_ligandable": "moderate",
                  "annotation_ligandable": "weak", "no_ligandability_signal": "absent",
                  "disordered_low": "negative", "insufficient_evidence": "unmeasured"}
_DRUG_SIGNAL = {"approved_drug_tractable": "strong", "clinically_actionable": "strong",
                "druggable_genome": "moderate", "interaction_only": "weak",
                "category_only": "weak", "no_known_drug_evidence": "absent"}
_DEGRADER_SIGNAL = {"precedented_degradable": "strong", "ubiquitination_substrate": "moderate",
                    "plausible_untested": "weak", "unfavorable_location": "negative",
                    "data_unavailable": "unmeasured"}

_INFORMS = {
    "POTENCY": "measured binding potency — is there a compound that binds the target (chemical start)",
    "ACTIVITY": "functional compound activity — does a compound kill cells + clinical precedent",
    "STRUCT": "structural ligandability — is there a druggable pocket even absent a known compound",
    "DRUG": "known-drug pharmacology — approved-drug / druggable-genome tractability",
    "DEGRADER": "degrader feasibility — E3-substrate evidence + degrader precedent (PROTAC lens)",
}


def _sig(card, field, smap):
    def fn(h, c):
        cls = (c.get(card) or {}).get(field)
        return smap.get(cls, "unmeasured"), f"{card}: {cls or 'data_unavailable'}", None
    return fn


def _corr_present(card, field, smap):
    def fn(h, c):
        return "moderate" if smap.get((c.get(card) or {}).get(field), "unmeasured") != "unmeasured" else "unmeasured"
    return fn


from _skills_common.claim_vector_core import build_summary_atom  # shared atom builder (Group D)


def _atom(card_id, summary, keys, read):
    return build_summary_atom(card_id=card_id, summary=summary, keys=keys, read=read,
                              entity={"measurement_type": "small_molecule_tractability", "grain": "target"})


def _mk_atom(card, field, keys):
    def fn(h, c):
        return _atom(card, c.get(card) or {}, keys, (c.get(card) or {}).get(field))
    return fn


_C_POT, _C_ACT = "measured-potency-tractability", "prism-compound-activity"
_C_STR, _C_DRUG, _C_DEG = "structure-features-static", "known-drug-tractability", "degradation-feasibility"

SMALL_MOLECULE_CLAIM_SPEC = [
    ClaimSpec("POTENCY", "measured binding", _sig(_C_POT, "measured_bioactivity_class", _POTENCY_SIGNAL),
              _corr_present(_C_POT, "measured_bioactivity_class", _POTENCY_SIGNAL), _INFORMS["POTENCY"],
              _mk_atom(_C_POT, "measured_bioactivity_class",
                       ("measured_bioactivity_class", "chembl_best_pchembl", "chembl_n_potent_ligands",
                        "best_measured_potency_neglog_m", "chembl_max_clinical_phase", "bindingdb_best_p_affinity"))),
    ClaimSpec("ACTIVITY", "functional compound", _sig(_C_ACT, "prism_activity_class", _ACTIVITY_SIGNAL),
              _corr_present(_C_ACT, "prism_activity_class", _ACTIVITY_SIGNAL), _INFORMS["ACTIVITY"],
              _mk_atom(_C_ACT, "prism_activity_class",
                       ("prism_activity_class", "n_compounds_targeting", "highest_clinical_phase",
                        "median_log2auc_across_compounds"))),
    ClaimSpec("STRUCT", "ligandable pocket", _sig(_C_STR, "structural_ligandability_class", _STRUCT_SIGNAL),
              _corr_present(_C_STR, "structural_ligandability_class", _STRUCT_SIGNAL), _INFORMS["STRUCT"],
              _mk_atom(_C_STR, "structural_ligandability_class",
                       ("structural_ligandability_class", "pdb_coverage_class", "alphafold_confidence_class",
                        "alphafold_plddt_mean", "pdb_best_resolution_angstrom", "hotspot_pocket_adjacency_call"))),
    ClaimSpec("DRUG", "known-drug pharmacology", _sig(_C_DRUG, "known_drug_tractability_class", _DRUG_SIGNAL),
              _corr_present(_C_DRUG, "known_drug_tractability_class", _DRUG_SIGNAL), _INFORMS["DRUG"],
              _mk_atom(_C_DRUG, "known_drug_tractability_class",
                       ("known_drug_tractability_class", "druggability_tier", "has_approved_drug",
                        "n_antineoplastic_interactions", "n_approved_drug_interactions"))),
    ClaimSpec("DEGRADER", "degrader feasibility", _sig(_C_DEG, "degradability_feasibility_class", _DEGRADER_SIGNAL),
              _corr_present(_C_DEG, "degradability_feasibility_class", _DEGRADER_SIGNAL), _INFORMS["DEGRADER"],
              _mk_atom(_C_DEG, "degradability_feasibility_class",
                       ("degradability_feasibility_class", "e3_substrate_evidence", "n_e3_ligases_literature",
                        "degrader_precedent"))),
]

_DISCLAIMER = (
    "Modality-blind, verdict-INERT projection of the small-molecule druggability cards into orthogonal "
    "claims (POTENCY / ACTIVITY / STRUCT / DRUG / DEGRADER), each signal×corroboration. POSITIVE valence "
    "(strong = strong druggability). Claims are NOT averaged. Never feeds the druggability verdict.")


def small_molecule_claim_vector(headline: dict, cards: list) -> dict:
    return build_claim_vector(SMALL_MOLECULE_CLAIM_SPEC, headline, cards, _DISCLAIMER)


def small_molecule_key_signals(headline: dict, cards: list) -> dict:
    vec = small_molecule_claim_vector(headline, cards)
    return build_key_signals(
        vec, rank_keys=("POTENCY", "ACTIVITY", "STRUCT", "DRUG", "DEGRADER"),
        support_fns={k: (lambda cl, _k=k: f"{_k}: {cl['signal']} ({cl['evidence']})") for k in
                     ("POTENCY", "ACTIVITY", "STRUCT", "DRUG", "DEGRADER")},
        critical_keys=("POTENCY", "STRUCT", "DRUG"), caveat_fns={},
        headline_fn=lambda v, s: ("Small-molecule tractable." if s else
                                  "Limited small-molecule tractability evidence."),
        fallback_caveat_fn=lambda: None)


__all__ = ["small_molecule_claim_vector", "small_molecule_key_signals", "SMALL_MOLECULE_CLAIM_SPEC"]
