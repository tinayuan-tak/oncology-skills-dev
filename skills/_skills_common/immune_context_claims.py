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
cohort for the indication, OR a cohort whose LEUKOCYTE denominator is the malignant clone
(`lymphoid_denominator_unreliable` — an absent MEASUREMENT, never read as measured absence). Kept out of
the nomination gate (verdict-bearing but gateless, pending calibration) — this projection is the
citable-atom surface for the cross-evidence reasoner.

THREE FRAME SCALARS gauge the class token, because it is a cohort MEDIAN of a RELATIVE fraction and each
of those three words hides something: `reference_frame` (the pan-cancer Q1/Q3 rank the token encodes),
`heterogeneity_frame` (the PREVALENCE of hot samples the median averages away) and `suppression_frame`
(the Treg/M2 load a bare hot call ignores). All descriptive; none gates.
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
    # UNMEASURED, explicitly — the leukocyte DENOMINATOR is the malignant clone (leukaemia / lymphoma /
    # lymphoid organ), so the CD8 SHARE is arithmetically valid and biologically uninterpretable. It maps
    # to `unmeasured` and NOT to `absent`: `absent` is a MEASURED effector-absence, and reading a missing
    # MEASUREMENT as measured absence would manufacture a TCE-efficacy risk in exactly the malignancies
    # where TCEs are the validated modality (glofitamab / mosunetuzumab in DLBCL). It is listed rather
    # than left to the `.get` default so the mapping is a stated decision a test can pin.
    "lymphoid_denominator_unreliable": "unmeasured",
    "data_unavailable": "unmeasured",
}
# The class tokens whose reference frame does not apply at all — no median is published for them, so
# every frame/gauge surface must say WHY rather than emit a bare "unmeasured".
_FRAME_INAPPLICABLE = "lymphoid_denominator_unreliable"

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
    s = c.get(_C_IMM) or {}
    cls = s.get("immune_context_class")
    ev = f"{_C_IMM}: {cls or 'data_unavailable'} (median CD8 frac={s.get('median_cd8_fraction')}"
    # the two QUALIFIERS of the cohort median ride the EVIDENCE string (hence the key_signals support line
    # and every atom that quotes it) — the median alone is the weakest part of this axis.
    if s.get("cd8_hot_sample_fraction") is not None:
        ev += f"; {round(float(s['cd8_hot_sample_fraction']) * 100, 1)}% of samples at/above the hot cut"
    if s.get("cd8_treg_ratio") is not None:
        ev += f"; CD8:Treg={s['cd8_treg_ratio']}"
    ev += ")"
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
            # HETEROGENEITY + SUPPRESSION (2026-09-12). The card has emitted these six since v1.2.0 and
            # NOTHING downstream read them — the mirror guard only checks card-declares -> reader-EMITS, so
            # it is structurally blind to a field the reader emits and no consumer consumes. They belong on
            # the CITABLE atom, not just in display prose: the cohort MEDIAN is the weakest part of this
            # axis, and these are the two fields that qualify it. All ADDITIVE and verdict-INERT.
            "cd8_hot_sample_fraction",  # PREVALENCE at the hot cut — the bimodal-cohort answer (MSI-H CRC)
            "cd8_treg_ratio",  # suppression: inflamed-but-SUPPRESSED != a bare hot call
            "cd8_m2_ratio",
            "median_treg_fraction",  # printed so a reader can see WHY a ratio abstained (noise floor)
            "median_m2_macrophage_fraction",
            "median_m1_macrophage_fraction",
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
    "for this indication); `low` = an orthogonal platform CONTRADICTS (and `conflict` names it). Three "
    "FRAME scalars qualify the token — reference_frame (pan-cancer rank), heterogeneity_frame (hot-sample "
    "PREVALENCE vs the cohort median) and suppression_frame (CD8:Treg / CD8:M2) — all descriptive, none "
    "gating: no pan-cancer distribution exists for a prevalence or a suppressor ratio yet."
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
    """One honest line gauging the CD8 read against its own frame. "unmeasured" when no cohort.

    The LYMPHOID token gets its OWN line rather than the bare "unmeasured" sentinel: those two abstentions
    are NOT the same claim. `data_unavailable` means there is no cohort; the lymphoid token means there IS
    a cohort and its reference frame does not apply — the very distinction the token was minted to carry,
    which collapsing onto "unmeasured" would throw away here after the card and the rule both preserved it."""
    s = c.get(_C_IMM) or {}
    cls, val = s.get("immune_context_class"), s.get("median_cd8_fraction")
    if cls == _FRAME_INAPPLICABLE:
        studies = s.get("tumor_studies")
        where = (
            "/".join(str(x) for x in studies)
            if isinstance(studies, (list, tuple))
            else (studies or "lymphoid TCGA study")
        )
        # No sample count is printed here, and n_samples is NOT consulted. The guard fires on the RESOLVED
        # study codes BEFORE the per-sample read, so nothing is ever loaded for these cohorts and the summary
        # carries n_samples=0 — a not-read sentinel, not a cohort size. Rendering it beside "the cohort exists"
        # would have this line refute its own first clause ("the cohort exists (DLBC, n=0)").
        return (
            f"frame DOES NOT APPLY: a cohort EXISTS for this indication ({where}; its size is deliberately "
            f"not read, so no count is quoted) but "
            f"its LEUKOCYTE denominator IS the malignant clone (leukaemia / lymphoma / lymphoid organ), so a "
            f"CD8 SHARE of that compartment is arithmetically valid and biologically uninterpretable. The "
            f"median is WITHHELD by design (not missing); {_REFERENCE_FRAME_BASIS} cannot gauge it. This is an "
            f"absent MEASUREMENT, NOT a measured effector absence — read no TCE-efficacy risk from it"
        )
    if not cls or cls == "data_unavailable" or val is None:
        return "unmeasured"
    return (
        f"median CD8 share {val} of the CIBERSORT LM22 LEUKOCYTE compartment (relative, not absolute "
        f"density; n={s.get('n_samples')} samples, cohort MEDIAN); {_REFERENCE_FRAME_BASIS} => `{cls}` is "
        f"a pan-cancer RANK of the CD8 share, NOT an absolute T-cell density and NOT a spatial or "
        f"functional read"
    )


