"""tractability_claims — tractability-small-molecule's CLAIM VECTOR + KEY SIGNALS: a verdict-INERT
projection of the small-molecule druggability cards into (signal × corroboration) per orthogonal claim.

A concrete claim_vector_core instance. Five POSITIVE-valence axes (strong = strong druggability evidence):

  POTENCY   measured binding      — ChEMBL/BindingDB measured potency (pChEMBL / neglog M).
  ACTIVITY  functional compound   — PRISM cell-kill activity + clinical phase.
  STRUCT    ligandable pocket      — experimental/predicted ligandability, PDB/AlphaFold coverage.
  DRUG      known-drug pharmacology— approved-drug / druggable-genome tractability.
  DEGRADER  degrader feasibility   — E3-substrate evidence + degrader precedent.

Signals + atoms are read from the SOURCE card summaries (cards_by_id) for correct per-card citation.
Verdict-INERT: never feeds the druggability resolver; frozen by the skill's replay guards.
"""

from __future__ import annotations

from _skills_common.claim_vector_core import (
    ClaimSpec,
    build_claim_vector,
    build_key_signals,
    bump_corroboration,
    cap_corroboration,
)
from _skills_common.claim_vector_core import (
    corr as _corr_present,
)
from _skills_common.claim_vector_core import (
    signal_from_class as _sig,
)

_POTENCY_SIGNAL = {
    "potent_measured_ligand": "strong",
    "weak_measured_ligand": "moderate",
    "no_measured_activity": "absent",
    "data_unavailable": "unmeasured",
}
_ACTIVITY_SIGNAL = {
    "clinically_active": "strong",
    "clinical_precedent_only": "moderate",
    "tool_compound_only": "moderate",
    "weakly_active": "weak",
    "no_compounds_found": "absent",
    "data_unavailable": "unmeasured",
}
_STRUCT_SIGNAL = {
    "experimental_ligandable": "strong",
    "predicted_ligandable": "moderate",
    "annotation_ligandable": "weak",
    "no_ligandability_signal": "absent",
    "disordered_low": "negative",
    "insufficient_evidence": "unmeasured",
}
_DRUG_SIGNAL = {
    "approved_drug_tractable": "strong",
    "clinically_actionable": "strong",
    "druggable_genome": "moderate",
    "interaction_only": "weak",
    "category_only": "weak",
    "no_known_drug_evidence": "absent",
}
_DEGRADER_SIGNAL = {
    "precedented_degradable": "strong",
    "ubiquitination_substrate": "moderate",
    "plausible_untested": "weak",
    "unfavorable_location": "negative",
    "data_unavailable": "unmeasured",
}

_INFORMS = {
    "POTENCY": "measured binding potency — is there a compound that binds the target (chemical start)",
    "ACTIVITY": "functional compound activity — does a compound kill cells + clinical precedent",
    "STRUCT": "structural ligandability — is there a druggable pocket even absent a known compound",
    "DRUG": "known-drug pharmacology — approved-drug / druggable-genome tractability",
    "DEGRADER": "degrader feasibility — E3-substrate evidence + degrader precedent (PROTAC lens)",
}


from _skills_common.claim_vector_core import build_summary_atom  # shared atom builder (Group D)


def _atom(card_id, summary, keys, read):
    return build_summary_atom(
        card_id=card_id,
        summary=summary,
        keys=keys,
        read=read,
        entity={"measurement_type": "small_molecule_tractability", "grain": "target"},
    )


def _mk_atom(card, field, keys):
    def fn(h, c):
        return _atom(card, c.get(card) or {}, keys, (c.get(card) or {}).get(field))

    return fn


_C_POT, _C_ACT = "measured-potency-tractability", "prism-compound-activity"
_C_STR, _C_DRUG, _C_DEG = "structure-features-static", "known-drug-tractability", "degradation-feasibility"

# GDSC (Sanger) activity classes that AGREE with a PRISM-active call vs those that CONTRADICT it.
_GDSC_ACTIVE = {"potent_activity", "moderate_activity"}
_GDSC_INACTIVE = {"weak_activity", "no_compounds_found"}
# chemical-genetic concordance (prism-crispr-concordance): does the compound kill TRACK the genetic
# dependency (ON-target engagement) or NOT (off-target)?
_CONCORD_ONTARGET = {"triangulated_target_engaged", "crispr_confirmed_engagement", "rnai_confirmed_engagement"}
_CONCORD_OFFTARGET = {"discordant_off_target_likely"}


