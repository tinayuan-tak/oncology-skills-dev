#!/usr/bin/env python3
"""translational-readiness — Phase-J PARTIAL skill (graduated 2026-08-14, scientific-gap #1).

Was a pure placeholder (emit_placeholder). Now PARTIALLY wired: it composes the
target-model-availability card (HCMI patient-derived model coverage per indication) — the
"can I preclinically validate a nomination in this indication?" leg of translational readiness.

DESCRIPTIVE (verdict_fn=None): like target-intrinsic, this skill emits no nomination verdict — model
availability is translational CONTEXT that informs confidence, not a gate. Uses the shared
run_wired_skill dispatcher; skill-specific logic reduces to CARDS + a headline callback.

STILL PARTIAL: the PD-assay, imaging-tracer, and INTERNAL Takeda models (PDX/organoid/GEMM) legs
remain un-wired (those catalogs are not in data-catalog) — surfaced in partial_status_note. The
public HCMI model-availability card is the first real translational signal wired here; the
genotype-MATCHED refinement (does an available model carry THIS target's alteration?) is a v2.
"""

from __future__ import annotations

import sys

from _skills_common import card_summary, get_card_field
from _skills_common.dispatcher import run_wired_skill
from _skills_common.headline_core import HeadlineSpec, build_headline, build_synthesis_facet
from _skills_common.literature_retrieval import default_retrieve, verify_citations
from _skills_common.literature_synthesis import make_literature_fn
from _skills_common.narrator_engine import make_synthesize_fn
from _skills_common.narrator_lenses import TRANSLATIONAL_READINESS as _LENS
from _skills_common.skill_report import ROLE_DESCRIPTIVE, build_skill_report
from _skills_common.translational_readiness_claims import (
    translational_readiness_claim_vector,
    translational_readiness_key_signals,
)
from _skills_common.translational_readiness_question_table import translational_readiness_question_table

SKILL_NAME = "translational-readiness"
SKILL_VERSION = "1.5.0"  # 1.5.0 (2026-09-05, literature-and-claims arc, 14th/FINAL skill): CREATE the
# TRANSLATIONAL_READINESS narrator lens (was NONE) + wire synthesize_fn + BAKE the
# --literature lane; verdict-INERT preclinical-readiness confidence surface —
# translational_readiness_confidence_caveat (3-tier: model_available_fidelity_
# unconfirmed / small_cohort_or_attribution_confounded / validated_preclinical_model
# false-demote guard) + model_fidelity_caveat + coverage_generalization_caveat
# (public-only + status:partial) + translational_readiness_provenance QUORUM. GATELESS
# + TOKENLESS → verdict None + gate None byte-stable. SET literals not 2-tuples.

# The organoid-crispr-dependency card documents min_organoid_models: 20 as the cohort below which the
# organoid dependency fraction is uninterpretable, but its `small_organoid_cohort` warning keys on the
# PAN-organoid n_models_screened (~114 for most genes → effectively never fires). The INDICATION-matched
# per-lineage read is where the small cohorts actually surface: the two smallest emitted organoid lineages
# (Prostate n=9, Breast n=16 in 26Q1) sit BELOW that floor, yet the reader emits a full organoid_lineage_class
# for them with no caveat. Surface a small-cohort flag HERE (verdict-inert, this skill's own surface) so a
# consumer reading organoid_lineage_class knows the indication-matched fraction rests on a thin cohort. The
# per-gene matrix is dense (min n_screened == the lineage cohort, ≥9), so this is a low-cohort RELIABILITY
# caveat, not a thin-N-artifact floor — the class is left unchanged.
_ORGANOID_LINEAGE_MIN_MODELS = 20  # mirrors the organoid card's THRESHOLD.min_organoid_models

CARDS = [
    "target-model-availability",  # scientific-gap #1 (2026-08-14): per-indication HCMI patient-derived
    # model coverage (organoid/next-gen cancer models). INDICATION-level,
    # target-independent translational cohort context. VERDICT-INERT.
    "target-genotype-matched-model",  # genotype-matched refinement (2026-08-24): do the available HCMI
    # models CARRY a functional coding alteration in THIS target? (gene x
    # indication; HCMI WXS MAF join). VERDICT-INERT translational context.
    "target-pdx-drug-response",  # in-vivo tractability corroboration (Novartis PDXE, Gao 2015): do
    # treatments naming the target produce tumour regression in PDX
    # population trials? Target-grain. VERDICT-INERT display facet.
    "organoid-crispr-dependency",  # ex-vivo validation-readiness (2026-08-28): does the target's dependency
    # REPRODUCE in patient-derived organoid (DepMap 3D CRISPR) models — the
    # ex-vivo complement of the PDX in-vivo leg? BORROWED from the dependency
    # axis (home: functional-requirement); read here with a TRANSLATIONAL
    # framing. VERDICT-INERT (skill has verdict_fn=None → fires no dependency rule).
]

