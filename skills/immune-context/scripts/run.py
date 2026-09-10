#!/usr/bin/env python3
"""immune-context — EFFECTOR-arm wired skill (new 2026-08-06, biologics-augment).

The effector companion to surface-modality-fit. A T-cell engager redirects cytotoxic T cells to the
antigen, so it can only work where T cells are PRESENT. surface-modality-fit answers "is there a
surface target?"; this answers the orthogonal "is the tumor immune-hot — is there a CD8 effector
population to redirect?" (IO-target-ID seed note method #2). Consumes the immune-context card
(CIBERSORT LM22 T-cell infiltration from gdc-pancanatlas-immune-2018).

Deliberately a STANDALONE skill, NOT a card inside surface-modality-fit: immune context is the
effector axis, orthogonal to surface biology — a TCE needs BOTH. It composes into the TCE story
ALONGSIDE surface-modality-fit.

v1 is per-indication / target-INDEPENDENT (tier: indication); the antigen-conditioned join (are the
ANTIGEN-HIGH patients also T-cell-high?) is a deferred v2 facet. The verdict is a direct read of the
immune_context_class categorical (a descriptive effector-context call — no cross-card resolver).
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common import get_card_field
from _skills_common.claim_record import assemble_claim_record
from _skills_common.dispatcher import run_wired_skill
from _skills_common.headline_core import HeadlineSpec, build_headline
from _skills_common.headline_hero import emit_headline_hero
from _skills_common.immune_context_claims import immune_context_claim_vector, immune_context_key_signals
from _skills_common.immune_context_question_table import immune_context_question_table
from _skills_common.literature_retrieval import default_retrieve, verify_citations
from _skills_common.literature_synthesis import make_literature_fn
from _skills_common.narrator_engine import make_synthesize_fn
from _skills_common.narrator_lenses import IMMUNE_CONTEXT as _LENS
from _skills_common.skill_report import ROLE_DESCRIPTIVE, build_skill_report
from _skills_common.subgroup_derivation import make_value_classifier

# Signals-first sub-group reader (VERDICT-INERT). Thesis: CD8/immune infiltration present (TCE effector
# arm). The fleet-default heuristic tags these context values `absent`; default_classify is the fallback.
_IMMUNE_VALUE_TIERS = {
    "immune_hot": "strong",
    "immune_inflamed": "strong",
    "t_cell_inflamed": "strong",
    "immune_intermediate": "moderate",
    "immune_excluded": "weak",
    "immune_cold": "weak",
    "immune_desert": "absent",
    "caf_subset_detected": "moderate",
    "caf_dominant": "moderate",
}

SKILL_NAME = "immune-context"
SKILL_VERSION = "1.7.0"  # 1.7.0 (2026-09-10): T0-4 — wire spatial-tumor-normal-colocalization (GeoMx/Xenium/CosMx) into the IMMUNE spine. VERDICT-INERT: adds spatial_immune_phenotype (inflamed / excluded / spatial_immune_indeterminate) — the spatial resolution of the inflamed-vs-excluded TCE call the bulk CD8 FRACTION structurally cannot make (the exact gap _spatial_localization_caveat concedes); the spatial bite_tce rules are NOT in _RULE_TO_VERDICT so the gateless immune_context_verdict spine stays byte-stable. data_unavailable outside the ~6 coloc-covered indication families (degrades honestly). Clean three-way inflamed/excluded/DESERT needs an absolute-adjacency desert threshold in the analysis-methods classifier (fast-follow).   # 1.6.1 (2026-09-04): VERDICT-INERT display follow-ups — Saltz median_number_of_clusters spatial-aggregation hint (clustered-vs-dispersed TIL, a first spatial proxy the CD8 FRACTION lacks) into immune_provenance; SURFACE the immune-context card's antigen-CONDITIONED join (antigen_conditioned_call / cd8_high_minus_low / antigen_high_immune_context_class — the ONLY target-dependent display fields; addresses the cohort-median heterogeneity blind spot = are the antigen-HIGH patients T-cell-POORER = effector escape) via _cf() defensive getter; data_unavailable when the join is thin. Verdict spine byte-stable. NOTE: the ici-response-imvigor210 display card MISSES a legacy-symbol target (NECTIN4->PVRL4 in the genentech eSet) — a data-product resolver gap, verdict-inert (filed, cross-repo).   # 1.6.0 (2026-09-04): --literature lane (make_literature_fn(IMMUNE_CONTEXT)) + VERDICT-INERT surfacing of the bulk-CD8-fraction annotation-INFLATION (immune_confirmation_caveat: a positive bulk CIBERSORT read resting on a RELATIVE/non-spatial/function-blind fraction w/o spatial or orthogonal-absolute-TIL confirmation — tiers bulk_fraction_til_discordant / bulk_fraction_spatially_unconfirmed / orthogonally_corroborated[false-demote guard]; spatial_localization_caveat inflamed-vs-excluded-vs-desert; immune_provenance quorum) + IMMUNE_CONTEXT thesis + polarity_note (was NONE). Spine byte-stable (gateless; verdict = direct read of immune_context_class).   # 1.4.0 (2026-08-28): + tcga-til-fraction-saltz (absolute H&E-DL TIL corroborator, VERDICT-INERT).   # 1.3.0: capsule-driven narrator via generic engine.   # 1.2.0 (2026-08-27): tuned signals-first sub-group reader. Verdict-INERT.   # 1.1.0: + canonical HEADLINE block (verdict + confidence + top tension) &
# headline hero — a verdict-INERT projection over the effector-context
# claim_vector / key_signals. Spine byte-stable (gateless; verdict unchanged).

CARDS = [
    "immune-context",
    # VERDICT-INERT TME/immune display cards (wired 2026-08-25). immune-context is GATELESS and its
    # verdict is a direct read of immune_context_class (see _verdict), so these fire no rule and leave
    # the effector-context verdict byte-stable — they add pan-cancer TME composition (myeloid + CAF) and
    # the outcome-anchored melanoma ICI-response association as display/context alongside the CD8 call.
    "myeloid-compartment-expression-cheng",  # pan-cancer tumour-infiltrating myeloid states (suppressive-TME / myeloid-target)
    "caf-compartment-expression-luo",  # pan-cancer CAF states (stromal lens; stroma-vs-malignant denominator)
    "ici-response-association",  # per-gene ICI (anti-PD-1) responder-vs-non-responder association (melanoma-scoped)
    "ici-response-imvigor210",  # urothelial ICI (atezolizumab) response + desert/excluded/inflamed phenotype (IMvigor210); verdict-inert
    "tcga-til-fraction-saltz",  # absolute H&E-DL TIL fraction (Saltz 2018) — VERDICT-INERT
    # corroborator of the CIBERSORT CD8 hot/cold call (morphology vs
    # RNA deconvolution, same TCGA participants); fires no rule.
    "spatial-tumor-normal-colocalization",  # T0-4: GeoMx/Xenium/CosMx spatial co-localization — resolves the
    # INFLAMED (immune adjacent to target-high malignant cells) vs IMMUNE-EXCLUDED (immune segregated to
    # peritumoral stroma — a TCE liability) call the bulk CD8 FRACTION structurally cannot make (the exact
    # gap _spatial_localization_caveat concedes). VERDICT-INERT: the spatial-immune bite_tce rules
    # (surface-intrinsic.rules.yaml) are NOT in _RULE_TO_VERDICT, so the gateless immune_context_verdict
    # spine stays byte-stable; surfaced as the spatial_immune_phenotype facet. data_unavailable outside the
    # ~6 coloc-covered indication families (degrades honestly).
]

QUESTION = (
    "For {indication}, is the tumor immune-hot or immune-cold — is there a CD8 T-cell "
    "effector population present for a T-cell engager to redirect (independent of {target})?"
)

# The immune-context rules (surface-intrinsic.rules.yaml) that fire on immune_context_class, mapped to
# this skill's effector-context verdict. The skill's verdict IS the immune-context class, resolved from
# the FIRED rule (the standard framework pattern — the categorical drives a rule, the rule drives the
# verdict), so the signal is also visible to any downstream composer, not just this skill.
_RULE_TO_VERDICT = {
    "immune-context-hot-tce-supportive": "immune_hot",
    "immune-context-intermediate-tce-neutral": "immune_intermediate",
    "immune-context-cold-tce-opposing": "immune_cold",
}


def _cf(cards, card_id, field):
    """Defensive get_card_field for OPTIONAL display fields — get_card_field RAISES on an absent card/field
    (e.g. an older card version missing a newer field), and this must never abort the verdict-INERT spine.
    Returns None on any absence/error."""
    try:
        return get_card_field(cards, card_id, field)
    except Exception:  # noqa: BLE001 — optional display field; absence degrades to None, never aborts
        return None


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Resolve the effector-context verdict from the fired immune-context rule. Exactly one of the
    three class rules fires per run (the class is mutually exclusive); data_unavailable fires none →
    honest insufficient."""
    for r in fired:
        rid = r.get("rule_id")
        if rid in _RULE_TO_VERDICT:
            return (_RULE_TO_VERDICT[rid], rid)
    return ("insufficient", None)