# ── the HETEROGENEITY and SUPPRESSION frames (2026-09-12) ─────────────────────────────────────────
# Two named weaknesses of the primary read, each with a card field that answers it and no consumer that
# read it. Both are FRAME scalars in the `reference_frame` mould — prose that gauges the class token — and
# both are deliberately NON-GATING: no pan-cancer distribution exists for a hot-PREVALENCE or a CD8:Treg
# ratio the way 0.113/0.084 are the 33-study Q1/Q3 of the CD8 share, so any cut here would be an
# unanchored number wearing a threshold's clothes. Surface + frame now; derive cuts from the same
# 11,373-sample product before anything is allowed to demote on them.
_HOT_PREVALENCE_DIVERGENCE = 0.20  # |prevalence - median-implied| worth NAMING (not a gate; see above)


def _heterogeneity_frame(h, c) -> str:
    """Gauge the cohort MEDIAN against the PREVALENCE of hot samples inside the same cohort.

    The median is a poor summary of a BIMODAL cohort: MSI-H colorectal (~15% of CRC) is strongly
    infiltrated and the other ~85% is not, so the pooled median reads `immune_intermediate` and the
    patient population a TCE would actually be developed FOR is invisible in the token. Same threshold as
    the class, read as prevalence instead of central tendency."""
    s = c.get(_C_IMM) or {}
    cls, prev = s.get("immune_context_class"), s.get("cd8_hot_sample_fraction")
    if cls == _FRAME_INAPPLICABLE:
        return "unmeasured — the cohort's leukocyte denominator is uninterpretable (see reference_frame)"
    if not cls or cls == "data_unavailable" or prev is None:
        return "unmeasured"
    line = (
        f"{round(float(prev) * 100, 1)}% of the {s.get('n_samples')} samples sit AT/ABOVE the same hot cut "
        f"({_CD8_HOT_MIN}) that produced `{cls}` from the cohort MEDIAN — prevalence, not central tendency"
    )
    # The cases worth naming: a cohort the median calls not-hot that still has a substantial hot MINORITY
    # (the MSI-H CRC shape — a real TCE population the token hides), and its mirror.
    if cls != "immune_hot" and float(prev) >= _HOT_PREVALENCE_DIVERGENCE:
        return (
            f"{line}. The median does NOT read hot yet a substantial MINORITY of patients does — a "
            f"selectable TCE population the cohort-median token hides. Descriptive: this does NOT move "
            f"`{cls}` (no pan-cancer prevalence distribution exists to gauge it against yet)"
        )
    if cls == "immune_hot" and float(prev) < 0.5:
        return (
            f"{line}. The cohort ranks hot on its MEDIAN while FEWER THAN HALF of individual patients clear "
            f"the cut — read the hot token as a cohort rank, not as per-patient effector presence"
        )
    return line


