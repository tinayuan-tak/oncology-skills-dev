"""target_intrinsic_claims — target-intrinsic's CLAIM VECTOR + KEY SIGNALS: a verdict-INERT projection
of the indication-INDEPENDENT target dossier into orthogonal (signal × corroboration) claims with
citable atoms.

A concrete claim_vector_core instance. target-intrinsic is a mostly-descriptive `tier: target`
dossier whose safety/structure/mechanism facts are HOME'd (and claim-decomposed) under their owning
subskills. Only the two fields UNIQUE to target-intrinsic that carry a defensible ordinal/routing
signal are projected here — the two most relevant to HYPOTHESIS + MODALITY FIT:

  MODALITY_ROUTING       domain→modality implication  (domain-modality-relevance)
  TRACTABILITY_PRECEDENT Pharos/IDG development level  (target-development-level)

Both are DESCRIPTIVE (direction / meaning in the atom, not the tier): MODALITY_ROUTING's tier is the
CONVICTION of the routing call (the inhibitor-vs-removal DIRECTION lives in the atom); TRACTABILITY_
PRECEDENT's tier is the strength of drug-development PRECEDENT for the target's mode (Tdark is `absent`
= measured no-precedent, NOT adverse — an understudied target may be a feature). Both source cards are
in the target-intrinsic composer entry, so this projection populates in the COMPOSED profile.

Verdict-INERT: target-intrinsic is gateless (verdict_fn=None); this never feeds a resolver.
"""
from __future__ import annotations

from _skills_common.claim_vector_core import ClaimSpec, build_claim_vector, build_key_signals

# domain→modality implication — tier = CONVICTION of the routing call; direction is in the atom.
_MODALITY_SIGNAL = {
    "removal_required_scaffolding": "strong",   # high-conviction: a scaffolding function → degrader/removal
    "removal_favored": "moderate", "inhibitor_sufficient": "moderate",
    "context_dependent": "weak",
    "indeterminate": "absent",                  # MEASURED: heuristic can't call (e.g. multi-domain enzyme)
    "data_unavailable": "unmeasured",
}
# modality_implication_basis → corroboration strength of the routing call
_MODALITY_BASIS_CORR = {"curated": "high", "heuristic": "low", "none": "unmeasured"}

# Pharos/IDG Target Development Level — tier = drug-development PRECEDENT for the target's mode.
_TDL_SIGNAL = {
    "Tclin": "strong", "Tchem": "moderate", "Tbio": "weak",
    "Tdark": "absent",                          # MEASURED: no probe/precedent (NOT adverse — may be a feature)
    "data_unavailable": "unmeasured",
}

_INFORMS = {
    "MODALITY_ROUTING": ("domain→modality implication — inhibitor-sufficient vs removal-required "
                         "(degrader/scaffolding); a MODALITY-FIT routing hint (direction in the atom)"),
    "TRACTABILITY_PRECEDENT": ("Pharos/IDG development level — strength of drug-development PRECEDENT for "
                               "the target's mode (Tdark = understudied, not adverse)"),
}

_C_MOD = "domain-modality-relevance"
_C_TDL = "target-development-level"

_E_MOD = {"measurement_type": "domain_modality_relevance", "grain": "target"}
_E_TDL = {"measurement_type": "target_development_level", "grain": "target"}


def _modality_signal(h, c):
    s = c.get(_C_MOD) or {}
    cls = s.get("modality_implication_class")
    return (_MODALITY_SIGNAL.get(cls, "unmeasured"),
            f"{_C_MOD}: {cls or 'data_unavailable'} (basis={s.get('modality_implication_basis') or 'none'})", None)


def _modality_corr(h, c):
    s = c.get(_C_MOD) or {}
    if _MODALITY_SIGNAL.get(s.get("modality_implication_class"), "unmeasured") == "unmeasured":
        return "unmeasured"
    return _MODALITY_BASIS_CORR.get(s.get("modality_implication_basis"), "low")


def _tdl_signal(h, c):
    cls = (c.get(_C_TDL) or {}).get("tdl_class")
    return _TDL_SIGNAL.get(cls, "unmeasured"), f"{_C_TDL}: {cls or 'data_unavailable'}", None


def _tdl_corr(h, c):
    return "moderate" if _TDL_SIGNAL.get((c.get(_C_TDL) or {}).get("tdl_class"), "unmeasured") != "unmeasured" else "unmeasured"


from _skills_common.claim_vector_core import build_summary_atom  # shared atom builder (Group D)


def _atom(card_id, summary, keys, entity, read):
    return build_summary_atom(card_id=card_id, summary=summary, keys=keys, read=read, entity=entity)


def _modality_atom(h, c):
    s = c.get(_C_MOD) or {}
    return _atom(_C_MOD, s, ("modality_implication_class", "modality_implication_basis",
                             "scaffolding_function", "modality_context"), _E_MOD,
                 s.get("modality_implication_class"))


def _tdl_atom(h, c):
    s = c.get(_C_TDL) or {}
    return _atom(_C_TDL, s, ("tdl_class", "tdl_meaning", "target_family", "novelty_score"), _E_TDL,
                 s.get("tdl_class"))


TARGET_INTRINSIC_CLAIM_SPEC = [
    ClaimSpec("MODALITY_ROUTING", "domain→modality implication", _modality_signal, _modality_corr,
              _INFORMS["MODALITY_ROUTING"], _modality_atom),
    ClaimSpec("TRACTABILITY_PRECEDENT", "Pharos/IDG development level", _tdl_signal, _tdl_corr,
              _INFORMS["TRACTABILITY_PRECEDENT"], _tdl_atom),
]

_DISCLAIMER = (
    "Modality-blind, verdict-INERT projection of the two target-intrinsic fields that carry a defensible "
    "signal (MODALITY_ROUTING / TRACTABILITY_PRECEDENT) — the dossier's safety/structure/mechanism facts "
    "are claim-decomposed under their OWNING subskills, not here. DESCRIPTIVE: MODALITY_ROUTING's tier is "
    "the CONVICTION of the routing call (inhibitor-vs-removal DIRECTION in the atom); TRACTABILITY_"
    "PRECEDENT's tier is drug-development precedent strength (Tdark = understudied, `absent` not adverse). "
    "Claims are NOT averaged; target-intrinsic is gateless — this never feeds a verdict.")


def target_intrinsic_claim_vector(headline: dict, cards: list) -> dict:
    return build_claim_vector(TARGET_INTRINSIC_CLAIM_SPEC, headline, cards, _DISCLAIMER)


def target_intrinsic_key_signals(headline: dict, cards: list) -> dict:
    vec = target_intrinsic_claim_vector(headline, cards)
    return build_key_signals(
        vec, rank_keys=("MODALITY_ROUTING", "TRACTABILITY_PRECEDENT"),
        support_fns={k: (lambda cl, _k=k: f"{_k}: {cl['signal']} ({cl['evidence']})") for k in
                     ("MODALITY_ROUTING", "TRACTABILITY_PRECEDENT")},
        critical_keys=("MODALITY_ROUTING",), caveat_fns={},
        headline_fn=lambda v, s: ("Target-intrinsic modality/tractability context present." if s else
                                  "Limited target-intrinsic modality/tractability signal."),
        fallback_caveat_fn=lambda: None)


__all__ = ["target_intrinsic_claim_vector", "target_intrinsic_key_signals", "TARGET_INTRINSIC_CLAIM_SPEC"]