# ── canonical HEADLINE block (verdict + confidence + top tension) ────────────────────────────────
# immune-context's declaration for the shared headline_core builder: the SINGLE TCE effector axis
# (IMMUNE), the effector-context vocabulary → human phrase, and the immune-cold effector-absence
# efficacy risk as the skill-specific tension source. Verdict-INERT — a one-way projection over the
# already-computed headline (this skill is GATELESS; the verdict spine stays byte-stable).
#
# POLARITY (colours the hero badge). This is a TCE-EFFICACY axis: a strong signal = immune-hot = there is
# a CD8 effector population for a T-cell engager to redirect. The badge polarity encodes the read FOR A
# TCE PROGRAM:
#   * immune_hot   → CD8 effector context present → TCE-favourable → "positive" (blue);
#   * immune_cold  → MEASURED effector absence → a TCE-efficacy RISK (NOT a target veto; CIBERSORT is a
#                    relative, non-spatial screen) → "negative" (red);
#   * immune_intermediate + coverage gaps (insufficient / no cohort) → "neutral" (grey).
_IMMUNE_VERDICT_PHRASE = {
    "immune_hot": "Immune-hot — CD8 effector context present (TCE-favourable)",
    "immune_intermediate": "Immune-intermediate — partial effector context",
    "immune_cold": "Immune-cold — effector absence (TCE-efficacy risk)",
    "insufficient": "Insufficient — no CIBERSORT cohort for this indication",
}