QUESTION = (
    "How translationally ready is {target} in {indication} — are there patient-derived "
    "(HCMI organoid / next-generation cancer) models available to preclinically validate a "
    "nomination (and do those models carry the target's alteration), does the target's dependency "
    "reproduce EX VIVO in patient-derived organoid models, and does its drug-response reproduce "
    "IN VIVO in PDX population trials? (PD-assay, imaging-tracer, and internal-model legs remain "
    "un-wired.)"
)

# Honest partial-coverage note: the internal Takeda models registry (PDX/organoid/GEMM), PD-assay, and
# imaging-tracer catalogs are NOT in data-catalog, so those legs are still un-wired. Three public
# translational legs are now reflected: HCMI model-availability, HCMI genotype-matched-model coverage,
# and PDXE in-vivo drug-response.
PARTIAL_STATUS_NOTE = (
    "translational-readiness is status: partial — four public translational legs are wired: HCMI "
    "model-availability (target-model-availability; INDICATION-level, target-independent), HCMI "
    "genotype-matched-model coverage (target-genotype-matched-model; does an available model carry THIS "
    "target's alteration?), organoid ex-vivo dependency reproduction (organoid-crispr-dependency; does the "
    "target's dependency hold in patient-derived 3D CRISPR models?), and PDXE in-vivo drug-response "
    "(target-pdx-drug-response; does the target's tractability reproduce in PDX population trials?). The "
    "PD-assay, imaging-tracer, and INTERNAL Takeda models (PDX/organoid/GEMM) catalogs are not yet in "
    "data-catalog. All four legs are VERDICT-INERT translational context; they inform confidence, not a "
    "nomination gate."
)


# ── TRANSLATIONAL-READINESS confidence surface (VERDICT-INERT) — the preclinical-validatability analog of
#    surface's surface_confirmation_caveat / combination's partner_confirmation_caveat / mechanism's
#    mechanism_confirmation_caveat. THE TRAP: a MODEL-AVAILABILITY / GENOTYPE-MATCHED / PDX-RESPONDER read
#    OVER-CALLS actual translational VALIDATABILITY (a FAITHFUL, on-target, adequately-powered preclinical
#    validation). Five sub-inflations: (a) MODEL AVAILABILITY ≠ MODEL FIDELITY — an HCMI model EXISTING does
#    not mean it faithfully recapitulates the target biology (passage/CNA drift + clonal selection — Ben-David
#    2017 PMID 28991255; TME/immune absence in submerged organoids — Neal 2018 PMID 30550791; PDX
#    mouse-stroma replacement — Byrne 2017 PMID 28104906); (b) GENOTYPE-MATCHED ≠ TARGET-DEPENDENT — carrying
#    the alteration is not proof of a validatable dependency (only a SUBSET of genotype-matched lines are
#    dependent — Singh 2009 PMID 19477428; co-occurring drivers / passengers — Vogelstein 2013 PMID 23539594;
#    mutation is a weak response predictor — Iorio 2016 PMID 27397505; a matched LoF genotype implies a
#    synthetic-lethal dependence on a DIFFERENT gene, not on-target — Lord & Ashworth 2017 PMID 28302823);
#    (c) SMALL-COHORT PDX/ORGANOID — a PDXE responder fraction or an organoid dependency read on a tiny cohort
#    is underpowered (selective dependencies need hundreds of models — Tsherniak 2017 PMID 28753430; Behan
#    2019 PMID 30971826; a ~114-model organoid panel's per-lineage slice is thin); (d) PDX DRUG-RESPONSE
#    ATTRIBUTION — a PDXE objective response to a drug 'naming' the target can be OFF-TARGET or
#    COMBINATION-confounded (drug efficacy can persist after target loss — Lin/Giuliano 2019 PMID 31511426);
#    (e) PUBLIC-ONLY / status:partial — the dossier is PUBLIC-model-only + the PD-assay / imaging-tracer /
#    INTERNAL Takeda PDX/organoid/GEMM legs are un-wired, so a 'ready' read on 4 public legs is a
#    COVERAGE-bounded readiness. translational-readiness is GATELESS (verdict_fn=None) + TOKENLESS (no
#    resolver), so — like combination / mechanism — these are VERDICT-INERT annotation layers over the
#    already-built model/genotype/organoid/PDX dossier, NEVER read by a resolver: the honest discriminator is
#    a SMALL, DISCLAIMED, NON-EXHAUSTIVE curated (target, indication) crosswalk of canonical
#    faithfulness-validated preclinical-model precedents, corroborated by the --literature lane + narrator. A
#    target absent from the crosswalk degrades to the DATA-derived tier or None (never a verdict change; there
#    is no verdict to change). SET literals / dict, not 2-string tuples (reference-drift guard).