def _activity_corr(h, c):
    """ACTIVITY corroboration: PRISM (the signal source) is ONE drug-response platform → base corroboration.
    TWO genuinely INDEPENDENT arms then adjust it: (1) GDSC (Sanger, a 2nd drug-response platform) — an
    agreeing call bumps, a contradicting one caps; (2) the prism-crispr chemical-genetic CONCORDANCE
    (crispr_prism_concordance_class, the raw evidence class — NOT the verdict) — ON-target engagement bumps,
    an off-target-likely discordance caps (the measured cell-kill may not reflect ON-TARGET druggability).
    Was the single-source `_corr_present` proxy (dead-constant `moderate`). Verdict-INERT."""
    base = (
        "moderate"
        if _ACTIVITY_SIGNAL.get((c.get(_C_ACT) or {}).get("prism_activity_class"), "unmeasured") != "unmeasured"
        else "unmeasured"
    )
    if base == "unmeasured":
        return "unmeasured"
    gdsc = h.get("gdsc_activity_class")
    if gdsc in _GDSC_ACTIVE:
        base = bump_corroboration(base, True)  # independent agreeing platform → moderate→high
    elif gdsc in _GDSC_INACTIVE:
        base = cap_corroboration(base, "low")  # PRISM-active but GDSC-inactive → conflict caps
    concord = h.get("prism_crispr_concord")  # raw crispr_prism_concordance_class (evidence, not verdict)
    if concord in _CONCORD_ONTARGET:
        base = bump_corroboration(base, True)  # compound kill tracks the genetic dependency → on-target
    elif concord in _CONCORD_OFFTARGET:
        base = cap_corroboration(base, "low")  # off-target-likely → activity may not be on-target druggability
    return base


SMALL_MOLECULE_CLAIM_SPEC = [
    ClaimSpec(
        "POTENCY",
        "measured binding",
        _sig(_C_POT, "measured_bioactivity_class", _POTENCY_SIGNAL),
        _corr_present(_C_POT, "measured_bioactivity_class", _POTENCY_SIGNAL),
        _INFORMS["POTENCY"],
        _mk_atom(
            _C_POT,
            "measured_bioactivity_class",
            (
                "measured_bioactivity_class",
                "chembl_best_pchembl",
                "chembl_n_potent_ligands",
                "best_measured_potency_neglog_m",
                "chembl_max_clinical_phase",
                "bindingdb_best_p_affinity",
            ),
        ),
    ),
    ClaimSpec(
        "ACTIVITY",
        "functional compound",
        _sig(_C_ACT, "prism_activity_class", _ACTIVITY_SIGNAL),
        _activity_corr,
        _INFORMS["ACTIVITY"],
        _mk_atom(
            _C_ACT,
            "prism_activity_class",
            (
                "prism_activity_class",
                "n_compounds_targeting",
                "highest_clinical_phase",
                "median_log2auc_across_compounds",
            ),
        ),
    ),
    ClaimSpec(
        "STRUCT",
        "ligandable pocket",
        _sig(_C_STR, "structural_ligandability_class", _STRUCT_SIGNAL),
        _corr_present(_C_STR, "structural_ligandability_class", _STRUCT_SIGNAL),
        _INFORMS["STRUCT"],
        _mk_atom(
            _C_STR,
            "structural_ligandability_class",
            (
                "structural_ligandability_class",
                "pdb_coverage_class",
                "alphafold_confidence_class",
                "alphafold_plddt_mean",
                "pdb_best_resolution_angstrom",
                "hotspot_pocket_adjacency_call",
            ),
        ),
    ),
    ClaimSpec(
        "DRUG",
        "known-drug pharmacology",
        _sig(_C_DRUG, "known_drug_tractability_class", _DRUG_SIGNAL),
        _corr_present(_C_DRUG, "known_drug_tractability_class", _DRUG_SIGNAL),
        _INFORMS["DRUG"],
        _mk_atom(
            _C_DRUG,
            "known_drug_tractability_class",
            (
                "known_drug_tractability_class",
                "druggability_tier",
                "has_approved_drug",
                "n_antineoplastic_interactions",
                "n_approved_drug_interactions",
            ),
        ),
    ),
    ClaimSpec(
        "DEGRADER",
        "degrader feasibility",
        _sig(_C_DEG, "degradability_feasibility_class", _DEGRADER_SIGNAL),
        _corr_present(_C_DEG, "degradability_feasibility_class", _DEGRADER_SIGNAL),
        _INFORMS["DEGRADER"],
        _mk_atom(
            _C_DEG,
            "degradability_feasibility_class",
            (
                "degradability_feasibility_class",
                "e3_substrate_evidence",
                "n_e3_ligases_literature",
                "degrader_precedent",
            ),
        ),
    ),
]

