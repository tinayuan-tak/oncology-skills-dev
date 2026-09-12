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

The VERDICT is per-indication / target-INDEPENDENT (tier: indication) and a direct read of the
immune_context_class categorical (a descriptive effector-context call — no cross-card resolver). The
antigen-CONDITIONED join (are the ANTIGEN-HIGH patients also T-cell-high, or T-cell-POORER = effector
escape?) SHIPPED in v1.6.1 and is surfaced as verdict-INERT display — it and the spatial co-localization
reads (v1.7.0) are the only target-DEPENDENT fields the skill carries.

READ THE CLASS TOKEN AS A PAN-CANCER RANK, NOT AN ABSOLUTE DENSITY. `immune_hot`/`immune_cold` are the
Q3/Q1 cuts of the 33-study CIBERSORT distribution over the LEUKOCYTE compartment, so ~9 studies are hot
and ~9 cold BY CONSTRUCTION — clinically-cold PRAD reads hot, ICI-approved LUAD/BLCA read intermediate.
The `reference_frame` claim scalar (v1.8.0) states that frame on the spine, and the corroboration ruler
demotes confidence when an orthogonal ABSOLUTE (H&E-DL TIL) or SPATIAL platform contradicts it.
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
from _skills_common.immune_context_claims import (
    immune_context_claim_vector,
    immune_context_key_signals,
    orthogonal_discordance_text,
)
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
    # The two ABSTENTIONS, now mapped to the off-axis `unmeasured` token the shared ladder gained. Both
    # previously fell through default_classify to `absent`, reading "we could not measure" as "no
    # effectors" — the same inversion the lymphoid verdict exists to prevent, reappearing one surface
    # further down. `unmeasured` keeps them off the presence ordinal entirely: no vote, no rank, no
    # conflict. This mapping matches _IMMUNE_SIGNAL in immune_context_claims.py, so the sub-group tier and
    # the claim signal now agree instead of contradicting each other.
    "lymphoid_denominator_unreliable": "unmeasured",
    "data_unavailable": "unmeasured",
}

