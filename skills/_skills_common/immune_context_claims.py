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

from _skills_common.claim_vector_core import (
    ClaimSpec,
    build_atom,
    build_claim_vector,
    build_key_signals,
    cards_by_id,
)

_IMMUNE_SIGNAL = {
    "immune_hot": "strong",
    "immune_intermediate": "moderate",
    "immune_cold": "absent",  # MEASURED effector-absence (TCE-efficacy risk, not a veto)
    "data_unavailable": "unmeasured",
}

_C_IMM = "immune-context"
_E_IMM = {"measurement_type": "immune_context", "grain": "indication"}

_INFORMS = (
    "TCE effector context — is the indication immune-hot (CD8 T cells present to redirect)? "
    "INDICATION-level / target-independent; immune_cold is an effector-absence efficacy risk for a "
    "T-cell engager, not a target-level veto"
)


# ── the CORROBORATION ruler (card data ruler for the IMMUNE axis) ─────────────────────────────────
# TWO ORTHOGONAL platforms can check the relative-CIBERSORT CD8 read, and both are already on the
# headline by the time the claim vector is built:
#   * ABSOLUTE H&E-DL TIL density (tcga-til-fraction-saltz)      -> til_cibersort_agreement True/False/None
#   * SPATIAL co-localization (spatial-tumor-normal-colocalization) -> spatial_immune_phenotype
#                                                                     inflamed / excluded / indeterminate
# Until 2026-09-12 `_immune_corr` returned the CONSTANT "moderate" for every measured indication and
# `_immune_signal` always returned conflict=None. Consequence: headline_block.confidence and
# skill_report.confidence were a CONSTANT "moderate" — `strong` and `weak` were UNREACHABLE, and
# derive_confidence's conflict cap + coverage floor were dead code on this single-axis skill. A
# DISCORDANT PRAD (relative-CD8-hot but absolute-TIL-LOW) read exactly as confidently as a
# corroborated SKCM. The ruler below makes the tier track the orthogonal-platform state instead.
#
# CORROBORATION_ORD: high > moderate > low > unmeasured; _CORR_TO_CONF maps high->strong,
# moderate->moderate, low->weak (headline_core.py), so the three tiers are all reachable.
_CORR_CORROBORATED = "high"  # an orthogonal ABSOLUTE / SPATIAL platform AGREES  -> confidence strong
_CORR_SINGLE = "moderate"  # CIBERSORT alone; no orthogonal check for this indication -> moderate
_CORR_CONTRADICTED = "low"  # an orthogonal platform DISAGREES -> confidence weak + a conflict atom

_POSITIVE_SIGNALS = ("strong", "moderate")  # immune_hot / immune_intermediate (effectors claimed present)


_HOT_CLASSES = ("immune_hot", "immune_inflamed", "t_cell_inflamed")


def orthogonal_discordance_text(headline: dict) -> "str | None":
    """The ONE prose builder for an orthogonal-platform CONTRADICTION of the relative-CIBERSORT call.

    Two sources, absolute-TIL first (it checks DENSITY, the more basic claim; spatial checks LOCALIZATION
    only once density is granted):

      1. absolute H&E-DL TIL (Saltz) — `til_cibersort_agreement is False`. CIBERSORT gives the CD8 SHARE
         of the leukocyte compartment (RELATIVE); Saltz gives the ABSOLUTE lymphocyte fraction from
         morphology. A relatively-CD8-rich but absolutely-T-cell-sparse indication (PRAD) reads
         immune_hot while the absolute effector density is low — the "effectors present to redirect" read
         OVER-claims. Symmetric for a cold call the absolute TIL contradicts.
      2. SPATIAL co-localization — `spatial_immune_phenotype` EXCLUDED on a positive read (effectors in
         the compartment but not adjacent to the target-positive malignant cells: nothing to redirect in
         the nest) or INFLAMED on an immune_cold one (the cohort median under-calls a local niche).

    None when no orthogonal platform contradicts. This is the SINGLE source for the claim's `conflict`
    atom, the key_signals caveat and the headline top_tension, so those three cannot drift apart."""
    icls = headline.get("immune_context_class")
    if headline.get("til_cibersort_agreement") is False:
        tcls = headline.get("til_fraction_class")
        tpct = headline.get("median_til_percentage")
        tail = f"absolute H&E-DL TIL={tcls}" + (f" (median {tpct}%)" if tpct is not None else "")
        if icls in _HOT_CLASSES:
            return (
                f"relative-CIBERSORT immune-hot DISAGREES with the orthogonal {tail}: CD8-rich SHARE but "
                f"low ABSOLUTE lymphocyte density — few effectors to redirect. Interpret the TCE-favourable "
                f"read with caution (CIBERSORT is relative + non-spatial)."
            )
        return (
            f"relative-CIBERSORT immune-cold DISAGREES with the orthogonal {tail}: the absolute lymphocyte "
            f"read is HIGHER than the relative CD8 share implies — the effector-absence call may understate "
            f"the TME (CIBERSORT is relative + non-spatial)."
        )
    pheno = headline.get("spatial_immune_phenotype")
    if pheno == "excluded" and icls in _HOT_CLASSES + ("immune_intermediate",):
        return (
            f"orthogonal SPATIAL co-localization reads IMMUNE-EXCLUDED while the bulk CIBERSORT call is "
            f"{icls}: the CD8 effectors are in the leukocyte compartment but DEPLETED from the "
            f"target-positive malignant neighbourhood — a TCE has nothing to redirect in the nest. This is "
            f"the inflamed-vs-excluded distinction a bulk fraction structurally cannot make."
        )
    if pheno == "inflamed" and icls in ("immune_cold", "immune_desert", "cold"):
        return (
            f"orthogonal SPATIAL co-localization reads an IMMUNE-RICH niche around the target-positive "
            f"malignant cells while the bulk CIBERSORT call is {icls}: the pan-cancer-ranked cohort MEDIAN "
            f"relative fraction UNDER-calls the local effector context."
        )
    return None


