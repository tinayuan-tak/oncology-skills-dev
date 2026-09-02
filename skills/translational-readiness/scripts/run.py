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
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill
from _skills_common import get_card_field


SKILL_NAME = "translational-readiness"
SKILL_VERSION = "1.4.0"

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
    "target-model-availability",   # scientific-gap #1 (2026-08-14): per-indication HCMI patient-derived
                                   # model coverage (organoid/next-gen cancer models). INDICATION-level,
                                   # target-independent translational cohort context. VERDICT-INERT.
    "target-genotype-matched-model",  # genotype-matched refinement (2026-08-24): do the available HCMI
                                   # models CARRY a functional coding alteration in THIS target? (gene x
                                   # indication; HCMI WXS MAF join). VERDICT-INERT translational context.
    "target-pdx-drug-response",    # in-vivo tractability corroboration (Novartis PDXE, Gao 2015): do
                                   # treatments naming the target produce tumour regression in PDX
                                   # population trials? Target-grain. VERDICT-INERT display facet.
    "organoid-crispr-dependency",  # ex-vivo validation-readiness (2026-08-28): does the target's dependency
                                   # REPRODUCE in patient-derived organoid (DepMap 3D CRISPR) models — the
                                   # ex-vivo complement of the PDX in-vivo leg? BORROWED from the dependency
                                   # axis (home: functional-requirement); read here with a TRANSLATIONAL
                                   # framing. VERDICT-INERT (skill has verdict_fn=None → fires no dependency rule).
]

QUESTION = ("How translationally ready is {target} in {indication} — are there patient-derived "
            "(HCMI organoid / next-generation cancer) models available to preclinically validate a "
            "nomination (and do those models carry the target's alteration), does the target's dependency "
            "reproduce EX VIVO in patient-derived organoid models, and does its drug-response reproduce "
            "IN VIVO in PDX population trials? (PD-assay, imaging-tracer, and internal-model legs remain "
            "un-wired.)")

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


def _headline(cards, fired, verdict_pair):
    """Descriptive translational-readiness context — model-availability fields from the composed card.
    No verdict spine (verdict_fn=None): translational readiness informs confidence/context, not a
    nomination. A composed consumer reads these as indication-grain translational context."""
    organoid_lineage_n_screened = get_card_field(cards, "organoid-crispr-dependency",
                                                  "organoid_lineage_n_screened")
    return {
        "model_availability_class":  get_card_field(cards, "target-model-availability",
                                          "model_availability_class"),
        "n_patient_derived_models":  get_card_field(cards, "target-model-availability",
                                          "n_patient_derived_models"),
        "primary_site_breakdown":    get_card_field(cards, "target-model-availability",
                                          "primary_site_breakdown"),
        "model_source":              get_card_field(cards, "target-model-availability", "source"),
        # genotype-matched refinement — does an available HCMI model carry THIS target's alteration?
        "genotype_matched_class":    get_card_field(cards, "target-genotype-matched-model",
                                          "genotype_matched_class"),
        "n_models_with_alteration":  get_card_field(cards, "target-genotype-matched-model",
                                          "n_models_with_alteration"),
        # in-vivo (PDX) tractability corroboration — Novartis PDXE
        "pdx_drug_response_class":   get_card_field(cards, "target-pdx-drug-response",
                                          "pdx_drug_response_class"),
        "pdx_responder_fraction":    get_card_field(cards, "target-pdx-drug-response",
                                          "responder_fraction"),
        "pdx_most_active_treatment": get_card_field(cards, "target-pdx-drug-response",
                                          "most_active_treatment"),
        # ex-vivo (patient-derived organoid) dependency reproduction — DepMap 3D CRISPR. BORROWED from
        # the dependency axis, read here as translational validation-readiness. The indication-matched
        # organoid_lineage_frac_dependent is the strongest translational read; the pan-organoid
        # frac_dependent + class are the fallback when the indication has no mapped organoid lineage.
        "organoid_dependency_class":       get_card_field(cards, "organoid-crispr-dependency",
                                              "organoid_dependency_class"),
        "organoid_frac_dependent":         get_card_field(cards, "organoid-crispr-dependency",
                                              "frac_dependent"),
        "organoid_lineage":                get_card_field(cards, "organoid-crispr-dependency",
                                              "organoid_lineage"),
        "organoid_lineage_frac_dependent": get_card_field(cards, "organoid-crispr-dependency",
                                              "organoid_lineage_frac_dependent"),
        "organoid_lineage_class":          get_card_field(cards, "organoid-crispr-dependency",
                                              "organoid_lineage_class"),
        # thin-cohort reliability caveat on the indication-matched per-lineage read (see the module note):
        # organoid_lineage_class computed over a lineage cohort below the organoid card's own
        # min_organoid_models=20 floor (e.g. Prostate n=9, Breast n=16) is a low-confidence read.
        "organoid_lineage_n_screened":     organoid_lineage_n_screened,
        "organoid_lineage_small_cohort":   (organoid_lineage_n_screened is not None
                                            and organoid_lineage_n_screened < _ORGANOID_LINEAGE_MIN_MODELS),
    }


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="intracellular_intrinsic",   # rules axis for loading; translational-readiness emits no verdict
        question=QUESTION,
        verdict_fn=None,                   # DESCRIPTIVE — model availability is translational context, not a gate
        headline_fn=_headline,
        partial_status_note=PARTIAL_STATUS_NOTE,
    ))