# NORMALISE the OncoTree code so the COADREAD crosswalk also matches COAD / READ, and the composite
# lung/gastric codes match their leaves (mirrors the HCMI reader's leaf→composite normalization).
_TR_IND_ALIAS = {
    "COAD": "COADREAD",
    "READ": "COADREAD",
    "LUAD": "NSCLC",
    "LUSC": "NSCLC",
    "STAD": "GC",
    # ESCA→GC removed (#1272): the HCMI reader keeps ESCA as its own product key (96 models,
    # deep coverage), so folding ESCA→GC here contradicted the reader. Verdict-inert (this map only
    # keys the curated _VALIDATED_PRECLINICAL_MODEL crosswalk, which has no ESCA/GC entry).
    "COADREAD": "COADREAD",
}


def _tr_norm_ind(indication) -> str:
    ind = (indication or "").upper().strip()
    return _TR_IND_ALIAS.get(ind, ind)


# (target, indication) whose available PUBLIC patient-derived models are a CANONICAL, FAITHFULNESS-VALIDATED,
# ON-TARGET preclinical-validation precedent — the MILDER false-demote guard (mirrors combination's
# _VALIDATED_COMBINATION_PRECEDENT / differentiation's _BIOLOGICALLY_ESTABLISHED_COMUT). Spared from the
# statistical fidelity-unconfirmed / small-cohort / attribution tiers: these are NOT over-calls — the target
# has faithful patient-derived models that carry the alteration AND in which an on-target agent has produced
# a genotype-matched response. DISCLAIMED / non-exhaustive; an absent (target, indication) degrades to a
# data-derived tier or None. NOTE the deliberate exclusion of (KRAS, PAAD): PDAC models are faithful and
# carry KRAS, but the dominant PAAD allele is G12D and on-target small-molecule validation in PAAD models
# lags (a G12D inhibitor is only recently preclinical) — so KRAS/PAAD correctly degrades to the
# fidelity-UNCONFIRMED tier, not the validated guard. Indications use the reader's composite codes
# (NSCLC / GC / COADREAD) — _tr_norm_ind normalises leaves in. PMIDs are from this arc's verified Phase-1 review.
_VALIDATED_PRECLINICAL_MODEL = {
    ("ERBB2", "BRCA"): (
        "Canonical, faithfulness-validated HER2 breast preclinical models: patient-derived "
        "breast PDX authentically recapitulate the primary tumour (DeRose 2011 PMID 22019887) "
        "and the HER2-amplified breast-organoid biobank shows genotype-matched HER2-agent "
        "response (Sachs 2018 PMID 29224780); on-target trastuzumab / T-DM1 pharmacology + "
        "subclonal resistance reproduce in these models. NOT a model-availability over-call."
    ),
    ("EGFR", "NSCLC"): (
        "Canonical EGFR-mutant lung preclinical models: patient-derived lung organoids "
        "recapitulate EGFR-mutant histology/genomics for TKI screening (Kim 2019 PMID 31488816) "
        "+ NSCLC PDX panels for TKI sensitivity/resistance (Kita 2019 PMID 31432603); "
        "osimertinib on-target regression validated in EGFR-mutant/T790M models (Cross 2014 "
        "PMID 24893891). NOT an over-call."
    ),
    ("KRAS", "COADREAD"): (
        "Validated KRAS-G12C colorectal preclinical models: G12C-inhibitor (adagrasib) "
        "on-target activity in KRAS-mutant PDX incl. colorectal (Hallin 2020 PMID 31658955), "
        "the CRC-specific G12Ci+cetuximab (EGFR) combination biology validated in CRC "
        "organoids + PDX (Amodio 2020 PMID 32430388), and GI/CRC organoids predict clinical "
        "response (Vlachogiannis 2018 PMID 29472484). NOT an over-call — but NB G12C is a "
        "MINORITY allele in CRC; the validated on-target precedent is allele-specific."
    ),
}


def _tr_positive_substrate(hl: dict) -> bool:
    """Is there an INDICATION-RELEVANT positive readiness signal to confidence-qualify? True when models are
    AVAILABLE in the indication, OR a genotype-matched model exists, OR PDX shows objective responders, OR the
    INDICATION-MATCHED organoid lineage is dependent. A pan-organoid-only read with everything else
    data_unavailable (e.g. a rare indication with no HCMI models + no mapped organoid lineage) is NOT positive
    substrate → the confidence caveat is None (honest thin degrade, not a manufactured readiness)."""
    _DEP_ORG = {"pan_organoid_essential", "broad_organoid_dependency", "selective_organoid_dependency"}
    model_ok = hl.get("model_availability_class") in {
        "deep_model_coverage",
        "moderate_model_coverage",
        "sparse_model_coverage",
    } and bool(hl.get("n_patient_derived_models"))
    geno_ok = hl.get("genotype_matched_class") in {"matched_deep", "matched_sparse"}
    pdx_ok = hl.get("pdx_drug_response_class") == "pdx_objective_responders"
    org_ok = hl.get("organoid_lineage_class") in _DEP_ORG  # INDICATION-matched organoid only
    return bool(model_ok or geno_ok or pdx_ok or org_ok)