_DISCLAIMER = (
    "Modality-blind, verdict-INERT projection of the small-molecule druggability cards into orthogonal "
    "claims (POTENCY / ACTIVITY / STRUCT / DRUG / DEGRADER), each signal×corroboration. POSITIVE valence "
    "(strong = strong druggability). Claims are NOT averaged. Never feeds the druggability verdict."
)


def small_molecule_claim_vector(headline: dict, cards: list) -> dict:
    return build_claim_vector(SMALL_MOLECULE_CLAIM_SPEC, headline, cards, _DISCLAIMER)


# The resolved druggability_snapshot NEGATIVE tokens (off-target / intractable / unhit). When the
# resolver lands one of these, key_signals must NOT read "Small-molecule tractable." off the
# positive-valence claim decomposition -- that would CONTRADICT the resolved negative verdict (a chemical
# hit that is off-target still lights up the ACTIVITY/POTENCY axes). Mirrors the FR #874 / selectivity
# #862 head()-over-claim fix. VERDICT-INERT: reads the already-resolved snapshot, never moves it; the
# POSITIVE / insufficient paths are byte-identical to the prior binary headline.
_NEGATIVE_SNAPSHOT_HEADLINE = {
    "discordant": "Chemical activity is off-target (discordant with the genetic "
    "dependency) — argues against small-molecule tractability.",
    "structurally_intractable": "Structurally intractable — no small-molecule handle.",
    "chemically_unhit": "No compound found — small-molecule tractability unestablished.",
    # directness gate (resolver v1.5.0): an approved drug is catalogued but the DGIdb roster is INDIRECT
    # (no direct binder) — must NOT read "tractable" off the positive-valence DRUG/POTENCY axes.
    "annotation_only_indirect": "Approved drugs are catalogued but INDIRECT (pathway/downstream) — no "
    "direct small-molecule binder established.",
}


def small_molecule_key_signals(headline: dict, cards: list) -> dict:
    vec = small_molecule_claim_vector(headline, cards)
    v = (headline or {}).get("druggability_snapshot")
    neg_headline = _NEGATIVE_SNAPSHOT_HEADLINE.get(v)

    def _headline_fn(_vec, supports):
        # A resolved NEGATIVE snapshot wins the headline over the positive-valence claim signals -- a
        # discordant/intractable/unhit call must never read as "tractable".
        if neg_headline:
            return neg_headline
        return "Small-molecule tractable." if supports else "Limited small-molecule tractability evidence."

    def _fallback_caveat():
        # For a discordant read, surface the off-target caveat even when no weak-critical claim fires --
        # the concordance conflict is the point (mirrors headline_block.top_tension).
        if v == "discordant":
            concord = (headline or {}).get("prism_crispr_concord")
            return "chemical activity does not track the CRISPR/RNAi genetic dependency (off-target)" + (
                f"; concordance: {concord}" if concord else ""
            )
        return None

    return build_key_signals(
        vec,
        rank_keys=("POTENCY", "ACTIVITY", "STRUCT", "DRUG", "DEGRADER"),
        support_fns={
            k: (lambda cl, _k=k: f"{_k}: {cl['signal']} ({cl['evidence']})")
            for k in ("POTENCY", "ACTIVITY", "STRUCT", "DRUG", "DEGRADER")
        },
        critical_keys=("POTENCY", "STRUCT", "DRUG"),
        caveat_fns={},
        headline_fn=_headline_fn,
        fallback_caveat_fn=_fallback_caveat,
    )


__all__ = ["small_molecule_claim_vector", "small_molecule_key_signals", "SMALL_MOLECULE_CLAIM_SPEC"]