def _immune_verdict_polarity(v) -> str:
    """The skill's OWN reading of the effector-context call (colours the hero badge; never a gate — this
    skill is gateless). immune-hot is TCE-favourable (positive); immune-cold is a MEASURED effector
    absence and thus a TCE-efficacy risk (negative, NOT a target veto); the intermediate mid-band and
    coverage gaps stay neutral."""
    if v == "immune_hot":
        return "positive"
    if v == "immune_cold":
        return "negative"
    return "neutral"


def _til_discordance_text(headline: dict) -> str | None:
    """Human-facing text for a CIBERSORT-vs-absolute-TIL DISAGREEMENT. Returns None unless the orthogonal
    absolute H&E-DL TIL corroborator (Saltz) is MEASURED and points the OPPOSITE way to the relative
    CIBERSORT hot/cold call (til_cibersort_agreement is False). The two measure different things — CIBERSORT
    gives the CD8 SHARE of the leukocyte compartment (relative), Saltz gives the ABSOLUTE lymphocyte
    fraction from morphology — so a relatively-CD8-rich but absolutely-T-cell-sparse indication (e.g. PRAD)
    reads immune_hot while the absolute effector density is low: the 'CD8 effectors present to redirect'
    read over-claims. Symmetric for a cold call the absolute TIL contradicts."""
    if headline.get("til_cibersort_agreement") is not False:
        return None
    icls = headline.get("immune_context_class")
    tcls = headline.get("til_fraction_class")
    tpct = headline.get("median_til_percentage")
    tail = f"absolute H&E-DL TIL={tcls}" + (f" (median {tpct}%)" if tpct is not None else "")
    if icls in ("immune_hot", "immune_inflamed", "t_cell_inflamed"):
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


def _immune_tension_extra(headline: dict):
    """The sharpest immune-context caveat. Priority order: (1) a CIBERSORT-vs-absolute-TIL DISAGREEMENT
    (the relative hot/cold call is contradicted by the orthogonal absolute H&E-DL TIL corroborator —
    surfaced whenever til_cibersort_agreement is False, either direction); else (2) an immune-COLD
    indication is a MEASURED CD8 effector-absence — a TCE-EFFICACY risk (no effector population to
    redirect), NOT a target-level veto (CIBERSORT is a RELATIVE, non-spatial bulk-deconvolution screen);
    else (3) a POSITIVE bulk read with NO orthogonal absolute-TIL corroboration is SPATIALLY-UNCONFIRMED —
    the bulk-fraction-over-calls-spatial-infiltration risk (immune_confirmation_caveat sharp tier). The
    orthogonally_corroborated MILDER tier does NOT raise a tension (an independent platform agrees — the
    false-demote guard: a genuinely-inflamed, ICI-validated indication like melanoma stays clean)."""
    discord = _til_discordance_text(headline)
    if discord:
        return {"text": discord, "source": "til_cibersort_agreement", "severity": 3}
    if headline.get("immune_context_verdict") == "immune_cold":
        return {
            "text": (
                "immune-cold: a MEASURED CD8 effector-absence is a TCE-EFFICACY risk (no effector "
                "population to redirect) — NOT a target veto; CIBERSORT is relative + non-spatial"
            ),
            "source": "immune_context_class",
            "severity": 3,
        }
    cav = headline.get("immune_confirmation_caveat")
    if isinstance(cav, dict) and cav.get("reason") == "bulk_fraction_spatially_unconfirmed":
        return {"text": cav.get("detail"), "source": "immune_confirmation_caveat", "severity": 2}
    return None


_IMMUNE_HEADLINE_SPEC = HeadlineSpec(
    gate="immune_context",
    axis_labels={"IMMUNE": "TCE effector context"},
    axis_keys=("IMMUNE",),
    critical_axes=("IMMUNE",),
    verdict_label=lambda v: _IMMUNE_VERDICT_PHRASE.get(v, str(v).replace("_", " ").strip().capitalize()),
    tension_extra=_immune_tension_extra,
)


def _build_headline_block(headline: dict) -> dict:
    """Build the canonical Headline block from the already-computed immune-context headline. Reads the
    effector-context verdict + the verdict-inert claim_vector / key_signals; never moves the spine (this
    skill is gateless). No CERTAINTY_MODEL sidecar is emitted, so confidence is derived from the claim
    vector's corroboration."""
    v = headline.get("immune_context_verdict")
    pol = _immune_verdict_polarity(v)
    # DISCORDANCE DEMOTION (verdict-INERT): when the orthogonal absolute H&E-DL TIL corroborator is
    # MEASURED and CONTRADICTS the relative CIBERSORT hot/cold call (til_cibersort_agreement is False), the
    # confident badge over-reads — the relative CD8 SHARE and the absolute lymphocyte DENSITY point opposite
    # ways. Neutralise the badge (positive/negative → neutral); the immune_context_verdict TOKEN is
    # unchanged (it is an honest RELATIVE call) and the discordance is spelled out in top_tension.
    if headline.get("til_cibersort_agreement") is False and pol in ("positive", "negative"):
        pol = "neutral"
    return build_headline(
        headline,
        headline.get("claim_vector"),
        headline.get("key_signals"),
        spec=_IMMUNE_HEADLINE_SPEC,
        verdict_token=v,
        driving_rule_id=headline.get("driving_rule_id"),
        verdict_polarity=pol,
    )