def _suppression_frame(h, c) -> str:
    """Effector PRESENCE is only half a TCE-efficacy read: an inflamed-but-SUPPRESSED TME (Treg-high /
    M2-high) is a different proposition from a bare hot call. Ratios OF MEDIANS, so the two medians are
    printed beside them; NULL when the denominator median is at the LM22 noise floor (< 0.005) — an ABSENT
    denominator, not a small one (GBM's median Treg of 0.0002 otherwise turned CD8:Treg into 176 in an
    indication whose own class token says immune_cold)."""
    s = c.get(_C_IMM) or {}
    cls = s.get("immune_context_class")
    if cls == _FRAME_INAPPLICABLE:
        return "unmeasured — the cohort's leukocyte denominator is uninterpretable (see reference_frame)"
    if not cls or cls == "data_unavailable":
        return "unmeasured"
    treg, m2 = s.get("cd8_treg_ratio"), s.get("cd8_m2_ratio")
    parts = []
    if treg is not None:
        parts.append(f"CD8:Treg={treg} (median Treg {s.get('median_treg_fraction')})")
    if m2 is not None:
        parts.append(f"CD8:M2={m2} (median M2 {s.get('median_m2_macrophage_fraction')})")
    if not parts:
        return (
            f"suppression unmeasurable for `{cls}`: BOTH suppressor medians (Treg "
            f"{s.get('median_treg_fraction')}, M2 {s.get('median_m2_macrophage_fraction')}) sit at the LM22 "
            f"noise floor, so the ratios ABSTAIN rather than divide by an absent denominator"
        )
    return (
        f"suppression context for `{cls}`: " + "; ".join(parts) + ". Ratios OF MEDIANS within the same "
        f"LM22 leukocyte compartment (recomputable from the medians printed beside them). DESCRIPTIVE and "
        f"verdict-INERT — no pan-cancer distribution exists for these ratios yet, so a high suppressor load "
        f"is REPORTED, never allowed to demote `{cls}`"
    )


def immune_context_claim_vector(headline: dict, cards: list) -> dict:
    vec = build_claim_vector(IMMUNE_CONTEXT_CLAIM_SPEC, headline, cards, _DISCLAIMER)
    # NON-ATOM scalars (no `signal` key) — chips skip them, `skill_report.claim_scalars` carries them onto
    # the spine losslessly, so every consumer of the report sees the frames next to the class token.
    _c = cards_by_id(cards)
    vec["reference_frame"] = _reference_frame(headline, _c)
    vec["heterogeneity_frame"] = _heterogeneity_frame(headline, _c)
    vec["suppression_frame"] = _suppression_frame(headline, _c)
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
