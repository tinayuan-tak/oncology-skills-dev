"""immune_context_claims — immune-context's CLAIM VECTOR + KEY SIGNALS: a verdict-INERT projection of
the effector-arm (TCE) immune context into a citable claim.

immune-context is the EFFECTOR companion to surface-modality-fit: a T-cell engager can only redirect
cytotoxic T cells where they are PRESENT, so this axis asks "is the indication immune-hot — is there a
CD8 effector population?" (CIBERSORT LM22, gdc-pancanatlas-immune-2018). One axis:

  IMMUNE   CD8 T-cell effector context  (immune-context.immune_context_class)

DESCRIPTIVE (the effector-context call is INDICATION-level and target-INDEPENDENT in v1 — the same call
fires for every target in the indication; direction/meaning in the atom). A strong signal = immune-hot
(favourable for a TCE). `immune_cold` is `absent` — a MEASURED effector-absence (a TCE-efficacy RISK,
NOT a target-level veto; CIBERSORT is a RELATIVE, non-spatial screen). `unmeasured` = no CIBERSORT
cohort for the indication. Kept out of the nomination gate (verdict-bearing but gateless, pending
calibration) — this projection is the citable-atom surface for the cross-evidence reasoner.
"""
from __future__ import annotations

from _skills_common.claim_vector_core import ClaimSpec, build_claim_vector, build_key_signals

_IMMUNE_SIGNAL = {
    "immune_hot": "strong", "immune_intermediate": "moderate",
    "immune_cold": "absent",              # MEASURED effector-absence (TCE-efficacy risk, not a veto)
    "data_unavailable": "unmeasured",
}

_C_IMM = "immune-context"
_E_IMM = {"measurement_type": "immune_context", "grain": "indication"}

_INFORMS = ("TCE effector context — is the indication immune-hot (CD8 T cells present to redirect)? "
            "INDICATION-level / target-independent; immune_cold is an effector-absence efficacy risk for a "
            "T-cell engager, not a target-level veto")


def _immune_signal(h, c):
    cls = (c.get(_C_IMM) or {}).get("immune_context_class")
    ev = f"{_C_IMM}: {cls or 'data_unavailable'} (median CD8 frac={ (c.get(_C_IMM) or {}).get('median_cd8_fraction') })"
    return _IMMUNE_SIGNAL.get(cls, "unmeasured"), ev, None


def _immune_corr(h, c):
    return "moderate" if _IMMUNE_SIGNAL.get((c.get(_C_IMM) or {}).get("immune_context_class"), "unmeasured") != "unmeasured" else "unmeasured"


def _immune_atom(h, c):
    s = c.get(_C_IMM) or {}
    vals = {k: s[k] for k in ("immune_context_class", "median_cd8_fraction", "median_total_t_cell_fraction",
                              "n_samples", "tumor_studies") if s.get(k) is not None}
    if not vals:
        return None
    return {"read": s.get("immune_context_class"), "values": vals,
            "cite": {"card_id": _C_IMM, "fields": sorted(k for k in vals if k != "tumor_studies")}, "entity": _E_IMM}


IMMUNE_CONTEXT_CLAIM_SPEC = [
    ClaimSpec("IMMUNE", "TCE effector context", _immune_signal, _immune_corr, _INFORMS, _immune_atom),
]

_DISCLAIMER = (
    "Modality-blind, verdict-INERT projection of the immune-context effector axis (IMMUNE), signal×"
    "corroboration. DESCRIPTIVE + INDICATION-level (target-independent in v1): strong = immune-hot "
    "(TCE-favourable); `immune_cold` = `absent` (MEASURED effector-absence, a TCE-efficacy risk NOT a "
    "target veto — CIBERSORT is relative + non-spatial); `unmeasured` = no cohort. Never feeds a verdict.")


def immune_context_claim_vector(headline: dict, cards: list) -> dict:
    return build_claim_vector(IMMUNE_CONTEXT_CLAIM_SPEC, headline, cards, _DISCLAIMER)


def immune_context_key_signals(headline: dict, cards: list) -> dict:
    vec = immune_context_claim_vector(headline, cards)
    return build_key_signals(
        vec, rank_keys=("IMMUNE",),
        support_fns={"IMMUNE": lambda cl: f"IMMUNE: {cl['signal']} ({cl['evidence']})"},
        critical_keys=("IMMUNE",), caveat_fns={},
        headline_fn=lambda v, s: ("TCE effector context present (immune-hot/intermediate)." if s else
                                  "Immune-cold or unmeasured — limited TCE effector context."),
        fallback_caveat_fn=lambda: None)


__all__ = ["immune_context_claim_vector", "immune_context_key_signals", "IMMUNE_CONTEXT_CLAIM_SPEC"]