# ── VERDICT-INERT enrichment: the bulk-CIBERSORT-CD8-fraction annotation-INFLATION surface ────────────
# The immune-context analog of surface-modality-fit's surface_confirmation_caveat and mechanism's
# mechanism_confirmation_caveat. A bulk CIBERSORT LM22 CD8 FRACTION over-calls actual SPATIAL T-cell
# infiltration: it reports the SHARE (relative, reference-model-dependent, non-spatial, function-blind),
# not the LOCALIZATION (inflamed tumour-nest CD8 vs immune-EXCLUDED stroma/margin CD8 vs DESERT) or the
# FUNCTION (functional vs exhausted). These fields NAME that confirmation deficit; they gate on the
# already-emitted headline fields (immune_context_verdict / immune_context_class / til_cibersort_agreement)
# and are NEVER read by the verdict path (the skill is gateless; the verdict is a direct read of
# immune_context_class) → the immune_context_verdict spine + goldens/replay stay byte-stable. SET literals
# (not 2-string tuples) throughout — a 2-string tuple in a membership check is misread by the reference-
# drift guard as a (rule_id, verdict) precedence tuple.
_POSITIVE_IMMUNE = {"immune_hot", "immune_intermediate"}  # a positive bulk read that would support a TCE arm
_HOT_CLASSES = {"immune_hot", "immune_inflamed", "t_cell_inflamed"}  # the strongest presence call


def _immune_confirmation_caveat(headline: dict) -> "dict | None":
    """The bulk-CD8-fraction annotation-INFLATION surface. Fires on a POSITIVE bulk read (immune_hot /
    immune_intermediate) — a call that would support a TCE effector arm — and names WHY the bulk fraction
    alone is not confirmed tumour-nest infiltration. Returns None on the negative (immune_cold) /
    insufficient paths → byte-stable there. Reason tiers, SHARP → MILD (mirrors surface's
    family_topology_annotation_unconfirmed vs clinically_precedented_cspa_unconfirmed):
      * bulk_fraction_til_discordant        — the orthogonal absolute H&E-DL TIL (Saltz) CONTRADICTS the
                                              relative CD8-share call (til_cibersort_agreement is False):
                                              CD8-rich SHARE but low ABSOLUTE lymphocyte density (the PRAD
                                              case) — the sharpest over-call.
      * bulk_fraction_spatially_unconfirmed — a positive read with NO orthogonal absolute-TIL check for this
                                              indication (til_cibersort_agreement is None) → looks-hot-but-
                                              SPATIALLY-UNCONFIRMED, the immune-EXCLUDED / desert risk.
      * orthogonally_corroborated           — the MILDER false-demote-guard tier: the absolute H&E-DL TIL
                                              CORROBORATES the CIBERSORT call (til_cibersort_agreement is
                                              True) → NOT an over-call (an independent morphology platform
                                              agrees; spares a genuinely-inflamed, ICI-validated indication
                                              like melanoma / MSI-H — the SKCM/DLL3 analog)."""
    v = headline.get("immune_context_verdict")
    if v not in _POSITIVE_IMMUNE:
        return None
    agree = headline.get("til_cibersort_agreement")
    icls = headline.get("immune_context_class")
    cd8 = headline.get("median_cd8_fraction")
    tcls = headline.get("til_fraction_class")
    tpct = headline.get("median_til_percentage")
    til_measured = tcls not in (None, "data_unavailable")
    til_tail = f"absolute H&E-DL TIL={tcls}" + (f" (median {tpct}%)" if tpct is not None else "")
    base = (
        f"immune_context_class={icls} (median CD8 share={cd8}) is a bulk CIBERSORT LM22 deconvolution "
        f"FRACTION — relative, reference-model-dependent, non-spatial and function-blind"
    )
    # The tier keys on whether the orthogonal absolute-TIL (Saltz) is MEASURED and whether it contradicts —
    # NOT on the raw agreement flag alone (a hot call + til_intermediate reads agreement=None yet Saltz IS
    # measured and does NOT contradict, so it must SPARE, not sharp-flag — the SKCM/MSI-H false-demote guard).
    if til_measured and agree is False:
        reason = "bulk_fraction_til_discordant"
        detail = (
            f"{base}; the orthogonal {til_tail} CONTRADICTS it — CD8-rich SHARE but low ABSOLUTE "
            f"lymphocyte density. The TCE-favourable effector read OVER-CALLS tumour infiltration."
        )
    elif til_measured:
        reason = "orthogonally_corroborated"
        strength = "CORROBORATES" if agree is True else "does NOT contradict"
        detail = (
            f"{base}, and the orthogonal {til_tail} {strength} it — an independent morphology platform "
            f"agrees the tumour is infiltrated, so this is NOT an over-call of DENSITY (the false-demote "
            f"guard: a genuinely-inflamed, ICI-validated indication is spared). BUT absolute TIL is a "
            f"density/morphology read, NOT spatial localization: it cannot confirm tumour-NEST (vs "
            f"stroma-EXCLUDED / margin-restricted) CD8, nor CD8 function — an IMMUNE-EXCLUDED tumour can "
            f"read high on both bulk platforms (see spatial_localization_caveat)."
        )
    else:  # Saltz unmeasured for this indication — no orthogonal absolute-TIL check at all
        reason = "bulk_fraction_spatially_unconfirmed"
        detail = (
            f"{base}, with NO orthogonal absolute-TIL corroboration for this indication (Saltz "
            f"unmeasured / non-comparable). Looks-hot-but-SPATIALLY-UNCONFIRMED — the bulk fraction "
            f"cannot tell an INFLAMED tumour (nest CD8, TCE-favourable) from an IMMUNE-EXCLUDED one "
            f"(stroma/margin CD8) or a DESERT."
        )
    if icls in _HOT_CLASSES:
        detail += (
            " CD8 PRESENCE != FUNCTION: a bulk fraction cannot exclude an exhausted/dysfunctional "
            "infiltrate that reads hot but is not cytotoxically effective."
        )
    return {"reason": reason, "detail": detail}