def _tr_pdx_attribution_confound(hl: dict):
    """Detect the (d) PDX-attribution sub-inflation: an objective-response read whose most-active treatment is
    a COMBINATION (response not attributable to a single on-target agent) OR a LOW responder fraction
    (underpowered / weak). Returns a reason string or None. Only meaningful when PDX shows responders."""
    if hl.get("pdx_drug_response_class") != "pdx_objective_responders":
        return None
    treat = hl.get("pdx_most_active_treatment") or ""
    frac = hl.get("pdx_responder_fraction")
    bits = []
    if " + " in treat:  # combination agent → attribution ambiguous
        bits.append(
            f"the most-active PDXE treatment is a COMBINATION ('{treat}') — an objective response is "
            "not attributable to a single on-target agent (it may reflect the partner arm)"
        )
    if isinstance(frac, (int, float)) and frac < 0.15:
        bits.append(
            f"the PDXE objective-response fraction is LOW ({frac:.1%}) — a weak / underpowered population signal"
        )
    return "; ".join(bits) if bits else None


def _translational_readiness_confidence_caveat(hl: dict, target=None, indication=None) -> dict | None:
    """CONSOLIDATED availability-vs-validated preclinical-readiness confidence call (VERDICT-INERT). Precedence:
    the MILDER canonical faithfulness-validated-model guard (iii) FIRST (ERBB2/BRCA, EGFR/NSCLC, KRAS/COADREAD
    must NOT be flagged) > the SHARP small-cohort / PDX-attribution confound (ii) > the SHARP generic
    fidelity-unconfirmed default (i) > None (no positive substrate → honest thin). Gates on already-emitted
    model/genotype/organoid/PDX fields + the curated (target, indication) crosswalk; never moves a spine
    (there is none — gateless + tokenless)."""
    if not _tr_positive_substrate(hl):
        return None  # thin / rare → byte-stable honest degrade
    key = ((target or "").upper().strip(), _tr_norm_ind(indication))

    # TIER (iii) MILDER — canonical faithfulness-validated preclinical-model guard (false-demote).
    if key in _VALIDATED_PRECLINICAL_MODEL:
        return {
            "reason": "validated_preclinical_model",
            "tier": "milder",
            "false_demote_guarded": True,
            "detail": _VALIDATED_PRECLINICAL_MODEL[key],
        }

    # TIER (ii) SHARP — small-cohort (organoid per-lineage below the min-model floor) OR PDX-attribution
    # confound (combination / low responder fraction). The more-specific sharp tier.
    small_cohort = bool(hl.get("organoid_lineage_small_cohort"))
    pdx_confound = _tr_pdx_attribution_confound(hl)
    if small_cohort or pdx_confound:
        bits = []
        if small_cohort:
            n = hl.get("organoid_lineage_n_screened")
            bits.append(
                f"the INDICATION-matched organoid dependency read rests on a THIN cohort "
                f"(n={n} < the organoid card's min_organoid_models=20 reliability floor) — a selective "
                "dependency needs hundreds of models to call reliably (Tsherniak 2017 PMID 28753430; "
                "Behan 2019 PMID 30971826)"
            )
        if pdx_confound:
            bits.append(
                pdx_confound + " — a PDX objective response to an agent 'naming' the target can be "
                "OFF-TARGET or combination-driven (efficacy can persist after target loss; Lin/Giuliano "
                "2019 PMID 31511426)"
            )
        return {
            "reason": "small_cohort_or_attribution_confounded",
            "tier": "sharp",
            "false_demote_guarded": False,
            "detail": (
                "The readiness read is UNDERPOWERED or attribution-confounded: "
                + "; ".join(bits)
                + ". Treat as a hypothesis pending an adequately-powered, on-target-attributed "
                "preclinical validation; the dependency MAGNITUDE is owned by functional-requirement "
                "and the small-molecule tractability call by tractability-small-molecule."
            ),
        }

    # TIER (i) SHARP — generic fidelity-UNCONFIRMED default: models exist / genotype-matched / organoid-
    # dependent, but faithfulness + on-target validatability are UNCONFIRMED in-package.
    return {
        "reason": "model_available_fidelity_unconfirmed",
        "tier": "sharp",
        "false_demote_guarded": False,
        "detail": (
            "Public patient-derived models are AVAILABLE (and/or genotype-matched / organoid-"
            "dependent), but MODEL AVAILABILITY ≠ MODEL FIDELITY and GENOTYPE-MATCH ≠ "
            "TARGET-DEPENDENCE: an existing/genotype-matched model is not proof it faithfully "
            "recapitulates the target biology (passage/CNA drift + clonal selection — Ben-David 2017 "
            "PMID 28991255) or that the target is an on-target-validatable dependency in it "
            "(co-occurring drivers / passengers — Vogelstein 2013 PMID 23539594; only a subset of "
            "genotype-matched lines are dependent — Singh 2009 PMID 19477428). Treat as a CANDIDATE "
            "validation system pending a measured, on-target-attributed dependency/tractability "
            "read (owned by functional-requirement / tractability-small-molecule)."
        ),
    }