SKILL_NAME = "immune-context"
SKILL_VERSION = "1.9.2"  # 1.9.2 (2026-09-12): the card's DECLARED figure `immune_context_leukocyte_composition` had NO emitter registered in _skills_common/_figure_emitters, so every live run attached nothing — a declared-not-emitted gap kept as a WARNING by target-contracts' KNOWN_FIGURE_DEBT waiver (44 cards) rather than the FIGURE_DECLARED_NOT_EMITTED error it otherwise is. Now emitted, self-contained on the summary. TWO panels because either alone misleads: (A) composition — the LM22 medians as fractions OF THE LEUKOCYTE POOL, labelled as the RELATIVE deconvolution they are (shares of the infiltrate, not densities), with a suppressor median at the LM22 noise floor drawn HOLLOW + annotated, read off the card's own NULLED ratio rather than a third copy of the 0.005 cut; (B) rank — the CD8 median against the pan-cancer Q1/Q3 cuts plus cd8_hot_sample_fraction, because immune_hot/cold are POSITIONS IN THE 33-STUDY DISTRIBUTION and a bare composition bar invites reading the token as an absolute effector density (ICI-approved BLCA sits at immune_intermediate), while a cohort median hides bimodality (MSI-H CRC). The figure ABSTAINS wherever the class abstains: data_unavailable has no medians, and lymphoid_denominator_unreliable is the important case — the medians ARE arithmetically defined and that is the trap, since the leukocyte denominator IS the malignant clone, so a bar chart would assert "CD8 is 11% of leukocytes" as an effector pool with no room for the caveat the prose carries. Display-only; verdict spine untouched. Clearing the TC waiver is a follow-on PR that must land AFTER this one.   # 1.9.1 (2026-09-12): the LYMPHOID reference_frame line refuted its own first clause — "the cohort exists (DLBC, n=0)". n_samples is 0 for these cohorts BY DESIGN (the denominator guard fires on the resolved study codes BEFORE the per-sample read, so no rows are loaded and the summariser gets an empty list): a NOT-READ sentinel, not a cohort size, and never to be rendered as one. The line now cites the STUDY CODES — what the "a cohort EXISTS" claim actually rests on — and quotes no count. Caught by a live DLBCL run, not by the suite: the unit fixture asserted n_samples=48 (DLBC's true size), a shape the reader never emits; it now carries the live 0 and a new test forbids any `n=` in that frame. Display-only; verdict spine and every non-lymphoid frame byte-stable.   # 1.9.0 (2026-09-12): TWO invisible-surface gaps. (A) The card's SIX heterogeneity + suppression summary_fields (cd8_hot_sample_fraction, cd8_treg_ratio, cd8_m2_ratio, median_treg/m2/m1_macrophage_fraction) were emitted by the reader since card v1.2.0 and read by NOTHING downstream — not the headline, not the citable atom, not the synthesis facet. The mirror guard is structurally blind to this (it runs card-DECLARES -> reader-EMITS, so a field nothing CONSUMES is invisible), which is why it survived a full review. Now on the headline, the IMMUNE atom, the facet and immune_provenance, plus TWO new frame scalars: `heterogeneity_frame` gauges the cohort MEDIAN against the PREVALENCE of hot samples at the same cut (the bimodal-cohort blind spot: MSI-H CRC is ~15% strongly infiltrated and the pooled median reads intermediate, hiding the population a TCE would be developed FOR), and `suppression_frame` reports CD8:Treg / CD8:M2 (inflamed-but-SUPPRESSED != a bare hot call), abstaining when a suppressor median sits at the LM22 noise floor. Both DESCRIPTIVE and NON-GATING by design: 0.113/0.084 are the 33-study Q3/Q1 of the CD8 SHARE and no equivalent pan-cancer distribution exists for a prevalence or a suppressor ratio, so a cut here would be unanchored — derive one from the same 11,373-sample product first. (B) The FOURTH class token `lymphoid_denominator_unreliable` was declared + emitted with NO rule and NO entry here, so it fired nothing and fell through to a bare `insufficient` INDISTINGUISHABLE from "no cohort" — collapsing "there IS a cohort and its reference frame does not apply" onto the generic abstention on TCE-VALIDATED indications (glofitamab/mosunetuzumab in DLBCL). Now a first-class verdict (TC rule immune-context-lymphoid-denominator-uninterpretable, bite_tce NEUTRAL): own phrase, NEUTRAL polarity (never red — an absent MEASUREMENT is not measured effector absence), `unmeasured` signal, its own reference_frame line instead of the bare sentinel, a severity-2 top_tension, and modality_scope SILENT (na). Verdict spine MOVES for lymphoid indications only, by design (AM #610 made those indications resolvable at all); byte-stable everywhere else.   # 1.8.0 (2026-09-12): CARD-DATA RULER pass — the confidence ladder was VACUOUS and the modality read was off the spine. (F2) `_immune_corr` returned the CONSTANT "moderate" for every measured indication and the IMMUNE atom never carried a `conflict`, so headline_block/skill_report confidence was a CONSTANT — `strong`/`weak` UNREACHABLE and derive_confidence's conflict cap + coverage floor dead code (a discordant PRAD read exactly as confidently as a corroborated SKCM). Now an ORTHOGONAL-PLATFORM ruler: high=absolute H&E-DL TIL (Saltz) or SPATIAL co-localization AGREES -> strong; moderate=CIBERSORT alone; low=an orthogonal platform CONTRADICTS -> weak + a first-class `conflict`. (F4) spatial_immune_phenotype=excluded on a POSITIVE bulk read is now a CONTRADICTION (effectors in the leukocyte compartment but DEPLETED from the target-positive nest) and caps bite_tce at `conditional` (DEMOTE-ONLY; never promotes). (F1) `modality_scope` now on the skill_report SPINE, not only the legacy claim_record_shadow. (S2) new `reference_frame` claim SCALAR names the pan-cancer Q1/Q3 frame so the class token cannot be read as an absolute T-cell density. Three duplicate discordance-prose builders collapsed onto ONE `orthogonal_discordance_text` (claim conflict == key_signals caveat == headline top_tension, cannot drift). Verdict spine BYTE-STABLE (gateless; verdict still a direct read of immune_context_class) — confidence + modality_scope MOVE by design.   # 1.7.0 (2026-09-10): T0-4 — wire spatial-tumor-normal-colocalization (GeoMx/Xenium/CosMx) into the IMMUNE spine. VERDICT-INERT: adds spatial_immune_phenotype (inflamed / excluded / spatial_immune_indeterminate) — the spatial resolution of the inflamed-vs-excluded TCE call the bulk CD8 FRACTION structurally cannot make (the exact gap _spatial_localization_caveat concedes); the spatial bite_tce rules are NOT in _RULE_TO_VERDICT so the gateless immune_context_verdict spine stays byte-stable. data_unavailable outside the ~6 coloc-covered indication families (degrades honestly). Clean three-way inflamed/excluded/DESERT needs an absolute-adjacency desert threshold in the analysis-methods classifier (fast-follow).   # 1.6.1 (2026-09-04): VERDICT-INERT display follow-ups — Saltz median_number_of_clusters spatial-aggregation hint (clustered-vs-dispersed TIL, a first spatial proxy the CD8 FRACTION lacks) into immune_provenance; SURFACE the immune-context card's antigen-CONDITIONED join (antigen_conditioned_call / cd8_high_minus_low / antigen_high_immune_context_class — the ONLY target-dependent display fields; addresses the cohort-median heterogeneity blind spot = are the antigen-HIGH patients T-cell-POORER = effector escape) via _cf() defensive getter; data_unavailable when the join is thin. Verdict spine byte-stable. NOTE: the ici-response-imvigor210 display card MISSES a legacy-symbol target (NECTIN4->PVRL4 in the genentech eSet) — a data-product resolver gap, verdict-inert (filed, cross-repo).   # 1.6.0 (2026-09-04): --literature lane (make_literature_fn(IMMUNE_CONTEXT)) + VERDICT-INERT surfacing of the bulk-CD8-fraction annotation-INFLATION (immune_confirmation_caveat: a positive bulk CIBERSORT read resting on a RELATIVE/non-spatial/function-blind fraction w/o spatial or orthogonal-absolute-TIL confirmation — tiers bulk_fraction_til_discordant / bulk_fraction_spatially_unconfirmed / orthogonally_corroborated[false-demote guard]; spatial_localization_caveat inflamed-vs-excluded-vs-desert; immune_provenance quorum) + IMMUNE_CONTEXT thesis + polarity_note (was NONE). Spine byte-stable (gateless; verdict = direct read of immune_context_class).   # 1.4.0 (2026-08-28): + tcga-til-fraction-saltz (absolute H&E-DL TIL corroborator, VERDICT-INERT).   # 1.3.0: capsule-driven narrator via generic engine.   # 1.2.0 (2026-08-27): tuned signals-first sub-group reader. Verdict-INERT.   # 1.1.0: + canonical HEADLINE block (verdict + confidence + top tension) &
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
#
# The FOURTH token (2026-09-12). `lymphoid_denominator_unreliable` was declared on the card and emitted by
# the reader while NO rule read it and this map did not carry it — so it arrived here, fired nothing, and
# fell through to a bare `insufficient` INDISTINGUISHABLE from "no CIBERSORT cohort". That collapsed the
# specific, useful answer ("there IS a cohort and its reference frame does not apply") onto the generic
# one, on TCE-VALIDATED indications (glofitamab / mosunetuzumab in DLBCL) where the distinction is the
# whole point. The rule now exists (target-contracts surface-intrinsic.rules.yaml, bite_tce: NEUTRAL) and
# the verdict is its own token, so every downstream consumer can tell the two abstentions apart.
_RULE_TO_VERDICT = {
    "immune-context-hot-tce-supportive": "immune_hot",
    "immune-context-intermediate-tce-neutral": "immune_intermediate",
    "immune-context-cold-tce-opposing": "immune_cold",
    "immune-context-lymphoid-denominator-uninterpretable": "lymphoid_denominator_unreliable",
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
#   * immune_intermediate + coverage gaps (insufficient / no cohort / uninterpretable denominator) →
#     "neutral" (grey). The lymphoid token is EMPHATICALLY not "negative": it is an absent MEASUREMENT,
#     and a red badge would read as measured effector absence in the malignancies where TCEs work.
_IMMUNE_VERDICT_PHRASE = {
    "immune_hot": "Immune-hot — CD8 effector context present (TCE-favourable)",
    "immune_intermediate": "Immune-intermediate — partial effector context",
    "immune_cold": "Immune-cold — effector absence (TCE-efficacy risk)",
    # NOT "insufficient": the cohort EXISTS, its leukocyte denominator is the malignant clone. Phrased so a
    # reader can tell this apart from the no-cohort abstention below at a glance.
    "lymphoid_denominator_unreliable": (
        "Not interpretable — the cohort's leukocyte denominator IS the malignancy (no effector read)"
    ),
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


# The orthogonal-platform DISCORDANCE prose lives in _skills_common/immune_context_claims.py
# (`orthogonal_discordance_text`) — the SAME string feeds the claim's `conflict` atom, the
# key_signals caveat and this headline top_tension, so the three surfaces cannot drift. It now also
# covers the SPATIAL contradiction (spatial_immune_phenotype=excluded on a positive bulk read), which
# the previous run.py-local, TIL-only builder could not express.
_til_discordance_text = orthogonal_discordance_text


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
    # The DENOMINATOR tension, ahead of the immune_cold one: on a lymphoid cohort the immune_cold branch
    # can never fire (the class is withheld), and a silent top_tension here would let the neutral badge read
    # as "nothing notable" when the notable thing is that the axis cannot speak at all.
    if headline.get("immune_context_verdict") == "lymphoid_denominator_unreliable":
        return {
            "text": (
                "the CIBERSORT cohort EXISTS but its LEUKOCYTE denominator is the malignant clone "
                "(leukaemia / lymphoma / lymphoid organ), so a CD8 SHARE of that compartment is "
                "arithmetically valid and biologically uninterpretable — the median is WITHHELD. This is an "
                "absent MEASUREMENT, not a measured effector absence: read NO TCE-efficacy risk from it "
                "(TCEs are the validated modality in these indications). An absolute or spatial effector "
                "read is the way in, not bulk leukocyte deconvolution."
            ),
            "source": "immune_context_class",
            "severity": 2,
        }
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


_HOT_CLASSES = {"immune_hot", "immune_inflamed", "t_cell_inflamed"}
_COLD_CLASSES = {"immune_cold", "immune_desert", "cold"}


def _til_cibersort_agreement(immune_class: "str | None", til_class: "str | None") -> "bool | None":
    """Coarse cross-PLATFORM agreement: do the absolute H&E-DL TIL bin and the relative CIBERSORT CD8
    hot/cold call point the same way? DIRECTIONAL only (different scales, different denominators). None
    when either side is unmeasured OR when the pair is not directionally comparable (an intermediate on
    either axis). Extracted from `_headline` so `_claim_record`'s independent frame cannot drift from it —
    both carriers of `modality_scope` must see the SAME orthogonal reads."""
    if til_class not in ("til_high", "til_intermediate", "til_low") or not immune_class:
        return None
    hi, lo = til_class == "til_high", til_class == "til_low"
    if immune_class in _HOT_CLASSES:
        return True if hi else (False if lo else None)
    if immune_class in _COLD_CLASSES:
        return True if lo else (False if hi else None)
    return None


def _orthogonal_reads(cards) -> dict:
    """The ORTHOGONAL-PLATFORM sub-frame of the headline (absolute H&E-DL TIL + spatial co-localization) —
    the minimum `orthogonal_discordance_text` needs. `_headline` already carries these keys on `hl`; this
    rebuilds just them for the legacy `_claim_record` shadow, which has cards but no headline."""
    icls = _cf(cards, "immune-context", "immune_context_class")
    tcls = _cf(cards, "tcga-til-fraction-saltz", "til_fraction_class")
    frame = {
        "immune_context_class": icls,
        "til_fraction_class": tcls,
        "median_til_percentage": _cf(cards, "tcga-til-fraction-saltz", "median_til_percentage"),
        "til_cibersort_agreement": _til_cibersort_agreement(icls, tcls),
        "spatial_coloc_class": _cf(cards, "spatial-tumor-normal-colocalization", "spatial_coloc_class"),
    }
    frame["spatial_immune_phenotype"] = _spatial_immune_phenotype(frame)
    return frame


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
        # the TARGET-INDEPENDENT half of the same heterogeneity question, and the one that needs no join:
        # what fraction of patients in this cohort actually clear the hot cut the MEDIAN was scored against?
        # (the antigen-conditioned block above degrades to data_unavailable on a thin barcode<->UUID join;
        # this one is always available where the class is.) Plus the SUPPRESSION load a bare hot call ignores.
        "cohort_heterogeneity": {
            "cd8_hot_sample_fraction": headline.get("cd8_hot_sample_fraction"),
            "frame": (headline.get("claim_vector") or {}).get("heterogeneity_frame"),
        },
        "suppression": {
            "cd8_treg_ratio": headline.get("cd8_treg_ratio"),
            "cd8_m2_ratio": headline.get("cd8_m2_ratio"),
            "median_treg_fraction": headline.get("median_treg_fraction"),
            "median_m2_macrophage_fraction": headline.get("median_m2_macrophage_fraction"),
            "median_m1_macrophage_fraction": headline.get("median_m1_macrophage_fraction"),
            "frame": (headline.get("claim_vector") or {}).get("suppression_frame"),
            # DESCRIPTIVE ONLY, and this is a deliberate scope limit, not an oversight: 0.113/0.084 are the
            # 33-study Q3/Q1 of the CD8 SHARE, and no equivalent pan-cancer distribution has been derived
            # for a hot-sample PREVALENCE or a CD8:suppressor ratio. A demote cut here would be an
            # unanchored number wearing a threshold's clothes. Derive it from the same 11,373-sample
            # product before anything is allowed to gate on these.
            "gating": "none — no pan-cancer distribution derived for these ratios yet",
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
        # HETEROGENEITY + SUPPRESSION (2026-09-12). The card has emitted these six since v1.2.0 and NOTHING
        # downstream read them — not the headline, not the atom, not the facet. The mirror guard cannot catch
        # that: it runs card-DECLARES -> reader-EMITS, so a field the reader emits and no consumer consumes
        # is invisible to it. `_cf` (not the strict getter) because a pre-1.2.0 card must degrade to None.
        # Verdict-INERT: they feed the two new frame scalars and the provenance block, never the verdict.
        "cd8_hot_sample_fraction": _cf(cards, "immune-context", "cd8_hot_sample_fraction"),
        "cd8_treg_ratio": _cf(cards, "immune-context", "cd8_treg_ratio"),
        "cd8_m2_ratio": _cf(cards, "immune-context", "cd8_m2_ratio"),
        "median_treg_fraction": _cf(cards, "immune-context", "median_treg_fraction"),
        "median_m2_macrophage_fraction": _cf(cards, "immune-context", "median_m2_macrophage_fraction"),
        "median_m1_macrophage_fraction": _cf(cards, "immune-context", "median_m1_macrophage_fraction"),
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
    hl["til_cibersort_agreement"] = _til_cibersort_agreement(hl["immune_context_class"], hl["til_fraction_class"])
    # T0-4 spatial resolution of the inflamed-vs-EXCLUDED call. Computed HERE (a pure function of
    # spatial_coloc_class, already on `hl`) because the corroboration ruler in immune_context_claims
    # reads it: spatial EXCLUSION on a positive bulk read is a CONTRADICTION, not display context.
    hl["spatial_immune_phenotype"] = _spatial_immune_phenotype(hl)
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
            # The TCE EFFECTOR arm's contribution to the composed modality conjunction. Until 2026-09-12
            # this rode ONLY the legacy `claim_record_shadow` (_claim_record below), so
            # tp_facets._modality_scope_by_axis reached it via the FALLBACK leg and standalone
            # decision.json carried no bite_tce read at all. Now it is on the skill_report SPINE, like
            # every other modality-speaking skill (surface-modality-fit / functional-requirement /
            # on-target-safety-liability / tractability-small-molecule).
            modality_scope=_immune_modality_scope(hl.get("immune_context_verdict"), hl),
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
    # v1.9.0 (VERDICT-INERT): the card's HETEROGENEITY + SUPPRESSION fields, which no consumer read before.
    # cd8_hot_sample_fraction is the target-INDEPENDENT half of the cohort-median blind spot (no barcode
    # join needed, so it is available wherever the class is); the ratios say whether a hot cohort is also a
    # SUPPRESSED one. Their gauged prose rides claim_vector.{heterogeneity,suppression}_frame.
    "cd8_hot_sample_fraction",
    "cd8_treg_ratio",
    "cd8_m2_ratio",
    "median_treg_fraction",
    "median_m2_macrophage_fraction",
    "median_m1_macrophage_fraction",
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
    # DELIBERATELY ABSENT: `lymphoid_denominator_unreliable`. An uninterpretable denominator must contribute
    # NOTHING to the bite_tce channel — silence (na), exactly like the no-cohort case. Both a `conditional`
    # and an `unfavorable` here would be this skill asserting a TCE read it has explicitly disclaimed, in
    # precisely the indications where TCEs are the validated modality. Matches the rule's bite_tce: neutral.
}  # insufficient / no cohort / uninterpretable denominator → silent (na)


def _immune_modality_scope(verdict: "str | None", orthogonal: "dict | None" = None) -> "dict | None":
    """bite_tce favorability for the composed modality conjunction, with a DEMOTE-ONLY cap when an
    ORTHOGONAL platform CONTRADICTS the CIBERSORT read (the same `orthogonal_discordance_text` ruler that
    drives the claim `conflict`, the key_signals caveat and the headline top_tension — one ruler, so the
    FOR-WHAT projection cannot say `favorable` while every prose surface says "interpret with caution").

    Two contradiction shapes reach it: absolute H&E-DL TIL discordance (CD8-rich SHARE but low ABSOLUTE
    lymphocyte density — few effectors to redirect, the PRAD shape) and spatial IMMUNE-EXCLUSION (CD8 in
    the leukocyte compartment but NOT adjacent to the target-positive malignant cells). Both are direct
    TCE-EFFICACY arguments, so a `favorable` channel over-claims and caps at `conditional`.

    It never PROMOTES, and never reaches `unfavorable`: the spatial-coloc products carry no donor floor (a
    1-donor read must not move a channel two rungs), CIBERSORT is relative + non-spatial, and the immune
    rules are `opposing`/`important`, never `killer` — hence a cap, not a kill."""
    fit = _IMMUNE_TCE_FIT.get(verdict)
    if not fit:
        return None
    if fit == "favorable" and orthogonal_discordance_text(orthogonal or {}):
        fit = "conditional"
    return {"_refinements": {"bite_tce": fit}}


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
        # same DEMOTE-ONLY spatial override as the skill_report spine leg (single ruler, no drift)
        modality_scope=_immune_modality_scope(v, _orthogonal_reads(cards)),
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