# T0-4: map the spatial coloc card's malignant-cell-anchored class to the TCE-decisive spatial-immune
# phenotype. inflamed = immune adjacent to target+ malignant cells (TCE-favourable); excluded = target+
# tumour DEPLETED of immune neighbours (TCE liability). The clean three-way inflamed/excluded/DESERT call
# needs an absolute-adjacency desert threshold in the analysis-methods classifier (fast-follow); until then
# a target that is not immune-anchored (no_spatial_preference / stromal|endothelial|epithelium niche) is
# reported as spatial_immune_indeterminate, NOT mislabelled desert. Target-DEPENDENT (anchored on target+
# cells) but VERDICT-INERT.
_SPATIAL_COLOC_TO_PHENOTYPE = {
    "immune_niche_colocalized": "inflamed",
    "immune_excluded": "excluded",
}


def _spatial_immune_phenotype(headline: dict) -> "str | None":
    """inflamed / excluded / spatial_immune_indeterminate / data_unavailable — the spatial resolution of
    the CD8 hot/cold call. None only when the coloc card is entirely absent (unmeasured indication)."""
    cls = headline.get("spatial_coloc_class")
    if cls in (None, "data_unavailable"):
        return None
    return _SPATIAL_COLOC_TO_PHENOTYPE.get(cls, "spatial_immune_indeterminate")


def _spatial_localization_caveat(headline: dict) -> "str | None":
    """Names the inflamed-vs-excluded-vs-desert distinction a BULK CD8 fraction cannot make — surfaced on
    every POSITIVE bulk read (the decisive TCE distinction). Where a spatial coloc product EXISTS for the
    indication, spatial_immune_phenotype (T0-4) now RESOLVES the inflamed-vs-excluded call and the caveat
    says so; otherwise it remains a documented gap. Target-independent framing; verdict-inert; None on the
    immune_cold / insufficient paths."""
    if headline.get("immune_context_verdict") not in _POSITIVE_IMMUNE:
        return None
    pheno = _spatial_immune_phenotype(headline)
    if pheno in ("inflamed", "excluded"):
        return (
            f"a bulk CD8 fraction cannot localise the infiltrate, but spatial co-localization "
            f"(spatial_immune_phenotype) RESOLVES it here: the target-positive malignant cells are "
            f"{'in an immune-rich niche — INFLAMED, TCE-favourable' if pheno == 'inflamed' else 'DEPLETED of immune neighbours — IMMUNE-EXCLUDED, a TCE liability (no effector T cells adjacent to redirect)'}."
        )
    return (
        "a bulk CD8 fraction reports the SHARE of the leukocyte compartment, not the spatial "
        "LOCALIZATION: it cannot distinguish an INFLAMED tumour (CD8 in the malignant nest — "
        "TCE-favourable) from an IMMUNE-EXCLUDED tumour (CD8 trapped in peritumoral stroma / at the "
        "invasive margin, not touching malignant cells — TCE-UNfavourable) from a DESERT. No spatial "
        "co-localization product covers this indication; resolving it needs spatial / multiplex-IHC / "
        "pathology, not bulk deconvolution."
    )