def _model_fidelity_caveat(hl: dict, target=None, indication=None) -> dict | None:
    """The (a)/(b) sub-inflations (VERDICT-INERT): a UNIVERSAL data-provenance note (fires whenever there is
    positive readiness substrate — orthogonal to whether the target is a validated precedent): model
    AVAILABILITY / genotype-MATCH is not model FIDELITY / target-DEPENDENCE. None on the thin/empty path
    (byte-stable)."""
    if not _tr_positive_substrate(hl):
        return None
    return {
        "reason": "availability_or_genotype_match_not_fidelity_or_dependence",
        "tier": "context",
        "detail": (
            "The readiness legs are PUBLIC patient-derived MODELS (HCMI availability + WXS "
            "genotype-match), an ex-vivo ORGANOID CRISPR dependency, and an in-vivo PDXE "
            "drug-response — none of which is fidelity- or on-target-validated in-package. Patient-"
            "derived models drift (passage/CNA drift + selection of pre-existing clones, "
            "mouse-specific evolution that does NOT mirror human tumour evolution — Ben-David 2017 "
            "PMID 28991255; PDX mouse-stroma replacement + no human adaptive immune TME — Byrne 2017 "
            "PMID 28104906; submerged tumour organoids lack the immune/stromal TME — Neal 2018 PMID "
            "30550791) and a genotype-matched model may be driven by a co-occurring driver or carry "
            "the alteration as a passenger (Vogelstein 2013 PMID 23539594; a matched LoF genotype "
            "implies a synthetic-lethal dependence on a DIFFERENT gene, not on-target — Lord & "
            "Ashworth 2017 PMID 28302823). Model availability/genotype-match is a CANDIDATE "
            "validation system, not a demonstrated faithful, on-target one."
        ),
    }


def _coverage_generalization_caveat(hl: dict, target=None, indication=None) -> dict | None:
    """The (e) sub-inflation (VERDICT-INERT): the dossier is PUBLIC-model-only + status:partial. A universal
    coverage note (fires on ANY real run — the leg classes are always emitted, even as data_unavailable):
    the un-wired PD-assay / imaging-tracer / INTERNAL Takeda PDX/organoid/GEMM legs are a COVERAGE gap, not an
    absence of readiness, and a data_unavailable public read can under-state readiness where non-public models
    exist (e.g. a rare-indication PDX/organoid published in the literature but absent from the public HCMI
    catalog). None only on a truly empty fixture (no leg-class fields at all)."""
    _leg_fields = (
        "model_availability_class",
        "genotype_matched_class",
        "organoid_dependency_class",
        "pdx_drug_response_class",
    )
    if not any(hl.get(f) is not None for f in _leg_fields):
        return None  # empty fixture → byte-stable
    return {
        "reason": "public_model_only_status_partial",
        "tier": "context",
        "detail": (
            "This is a PUBLIC-model-only readiness read (HCMI availability + HCMI genotype-match + "
            "DepMap organoid CRISPR + Novartis PDXE) and the skill is status:partial — the PD-assay, "
            "imaging-tracer, and INTERNAL Takeda PDX/organoid/GEMM model legs are un-wired. So a "
            "'ready' read is a COVERAGE-BOUNDED readiness over 4 public legs, and a data_unavailable "
            "public read is a COVERAGE gap (models may exist in the literature or internally), NOT a "
            "proven absence of a validatable model."
        ),
    }


def _translational_readiness_provenance(hl: dict, target=None, indication=None) -> dict | None:
    """QUORUM / PROVENANCE summary for the readiness dossier (VERDICT-INERT): which of the four public legs
    (MODEL/GENOTYPE/ORGANOID/PDX) are POPULATED (vs data_unavailable), the model + alteration counts, the
    organoid cohort size + small-cohort flag, the PDX responder fraction + most-active treatment +
    combination-attribution flag, and the curated validated-precedent flag — so an availability-only read is
    never mistaken for a faithful, on-target, adequately-powered validation. None only on a truly empty
    fixture (byte-stable)."""
    _leg_fields = {
        "MODEL": "model_availability_class",
        "GENOTYPE": "genotype_matched_class",
        "ORGANOID": "organoid_dependency_class",
        "PDX": "pdx_drug_response_class",
    }
    if not any(hl.get(f) is not None for f in _leg_fields.values()):
        return None
    populated = [
        axis
        for axis, fld in _leg_fields.items()
        if hl.get(fld) not in (None, "data_unavailable", "pdx_response_unavailable")
    ]
    key = ((target or "").upper().strip(), _tr_norm_ind(indication))
    treat = hl.get("pdx_most_active_treatment") or ""
    return {
        "legs_populated": populated,
        "n_legs_populated": len(populated),
        "model_availability_class": hl.get("model_availability_class"),
        "n_patient_derived_models": hl.get("n_patient_derived_models"),
        "model_source": hl.get("model_source"),
        "genotype_matched_class": hl.get("genotype_matched_class"),
        "n_models_with_alteration": hl.get("n_models_with_alteration"),
        "organoid_dependency_class": hl.get("organoid_dependency_class"),
        "organoid_lineage": hl.get("organoid_lineage"),
        "organoid_lineage_class": hl.get("organoid_lineage_class"),
        "organoid_lineage_n_screened": hl.get("organoid_lineage_n_screened"),
        "organoid_lineage_small_cohort": bool(hl.get("organoid_lineage_small_cohort")),
        "pdx_drug_response_class": hl.get("pdx_drug_response_class"),
        "pdx_responder_fraction": hl.get("pdx_responder_fraction"),
        "pdx_most_active_treatment": hl.get("pdx_most_active_treatment"),
        "pdx_treatment_is_combination": " + " in treat,
        "validated_preclinical_model_flag": key in _VALIDATED_PRECLINICAL_MODEL,
        "public_model_only": True,  # HCMI + DepMap + PDXE; no internal / PD-assay / imaging legs
        "status_partial": True,  # PD-assay / imaging-tracer / internal Takeda legs un-wired
    }