def _orthogonal_check(h, signal):
    """(corroboration_tier, conflict|None) from the orthogonal ABSOLUTE-TIL and SPATIAL platforms.

    A CONTRADICTION always wins over a corroboration (weakest-link honesty): the read we are least
    entitled to make is the one the consumer must see. Returns ("unmeasured", None) when the primary
    CIBERSORT read itself is absent — there is nothing to corroborate."""
    if signal not in _POSITIVE_SIGNALS and signal != "absent":
        return "unmeasured", None
    conflict = orthogonal_discordance_text(h)
    if conflict:
        return _CORR_CONTRADICTED, conflict

    # CORROBORATIONS — an orthogonal platform agrees (absolute density, or the matching spatial phenotype).
    positive = signal in _POSITIVE_SIGNALS
    if h.get("til_cibersort_agreement") is True:
        return _CORR_CORROBORATED, None
    if h.get("spatial_immune_phenotype") == ("inflamed" if positive else "excluded"):
        return _CORR_CORROBORATED, None

    # Single-platform: CIBERSORT is the only read (no Saltz coverage / no coloc product / not
    # directionally comparable). Honest middle tier — measured, but unconfirmed.
    return _CORR_SINGLE, None


def _immune_signal(h, c):
    cls = (c.get(_C_IMM) or {}).get("immune_context_class")
    ev = f"{_C_IMM}: {cls or 'data_unavailable'} (median CD8 frac={(c.get(_C_IMM) or {}).get('median_cd8_fraction')})"
    signal = _IMMUNE_SIGNAL.get(cls, "unmeasured")
    return signal, ev, _orthogonal_check(h, signal)[1]


def _immune_corr(h, c):
    signal = _IMMUNE_SIGNAL.get((c.get(_C_IMM) or {}).get("immune_context_class"), "unmeasured")
    return "unmeasured" if signal == "unmeasured" else _orthogonal_check(h, signal)[0]


def _immune_atom(h, c):
    s = c.get(_C_IMM) or {}
    vals = {
        k: s[k]
        for k in (
            "immune_context_class",
            "median_cd8_fraction",
            "median_total_t_cell_fraction",
            "n_samples",
            "tumor_studies",
        )
        if s.get(k) is not None
    }
    return build_atom(
        card_id=_C_IMM,
        values=vals,
        read=s.get("immune_context_class"),
        entity=_E_IMM,
        exclude_fields=("tumor_studies",),
    )


IMMUNE_CONTEXT_CLAIM_SPEC = [
    ClaimSpec("IMMUNE", "TCE effector context", _immune_signal, _immune_corr, _INFORMS, _immune_atom),
]

_DISCLAIMER = (
    "Modality-blind, verdict-INERT projection of the immune-context effector axis (IMMUNE), signal×"
    "corroboration. DESCRIPTIVE + INDICATION-level (target-independent in v1): strong = immune-hot "
    "(TCE-favourable); `immune_cold` = `absent` (MEASURED effector-absence, a TCE-efficacy risk NOT a "
    "target veto — CIBERSORT is relative + non-spatial); `unmeasured` = no cohort. Never feeds a verdict. "
    "CORROBORATION is the orthogonal-platform ruler, not a constant: `high` = an ABSOLUTE H&E-DL TIL "
    "(Saltz) or SPATIAL co-localization read AGREES; `moderate` = CIBERSORT alone (no orthogonal check "
    "for this indication); `low` = an orthogonal platform CONTRADICTS (and `conflict` names it)."
)