def _immune_provenance(headline: dict) -> dict:
    """QUORUM/PROVENANCE summary: which platforms speak to the effector-context call, and whether the bulk
    CIBERSORT fraction is corroborated by an orthogonal absolute-TIL read. A bulk fraction ALONE must NOT be
    read as confirmed tumour-nest infiltration — confirmed_tumor_nest_infiltration is always False (bulk
    deconvolution is never spatial). Verdict-inert."""
    agree = headline.get("til_cibersort_agreement")
    tcls = headline.get("til_fraction_class")
    til_measured = tcls not in (None, "data_unavailable")
    if not til_measured:
        corr = "unmeasured"
    else:
        corr = {True: "corroborates", False: "contradicts", None: "not_comparable"}.get(agree, "not_comparable")
    return {
        "bulk_cibersort": {
            "immune_context_class": headline.get("immune_context_class"),
            "median_cd8_fraction": headline.get("median_cd8_fraction"),
            "n_samples": headline.get("n_samples"),
            "tumor_studies": headline.get("tumor_studies"),
            "platform": "CIBERSORT LM22 (relative, reference-model-dependent, non-spatial, function-blind)",
        },
        "absolute_til_corroboration": {
            "til_fraction_class": tcls,
            "median_til_percentage": headline.get("median_til_percentage"),
            "til_n_samples": headline.get("til_n_samples"),
            "orthogonal_agreement": corr,  # corroborates | contradicts | not_comparable | unmeasured
            # a spatial-AGGREGATION statistic (clustered vs dispersed TIL) — a FIRST proxy for organization
            # the CD8 FRACTION lacks; still NOT tumour-nest-vs-stroma localization (needs multiplex-IHC).
            "median_number_of_clusters": headline.get("median_number_of_clusters"),
        },
        # per-patient / antigen-CONDITIONED heterogeneity (v2 facet; target-DEPENDENT display, verdict-inert):
        # a cohort-MEDIAN CD8 fraction hides whether the ANTIGEN-HIGH (targetable) patients are ALSO T-cell-
        # high (ideal) or T-cell-POORER (effector escape — a TCE-efficacy risk concentrated where it matters).
        # data_unavailable when the CIBERSORT-barcode <-> expression-UUID join is too thin.
        "antigen_conditioned": {
            "antigen_conditioned_call": headline.get("antigen_conditioned_call"),
            "cd8_high_minus_low": headline.get("cd8_high_minus_low"),  # negative => antigen-high patients T-cell-POORER
            "antigen_high_immune_context_class": headline.get("antigen_high_immune_context_class"),
        },
        "confirmed_tumor_nest_infiltration": False,  # NEVER confirmed by bulk deconvolution alone
        "note": (
            "A bulk CIBERSORT CD8 fraction is RELATIVE, non-spatial and function-blind; a positive read "
            "is CONFIRMED tumour-nest infiltration only with spatial / multiplex-IHC corroboration. The "
            "absolute H&E-DL TIL (Saltz) is an orthogonal ABSOLUTE-density check (still not spatial "
            "localization or CD8 function); median_number_of_clusters is a coarse spatial-aggregation "
            "hint, not a nest-vs-stroma call."
        ),
    }