# Canonical headline spec (DESCRIPTIVE MODE — verdict_token=None). The four translational legs, in
# display order; MODEL (can I validate at all?) is the coverage-critical axis that floors confidence.
_TRANSLATIONAL_HEADLINE_SPEC = HeadlineSpec(
    gate="translational_readiness",
    axis_labels={
        "MODEL": "HCMI models",
        "GENOTYPE": "genotype-matched",
        "ORGANOID": "organoid (ex-vivo)",
        "PDX": "PDX (in-vivo)",
    },
    axis_keys=("MODEL", "GENOTYPE", "ORGANOID", "PDX"),
    critical_axes=("MODEL",),
)


def _build_headline_block(headline: dict) -> dict:
    """Canonical Headline block in DESCRIPTIVE MODE — translational-readiness is gateless (verdict_fn=None),
    so verdict_token=None and the deterministic key_signals.headline dominant-signal summary is the
    descriptive_phrase (call stays None, polarity defaults neutral). Never moves a spine (there is none)."""
    ks = headline.get("key_signals") or {}
    return build_headline(
        headline,
        headline.get("claim_vector"),
        headline.get("key_signals"),
        spec=_TRANSLATIONAL_HEADLINE_SPEC,
        verdict_token=None,
        descriptive_phrase=ks.get("headline"),
    )