# ── the REFERENCE-FRAME ruler (S2 honesty) ────────────────────────────────────────────────────────
# `immune_hot` / `immune_cold` READ as absolute biology but ENCODE a pan-cancer PERCENTILE: the cuts ARE
# the Q1/Q3 of the 33-study CIBERSORT distribution, so ~9 studies are hot and ~9 cold BY CONSTRUCTION.
# Measured consequence of leaving that implicit: ICI-approved BLCA (0.1103) / LUAD (0.0876) / LUSC
# (0.0974) / COAD (0.1023) all read `immune_intermediate`, while clinically-COLD PRAD (0.1312) and
# indolent THCA (0.1230) read `immune_hot`. The ruler names the frame so the token cannot be mistaken
# for an absolute T-cell density. A STRING scalar (the `homogeneity` precedent) — the evidence_package
# claim_vector schema is oneOf[string, object], and a string renders verbatim in every consumer.
_CD8_HOT_MIN, _CD8_COLD_MAX = 0.113, 0.084  # pan-cancer Q3 / Q1; mirrors methods/immune_context/classify.py
_REFERENCE_FRAME_BASIS = (
    f"pan-cancer cuts Q1={_CD8_COLD_MAX} (cold) / Q3={_CD8_HOT_MIN} (hot) over 33 TCGA studies "
    f"(pancanatlas-cibersort-lm22-per-sample-v1, 11,373 samples)"
)


def _reference_frame(h, c) -> str:
    """One honest line gauging the CD8 read against its own frame. "unmeasured" when no cohort."""
    s = c.get(_C_IMM) or {}
    cls, val = s.get("immune_context_class"), s.get("median_cd8_fraction")
    if not cls or cls == "data_unavailable" or val is None:
        return "unmeasured"
    return (
        f"median CD8 share {val} of the CIBERSORT LM22 LEUKOCYTE compartment (relative, not absolute "
        f"density; n={s.get('n_samples')} samples, cohort MEDIAN); {_REFERENCE_FRAME_BASIS} => `{cls}` is "
        f"a pan-cancer RANK of the CD8 share, NOT an absolute T-cell density and NOT a spatial or "
        f"functional read"
    )


def immune_context_claim_vector(headline: dict, cards: list) -> dict:
    vec = build_claim_vector(IMMUNE_CONTEXT_CLAIM_SPEC, headline, cards, _DISCLAIMER)
    # A NON-ATOM scalar (no `signal` key) — chips skip it, `skill_report.claim_scalars` carries it onto
    # the spine losslessly, so every consumer of the report sees the frame next to the class token.
    vec["reference_frame"] = _reference_frame(headline, cards_by_id(cards))
    return vec


def _til_discordance_caveat(headline: dict):
    """The key_signals caveat for an orthogonal-platform contradiction. Thin alias over the single prose
    builder `orthogonal_discordance_text` (kept under the historical name for its importers)."""
    return orthogonal_discordance_text(headline)


def immune_context_key_signals(headline: dict, cards: list) -> dict:
    vec = immune_context_claim_vector(headline, cards)
    # An ORTHOGONAL-platform disagreement qualifies the headline and supplies the caveat — the relative
    # hot/cold call is contradicted by an absolute-density or spatial card, so the deterministic surface
    # must not read a bald "effector context present". Sourced from the claim's own `conflict` atom (the
    # single ruler in `_orthogonal_check`) so headline text, corroboration tier and caveat cannot drift.
    discord = bool((vec.get("IMMUNE") or {}).get("conflict"))

    def _head(v, s):
        base = (
            "TCE effector context present (immune-hot/intermediate)."
            if s
            else "Immune-cold or unmeasured — limited TCE effector context."
        )
        if discord:
            _src = (
                "absolute H&E-DL TIL" if headline.get("til_cibersort_agreement") is False else "spatial co-localization"
            )
            return base.rstrip(".") + f" — but the {_src} read disagrees (interpret with caution)."
        return base

    return build_key_signals(
        vec,
        rank_keys=("IMMUNE",),
        support_fns={"IMMUNE": lambda cl: f"IMMUNE: {cl['signal']} ({cl['evidence']})"},
        critical_keys=("IMMUNE",),
        caveat_fns={},
        headline_fn=_head,
        fallback_caveat_fn=lambda: _til_discordance_caveat(headline),
    )


__all__ = [
    "immune_context_claim_vector",
    "immune_context_key_signals",
    "orthogonal_discordance_text",
    "IMMUNE_CONTEXT_CLAIM_SPEC",
]