def _headline(cards, fired, verdict_pair):
    v, drv = verdict_pair or ("insufficient", None)
    hl = {
        "immune_context_verdict": v,
        "driving_rule_id": drv,
        "immune_context_class": get_card_field(cards, "immune-context", "immune_context_class"),
        "median_cd8_fraction": get_card_field(cards, "immune-context", "median_cd8_fraction"),
        "median_total_t_cell_fraction": get_card_field(cards, "immune-context", "median_total_t_cell_fraction"),
        "n_samples": get_card_field(cards, "immune-context", "n_samples"),
        "tumor_studies": get_card_field(cards, "immune-context", "tumor_studies"),
        # Saltz H&E-DL absolute TIL corroborator (2026-08-28) — VERDICT-INERT. An orthogonal (morphology,
        # not RNA-deconvolution) TIL read on the SAME TCGA participants; til_cibersort_agreement HARDENS
        # confidence in the CD8 hot/cold call (never creates/overrides it).
        "til_fraction_class": get_card_field(cards, "tcga-til-fraction-saltz", "til_fraction_class"),
        "median_til_percentage": get_card_field(cards, "tcga-til-fraction-saltz", "median_til_percentage"),
        "til_n_samples": get_card_field(cards, "tcga-til-fraction-saltz", "n_samples"),
        # v1.6.1 follow-ups (VERDICT-INERT display). (a) the Saltz median TIL-CLUSTER count — a
        # spatial-AGGREGATION statistic (clustered vs dispersed TIL), a first, cheap proxy for spatial
        # organization the bulk CD8 FRACTION lacks (still NOT nest-vs-stroma; needs true multiplex-IHC).
        "median_number_of_clusters": _cf(cards, "tcga-til-fraction-saltz", "median_number_of_clusters"),
        # (b) the antigen-CONDITIONED join the immune-context card already computes (the documented v2 facet):
        # are the ANTIGEN-HIGH patients ALSO T-cell-high, or T-cell-POORER (effector escape)? These are the
        # ONLY target-DEPENDENT fields the skill surfaces (the verdict stays target-independent), and degrade
        # to data_unavailable when the CIBERSORT-barcode <-> expression-UUID join is too thin (guard).
        "antigen_conditioned_call": _cf(cards, "immune-context", "antigen_conditioned_call"),
        "cd8_high_minus_low": _cf(cards, "immune-context", "cd8_high_minus_low"),
        "antigen_high_immune_context_class": _cf(cards, "immune-context", "antigen_high_immune_context_class"),
        # T0-4: spatial co-localization reads (GeoMx/Xenium/CosMx) — the target's malignant-cell
        # neighbourhood pattern. VERDICT-INERT: these resolve the inflamed-vs-excluded call the bulk CD8
        # fraction cannot (see spatial_immune_phenotype below), but fire no rule mapped in _RULE_TO_VERDICT.
        # _cf so an absent card (indication with no coloc product) degrades to None, never aborts.
        "spatial_coloc_class": _cf(cards, "spatial-tumor-normal-colocalization", "spatial_coloc_class"),
        "spatial_immune_adjacency_fraction": _cf(
            cards, "spatial-tumor-normal-colocalization", "immune_adjacency_fraction"
        ),
        "spatial_top_enriched_compartment": _cf(
            cards, "spatial-tumor-normal-colocalization", "top_enriched_compartment"
        ),
    }
    # coarse cross-modality agreement: do the H&E-DL TIL bin and the CIBERSORT CD8 hot/cold call point the
    # same way? None when either is unmeasured. Directional only (different scales).
    _icls = hl["immune_context_class"]
    _tcls = hl["til_fraction_class"]
    _hot = {"immune_hot", "immune_inflamed", "t_cell_inflamed"}
    _cold = {"immune_cold", "immune_desert", "cold"}
    if _tcls in ("til_high", "til_intermediate", "til_low") and _icls:
        _til_hi = _tcls == "til_high"
        _til_lo = _tcls == "til_low"
        if _icls in _hot:
            hl["til_cibersort_agreement"] = True if _til_hi else (False if _til_lo else None)
        elif _icls in _cold:
            hl["til_cibersort_agreement"] = True if _til_lo else (False if _til_hi else None)
        else:
            hl["til_cibersort_agreement"] = None
    else:
        hl["til_cibersort_agreement"] = None
    # verdict-INERT claim-vector projection (TCE effector axis) + citable CD8-fraction atom for the
    # cross-evidence reasoner. immune-context is gateless (absent from _SHORT_TO_GATE); verdict-inert.
    hl["claim_vector"] = immune_context_claim_vector(hl, cards)
    hl["key_signals"] = immune_context_key_signals(hl, cards)
    # The per-question (data·signal·confidence) LEADING table — verdict-INERT projection over the IMMUNE
    # claim_vector just built; best-effort (never abort the effector-context spine already built in `hl`).
    try:
        hl["question_table"] = immune_context_question_table(hl, cards)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["question_table"] = f"{type(exc).__name__}: {exc}"
        hl["question_table"] = None
    # VERDICT-INERT bulk-CD8-fraction annotation-INFLATION surface (the surface_confirmation_caveat /
    # mechanism_confirmation_caveat analog). Computed BEFORE the headline_block so the spatial-unconfirmed
    # tier can feed the headline top_tension. Best-effort — a projection fault must never discard the spine.
    try:
        hl["spatial_immune_phenotype"] = _spatial_immune_phenotype(hl)  # T0-4 (computed before the caveat reads it)
        hl["immune_confirmation_caveat"] = _immune_confirmation_caveat(hl)
        hl["spatial_localization_caveat"] = _spatial_localization_caveat(hl)
        hl["immune_provenance"] = _immune_provenance(hl)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["immune_confirmation"] = f"{type(exc).__name__}: {exc}"
        hl.setdefault("immune_confirmation_caveat", None)
        hl.setdefault("spatial_immune_phenotype", None)
        hl.setdefault("spatial_localization_caveat", None)
        hl.setdefault("immune_provenance", None)
    # Canonical HEADLINE block (verdict + confidence + top tension) — the concise, consumer-facing
    # headline message as deterministic text + a renderer-agnostic hero payload. A verdict-INERT
    # projection over the claim_vector / key_signals just built. Best-effort: a formatting/read fault must
    # NEVER discard the effector-context spine already built in `hl` (same degrade discipline the
    # dispatcher applies to synthesis / figures). On the happy path this adds no _enrichment_errors key.
    try:
        hl["headline_block"] = _build_headline_block(hl)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["headline_block"] = f"{type(exc).__name__}: {exc}"
        hl["headline_block"] = None
    # UNIFIED skill_report (docs/UNIFIED_OUTPUT_CONTRACT.md) — immune-context is a DESCRIPTIVE skill (CD8
    # effector context for the TCE arm; role=descriptive → polarity=not_scored, excluded from gate math).
    # Best-effort + verdict-INERT.
    try:
        _used = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and not c.get("_missing")]
        _missing = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and c.get("_missing")]
        hl["skill_report"] = build_skill_report(
            role=ROLE_DESCRIPTIVE,
            verdict=hl.get("immune_context_verdict"),
            driving_rule_id=hl.get("driving_rule_id"),
            headline_block=hl.get("headline_block"),
            claim_vector=hl.get("claim_vector"),
            question_table=hl.get("question_table"),
            fired_rule_ids=[f.get("rule_id") for f in (fired or [])],
            cards_used=_used or CARDS,
            cards_missing=_missing,
        )
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["skill_report"] = f"{type(exc).__name__}: {exc}"
        hl["skill_report"] = None
    return hl


_SYNTHESIS_FACET_KEYS = (
    "immune_context_verdict",
    "driving_rule_id",
    "immune_context_class",
    "median_cd8_fraction",
    "median_total_t_cell_fraction",
    "n_samples",
    "til_fraction_class",
    "median_til_percentage",
    "til_cibersort_agreement",
    # v1.6.1 (VERDICT-INERT display): Saltz spatial-aggregation hint + the antigen-CONDITIONED heterogeneity
    # facet (target-dependent; the cohort-median blind spot — are the antigen-HIGH patients T-cell-poorer?).
    "median_number_of_clusters",
    "antigen_conditioned_call",
    "cd8_high_minus_low",
    "antigen_high_immune_context_class",
    # VERDICT-INERT bulk-CD8-fraction annotation-INFLATION surface (bulk fraction != spatial localization
    # != CD8 function) — the surface_confirmation_caveat / mechanism_confirmation_caveat analog.
    "immune_confirmation_caveat",
    "spatial_localization_caveat",
    # T0-4 (VERDICT-INERT): spatial co-localization resolution of the inflamed-vs-excluded TCE call the
    # bulk CD8 fraction cannot make. spatial_immune_phenotype ∈ inflamed/excluded/spatial_immune_indeterminate.
    "spatial_immune_phenotype",
    "spatial_coloc_class",
    "spatial_immune_adjacency_fraction",
    "spatial_top_enriched_compartment",
    "immune_provenance",
    "claim_vector",
    "key_signals",
    # the per-question (data·signal·confidence) rows — rendered as the leading table by target-profile too
    "question_table",
    # the canonical headline (verdict + confidence + top tension) — text + hero payload for every consumer
    "headline_block",
    # the UNIFIED cross-skill output object (docs/UNIFIED_OUTPUT_CONTRACT.md) — Wave-3 descriptive adoption
    "skill_report",
)