def _headline(cards, fired, verdict_pair, target=None, indication=None):
    """Descriptive translational-readiness context — model-availability fields from the composed card.
    No verdict spine (verdict_fn=None): translational readiness informs confidence/context, not a
    nomination. A composed consumer reads these as indication-grain translational context.

    target / indication are OPTIONAL (the dispatcher signature-introspects headline_fn and passes them when
    present) — they key the (target)-crosswalk false-demote guard in translational_readiness_confidence_caveat."""
    # organoid-crispr-dependency is HOME'd under functional-requirement (composed there, not double-read
    # under this skill's composer entry — tp_fanout SUB_SKILL_CARDS comment). So read it GRACEFULLY
    # (card_summary → {} when absent) rather than the strict get_card_field (which RAISES on a missing
    # card): in the composed fan-out this card is legitimately absent here, so the ORGANOID leg is an
    # honest `unmeasured`; standalone (its CARDS list composes it) the leg is populated. The other three
    # legs' cards ARE in this skill's composer entry, so they stay on the strict accessor.
    _org = card_summary(cards, "organoid-crispr-dependency")
    organoid_lineage_n_screened = _org.get("organoid_lineage_n_screened")
    hl = {
        "model_availability_class": get_card_field(cards, "target-model-availability", "model_availability_class"),
        "n_patient_derived_models": get_card_field(cards, "target-model-availability", "n_patient_derived_models"),
        "primary_site_breakdown": get_card_field(cards, "target-model-availability", "primary_site_breakdown"),
        "model_source": get_card_field(cards, "target-model-availability", "source"),
        # genotype-matched refinement — does an available HCMI model carry THIS target's alteration?
        "genotype_matched_class": get_card_field(cards, "target-genotype-matched-model", "genotype_matched_class"),
        "n_models_with_alteration": get_card_field(cards, "target-genotype-matched-model", "n_models_with_alteration"),
        # in-vivo (PDX) tractability corroboration — Novartis PDXE
        "pdx_drug_response_class": get_card_field(cards, "target-pdx-drug-response", "pdx_drug_response_class"),
        "pdx_responder_fraction": get_card_field(cards, "target-pdx-drug-response", "responder_fraction"),
        "pdx_most_active_treatment": get_card_field(cards, "target-pdx-drug-response", "most_active_treatment"),
        # regression MAGNITUDE (signed % tumour-volume change; more-negative = more shrinkage — the
        # decisive datum per the card's own doc, target-pdx-drug-response.card.yaml:56-57) + cohort-size
        # / breadth context, previously computed+emitted by the reader but read by no consumer (#1548):
        "pdx_median_best_avg_response": get_card_field(cards, "target-pdx-drug-response", "median_best_avg_response"),
        "pdx_min_best_avg_response": get_card_field(cards, "target-pdx-drug-response", "min_best_avg_response"),
        "pdx_n_models_tested": get_card_field(cards, "target-pdx-drug-response", "n_models_tested"),
        "pdx_n_response_records": get_card_field(cards, "target-pdx-drug-response", "n_response_records"),
        "pdx_most_active_treatment_median_best_avg_response": get_card_field(
            cards, "target-pdx-drug-response", "most_active_treatment_median_best_avg_response"
        ),
        "pdx_treatment_types": get_card_field(cards, "target-pdx-drug-response", "treatment_types"),
        # ex-vivo (patient-derived organoid) dependency reproduction — DepMap 3D CRISPR. BORROWED from
        # the dependency axis, read here as translational validation-readiness. The indication-matched
        # organoid_lineage_frac_dependent is the strongest translational read; the pan-organoid
        # frac_dependent + class are the fallback when the indication has no mapped organoid lineage.
        "organoid_dependency_class": _org.get("organoid_dependency_class"),
        "organoid_frac_dependent": _org.get("frac_dependent"),
        "organoid_lineage": _org.get("organoid_lineage"),
        "organoid_lineage_frac_dependent": _org.get("organoid_lineage_frac_dependent"),
        "organoid_lineage_class": _org.get("organoid_lineage_class"),
        # thin-cohort reliability caveat on the indication-matched per-lineage read (see the module note):
        # organoid_lineage_class computed over a lineage cohort below the organoid card's own
        # min_organoid_models=20 floor (e.g. Prostate n=9, Breast n=16) is a low-confidence read.
        "organoid_lineage_n_screened": organoid_lineage_n_screened,
        "organoid_lineage_small_cohort": (
            organoid_lineage_n_screened is not None and organoid_lineage_n_screened < _ORGANOID_LINEAGE_MIN_MODELS
        ),
    }
    # ── verdict-INERT signals-first projections (mirrors the other descriptive skills) ─────────────
    # claim_vector (MODEL/GENOTYPE/ORGANOID/PDX) + deterministic key_signals over the fields just built.
    hl["claim_vector"] = translational_readiness_claim_vector(hl, cards)
    hl["key_signals"] = translational_readiness_key_signals(hl, cards)
    # CONSOLIDATED preclinical-readiness confidence caveats + provenance quorum (VERDICT-INERT) — the
    # preclinical-validatability analog of combination/surface/mechanism's confirmation-caveat surface. Gate on
    # the already-emitted model/genotype/organoid/PDX fields + the curated (target, indication) crosswalk; None
    # on the thin/empty / validated-guarded paths → the model/genotype/organoid/PDX dossier + verdict(=None)
    # byte-stable. Best-effort: a fault degrades to None + _enrichment_errors, never aborts the dossier.
    _cc = None
    try:
        _cc = _translational_readiness_confidence_caveat(hl, target=target, indication=indication)
        hl["translational_readiness_confidence_caveat"] = _cc
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the dossier
        hl.setdefault("_enrichment_errors", {})["translational_readiness_confidence_caveat"] = (
            f"{type(exc).__name__}: {exc}"
        )
        hl["translational_readiness_confidence_caveat"] = None
    for _fld, _fn in (
        ("model_fidelity_caveat", _model_fidelity_caveat),
        ("coverage_generalization_caveat", _coverage_generalization_caveat),
        ("translational_readiness_provenance", _translational_readiness_provenance),
    ):
        try:
            hl[_fld] = _fn(hl, target=target, indication=indication)
        except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the dossier
            hl.setdefault("_enrichment_errors", {})[_fld] = f"{type(exc).__name__}: {exc}"
            hl[_fld] = None
    # Surface the PRIMARY readiness-confidence caveat in the key_signals.caveat slot (read by the narrator +
    # cross-evidence) so it is deterministic, not LLM discretion. base key_signals sets no caveat on the
    # negative/thin path → caveat stays None → byte-stable.
    if _cc and _cc.get("detail") and isinstance(hl.get("key_signals"), dict):
        hl["key_signals"]["caveat"] = _cc["detail"]
    # The per-question (data·signal·confidence) LEADING table + the canonical DESCRIPTIVE headline block
    # + the UNIFIED skill_report. All best-effort + verdict-INERT — a formatting/read fault must NEVER
    # discard the translational-context fields already built in `hl` (tumor-presence degrade discipline).
    try:
        hl["question_table"] = translational_readiness_question_table(hl, cards)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the context spine
        hl.setdefault("_enrichment_errors", {})["question_table"] = f"{type(exc).__name__}: {exc}"
        hl["question_table"] = None
    try:
        hl["headline_block"] = _build_headline_block(hl)
    except Exception as exc:  # noqa: BLE001
        hl.setdefault("_enrichment_errors", {})["headline_block"] = f"{type(exc).__name__}: {exc}"
        hl["headline_block"] = None
    # UNIFIED skill_report (docs/UNIFIED_OUTPUT_CONTRACT.md) — translational-readiness is a GATELESS
    # DESCRIPTIVE skill (verdict_fn=None → no call), so role=descriptive + verdict=None → call=None,
    # polarity=not_scored; the reader-useful content is the honest_phrase + claim_chips.
    try:
        _used = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and not c.get("_missing")]
        _missing = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and c.get("_missing")]
        hl["skill_report"] = build_skill_report(
            role=ROLE_DESCRIPTIVE,
            verdict=None,
            headline_block=hl.get("headline_block"),
            claim_vector=hl.get("claim_vector"),
            question_table=hl.get("question_table"),
            fired_rule_ids=[f.get("rule_id") for f in (fired or [])],
            cards_used=_used or CARDS,
            cards_missing=_missing,
        )
    except Exception as exc:  # noqa: BLE001
        hl.setdefault("_enrichment_errors", {})["skill_report"] = f"{type(exc).__name__}: {exc}"
        hl["skill_report"] = None
    return hl