def _synthesis_facet(cards, fired, verdict_pair):
    """Compact, VERDICT-INERT immune-context facet for the composed synthesis. Reuses _headline (single
    source) + returns the IMMUNE claim_vector (TCE effector axis) with its citable CD8-fraction atom.
    immune-context is gateless — this never moves the nomination spine."""
    h = _headline(cards, fired, verdict_pair)
    facet = {k: h.get(k) for k in _SYNTHESIS_FACET_KEYS}
    facet["_facet_note"] = (
        "Deterministic immune-context facet; claim_vector is the TCE EFFECTOR axis "
        "(indication-level, target-independent). Gateless — no verdict on the spine."
    )
    return facet


# ── M1 claim-record: wires the CD8 effector context into the composed modality_fit bite_tce channel ──
# immune-context is the TCE EFFECTOR arm — the CD8 companion to surface-modality-fit's antigen arm. It
# is the ONLY axis that speaks to whether there are effector T-cells for a T-cell engager to redirect,
# so its record contributes a bite_tce refinement ONLY (silent on every other channel). Previously
# immune-context exposed no _claim_record, so this signal reached neither modality_fit nor the modality
# conjunction — the TCE effector arm was unwired (2026-09 modality-coverage audit). VERDICT-INERT.
_IMMUNE_TCE_FIT = {  # immune verdict → bite_tce favorability (modality_fit vocab)
    "immune_hot": "favorable",  # CD8 effector context present → TCE-favourable
    "immune_intermediate": "conditional",  # partial effector context
    "immune_cold": "conditional",  # effector absence = TCE-EFFICACY RISK, but NOT a veto
    # (CIBERSORT is a relative, non-spatial screen) → caveat, not kill
}  # insufficient / no cohort → silent (na)


def _immune_modality_scope(verdict: "str | None") -> "dict | None":
    fit = _IMMUNE_TCE_FIT.get(verdict)
    return {"_refinements": {"bite_tce": fit}} if fit else None


def _claim_record(cards, fired=None, verdict_pair=None) -> dict:
    """M1 shadow builder — the effector (TCE) axis's contribution; mirrors the other axes' hook. Its
    modality_scope is the wiring that lets the CD8 effector read reach the composed bite_tce channel."""
    v = verdict_pair[0] if verdict_pair else (_verdict(fired)[0] if fired is not None else None)
    _avail = {
        "immune_hot": "measured_positive",
        "immune_intermediate": "measured_positive",
        "immune_cold": "measured_negative",
    }.get(v, "insufficient")
    return assemble_claim_record(
        axis="immune_context",
        state=(v or "insufficient"),
        direction={"immune_hot": "supports", "immune_cold": "opposes"}.get(v, "neutral"),
        availability=_avail,
        magnitude={"level": {"immune_hot": "strong", "immune_cold": "moderate"}.get(v, "none")},
        modality_scope=_immune_modality_scope(v),
        certainty={"coverage": "measured" if _avail != "insufficient" else "unmeasured"},
        fired=fired,
        cards=cards,
    )


if __name__ == "__main__":
    sys.exit(
        run_wired_skill(
            skill_name=SKILL_NAME,
            skill_version=SKILL_VERSION,
            cards=CARDS,
            axis="surface_intrinsic",  # effector context reads on the biologics (surface/TCE) side
            question=QUESTION,
            verdict_fn=_verdict,
            headline_fn=_headline,
            # NET-NEW capsule-driven narrator (generic engine + this lens's LensConfig).
            synthesize_fn=make_synthesize_fn(_LENS),
            # Skill-level graphics (opt-in --figures): the canonical headline hero. Additive / display-only.
            skill_figures_fn=emit_headline_hero,
            # Signals-first: tuned sub-group reader for the immune-context vocabulary. Verdict-INERT.
            subgroup_classify=make_value_classifier(_IMMUNE_VALUE_TIERS),
            # Opt-in --literature: a VERDICT-INERT literature corroboration/contradiction lane (mirrors surface
            # #1021 / mechanism skills#1030). Attaches decision['literature_synthesis'] (Europe PMC → PubTator3
            # grounding + a verify_citations PMID pass) and feeds the --synthesize narrator. The IMMUNE query
            # terms (immune exclusion / inflamed-excluded-desert phenotype / spatial multiplex-IHC / T-cell
            # exhaustion / checkpoint response) live in literature_retrieval.py::_LENS_QUERY_TERMS. Spine-
            # untouched: the lane attaches AFTER the deterministic decision is composed (gateless verdict).
            literature_fn=make_literature_fn(_LENS, retrieve_fn=default_retrieve, verify_fn=verify_citations),
        )
    )