# ── OPTIONAL cross-modal synthesis facet (lifts the claim_vector to the composed target-profile) ────
# translational-readiness is DESCRIPTIVE (verdict_fn=None); this carries the verdict-INERT translational
# claim_vector + headline_block + question_table + skill_report to the composed target-profile synthesis
# (which reads getattr(module, "_synthesis_facet")). Never moves a verdict (there is none).
_SYNTHESIS_FACET_KEYS = (
    "model_availability_class",
    "n_patient_derived_models",
    "primary_site_breakdown",
    "model_source",
    "genotype_matched_class",
    "n_models_with_alteration",
    "pdx_drug_response_class",
    "pdx_responder_fraction",
    "pdx_most_active_treatment",
    "pdx_median_best_avg_response",
    "pdx_min_best_avg_response",
    "pdx_n_models_tested",
    "pdx_n_response_records",
    "pdx_most_active_treatment_median_best_avg_response",
    "pdx_treatment_types",
    "organoid_dependency_class",
    "organoid_frac_dependent",
    "organoid_lineage",
    "organoid_lineage_frac_dependent",
    "organoid_lineage_class",
    "organoid_lineage_n_screened",
    "organoid_lineage_small_cohort",
    "claim_vector",
    "key_signals",
    # the CONSOLIDATED preclinical-readiness confidence caveats + provenance quorum (verdict-INERT; the
    # preclinical-validatability analog of combination/surface/mechanism's confirmation-caveat surface):
    "translational_readiness_confidence_caveat",
    "model_fidelity_caveat",
    "coverage_generalization_caveat",
    "translational_readiness_provenance",
    "question_table",
    "headline_block",
    "skill_report",
)


def _synthesis_facet(cards, fired, verdict_pair=None, target=None, indication=None):
    """Compact, VERDICT-INERT translational facet for the composed target-profile synthesis. Reuses
    _headline (single source). Gateless — no verdict. target / indication are signature-introspected by the
    fan-out (tp_fanout) so the (target)-keyed validated-preclinical-model false-demote guard reaches the
    composed profile too."""
    h = _headline(cards, fired, verdict_pair, target=target, indication=indication)
    return build_synthesis_facet(
        h,
        _SYNTHESIS_FACET_KEYS,
        (
            "Deterministic translational-readiness facet; claim_vector is the four public "
            "readiness legs (MODEL/GENOTYPE/ORGANOID/PDX). Gateless — no verdict."
        ),
    )


if __name__ == "__main__":
    sys.exit(
        run_wired_skill(
            skill_name=SKILL_NAME,
            skill_version=SKILL_VERSION,
            cards=CARDS,
            axis="intracellular_intrinsic",  # rules axis for loading; translational-readiness emits no verdict
            question=QUESTION,
            verdict_fn=None,  # DESCRIPTIVE — model availability is translational context, not a gate
            headline_fn=_headline,
            # NET-NEW capsule-driven narrator (generic engine + this skill's LensConfig). translational-readiness
            # had NO lens/narrator before the literature-and-claims arc; TRANSLATIONAL_READINESS (mode=descriptive)
            # leads with faithful-on-target-validated vs availability-only/small-cohort/attribution-confounded.
            synthesize_fn=make_synthesize_fn(_LENS),
            # OPTIONAL verdict-INERT LLM --literature lane (BAKED 2026-09-05): Europe-PMC-grounded (default_retrieve
            # = Europe PMC → PubTator3 fallback) + PMID-verified (verify_citations); attached as
            # decision['literature_synthesis'] AFTER the deterministic dossier is composed and fed to the
            # --synthesize narrator as a corroboration/contradiction lane. Query terms
            # (_LENS_QUERY_TERMS["translational-readiness"] + the per-lens cap bump _LENS_MAX_TERMS=8) front-load the
            # PDX/organoid FIDELITY / DRIFT / PDXE-attribution discriminators. This skill is gateless — the lane
            # cannot touch a verdict (there is none).
            literature_fn=make_literature_fn(_LENS, retrieve_fn=default_retrieve, verify_fn=verify_citations),
            partial_status_note=PARTIAL_STATUS_NOTE,
        )
    )
