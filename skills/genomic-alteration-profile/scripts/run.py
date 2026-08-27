#!/usr/bin/env python3
"""genomic-alteration-profile — how is a (target, indication) genomically altered?

Answers: "How is gene X altered in indication Y, and which alteration class drives —
SNV/indel (mutation), copy-number (amplification/deletion), or fusion/rearrangement?"
A gene is often a driver via DIFFERENT classes across indications (ERBB2 amplified in
breast/gastric vs mutated in a lung subset; MET exon14-skip + amplification), so this
skill reports the alteration MIX and names which class carries the signal, rather than
implying "not a driver" for an amplification- or fusion-driven target.

Structure:
  - A whole-cohort spine of CARDS drives the deterministic multi-class verdict, resolved
    by the shared declarative resolver (resolvers/genomic_alteration.resolver.yaml).
  - An optional, --subtypes-gated subtype panorama (SUBTYPE_CARDS) is DESCRIPTIVE only: it
    recomputes frequency within each stratum and never touches a resolver rung, so the
    verdict is byte-identical whether or not --subtypes is passed.
  - An optional --synthesize flag attaches an LLM narration as a sibling key; it can never
    alter the deterministic verdict.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common import (
    resolve_cards, fired_rules, modality_lens,
    make_decision_json, write_package, card_summary,
)
from _skills_common.resolver import resolve_or_raise
from _skills_common.claim_record import assemble_claim_record
# The family-wise FDR across the stratified-dependency classes is single-sourced in
# _skills_common.card_preprocessors so all three resolution paths apply it identically:
# this skill's main(), the target-profile fan-out, and compose-dashboard's gate spine.
# apply_family_wise_fdr is used by main(); _bh_qvalues is re-exported for this skill's tests.
from _skills_common.card_preprocessors import (  # noqa: F401
    apply_family_wise_fdr as _apply_family_wise_fdr, _bh_qvalues,
)
from _skills_common.genomic_claims import genomic_claim_vector, genomic_key_signals
from _skills_common.genomic_question_table import genomic_question_table
from _skills_common.subgroup_derivation import make_value_classifier, subgroup_signals_for

# ─── Signals-first sub-group reader (verdict-INERT) ──────────────────────────────────────────────
# This skill hand-rolls main() (no run_wired_skill), so it wires the fleet sub-group derivation itself
# (see _headline). The fleet-default heuristic is lens-blind — it tags this lens's POSITIVE signals
# (direct_driver_gof, likely_oncogenic, predominantly_clonal, concordant_dependent, top_1pct recurrence)
# as `absent`. _GENOMIC_VALUE_TIERS states the tier for the alteration vocabulary (signal = strength of
# evidence that the target IS genomically altered / the class drives). default_classify is the fallback.
_GENOMIC_VALUE_TIERS = {
    # driver role / recurrence / oncogenicity / pathway
    "direct_driver_gof": "strong", "direct_driver_lof": "strong", "likely_driver": "moderate",
    "passenger": "absent", "no_established_role": "absent",
    "top_1pct": "strong", "top_5pct": "strong", "top_decile": "moderate", "recurrent": "strong",
    "frequently_altered": "strong", "occasionally_altered": "moderate", "rarely_altered": "weak",
    "likely_oncogenic": "strong", "oncogenic": "strong", "likely_benign": "absent", "benign": "absent",
    # mutation type / clonality / functional state
    "missense": "moderate", "truncating": "strong", "inframe": "moderate", "silent": "absent",
    "predominantly_clonal": "strong", "subclonal": "moderate",
    "biallelic_inactivation": "strong", "sporadic_biallelic_inactivation": "moderate",
    "functionally_abnormal": "strong", "mave_unmapped_target": "absent",
    # mutation/CN/fusion-stratified dependency + drug response + cross-consortium
    "mutant_strongly_dependent": "strong", "mutant_moderately_dependent": "moderate",
    "mutant_strongly_drug_sensitive": "strong", "mutant_moderately_drug_sensitive": "moderate",
    "concordant_dependent": "strong", "own_mut_hotspot": "moderate",
    "broadly_neutral": "absent", "recurrently_amplified": "strong", "recurrently_deleted": "strong",
    "amplified_moderately_dependent": "moderate", "amplified_strongly_dependent": "strong",
    "amplified_overexpressed_moderately_dependent": "moderate",
    "amplified_overexpressed_strongly_dependent": "strong",
    "fusion_positive_moderately_dependent": "moderate", "fusion_positive_strongly_dependent": "strong",
    "no_recurrent_fusion": "absent", "tumor_shifted": "moderate", "no_splice_shift": "absent",
}
from _skills_common.headline_core import build_headline, HeadlineSpec
from _skills_common.headline_hero import emit_headline_hero

SKILL_NAME = "genomic-alteration-profile"
SKILL_VERSION = "2.9.0"   # 2.9.0 (2026-08-27): wire signals-first sub-group signals (hand-rolled main bypassed
                          #        the fleet wiring) + tuned alteration value→tier map. Verdict-INERT.

# Whole-cohort cards read on every run. The verdict is driven by the resolver (see _verdict);
# cards tagged "verdict-driving" fire rules the resolver references, "signal-only" cards feed
# the headline / LLM / matrix but touch no resolver rung (the verdict spine stays byte-stable).
CARDS = [
    # ── SNV / indel ──────────────────────────────────────────────────────────
    "mutation-type-counts",            # verdict-driving: variant-class landscape (missense/truncating mix)
    "mutation-stratified-dependency",  # verdict-driving: are mutant cell lines more Chronos-dependent?
    "mutation-hotspot-frequency",      # verdict-driving (Phase 2): pooled top_1pct patient recurrence → recurrent_snv_driver

    # ── Copy number (amplification / deletion) ───────────────────────────────
    "copy-number-distribution",           # verdict-driving: focal amp/deletion recurrence
    "copy-number-stratified-dependency",  # verdict-driving: are AMPLIFIED lines more dependent? (ERBB2/MYC)
    "amp-expr-stratified-dependency",     # verdict-driving: amplified AND high-expression conjoint dependency

    # ── Fusion / rearrangement ───────────────────────────────────────────────
    "fusion-stratified-dependency",    # verdict-driving: are fusion-positive lines more dependent? (EWSR1-FLI1)
    "fusion-rearrangement-landscape",  # verdict-driving: recurrent TCGA fusion driver (tcga-fusion-consensus-v1)

    # ── Genotype × drug response ─────────────────────────────────────────────
    "mutation-drug-response",          # verdict-driving (STRONG class only): mutant lines more drug-sensitive (PRISM)

    # ── Typed driver ROLE ────────────────────────────────────────────────────
    "alteration-role",                 # verdict-driving: OncoKB × IntOGen GoF/LoF role → confirmed_driver rungs

    # ── Additive signal-only layers (feed the headline/LLM; touch no resolver rung) ──
    "functional-gene-state",           # biallelic two-hit / allele-count state (mutation + allele-specific CN)
    "genomic-event-model-match",       # which DepMap models carry the SAME event as the tumours, and are dependent
    "genomic-instability-state",       # indication-level aneuploidy / CIN / WGD / MSI cohort context (target-independent)
    "mutational-signature-context",    # indication-level mutagenic-process context (TCGA MC3 SBS signatures)
    "ddr-deficiency-context",          # indication-level DDR/HRD cohort context (frames the HRD-conditional axis)
    "oncogenic-pathway-alteration",    # indication-level oncogenic-pathway alteration frequency (Sanchez-Vega 2018)
    "variant-level-interpretation",    # per-variant oncogenicity + therapy-resistance alleles (CIViC clinical interp)
    "variant-effect-mave-mavedb",      # per-variant MEASURED functional effect (MAVEdb DMS/SGE); orthogonal to CIViC (verdict-inert)
    "target-clonality",                # is the driver mutation truncal (durable) or subclonal (relapse-prone)?
    # ── Q4 KO-dependency CONFIDENCE annotations (additive, verdict-inert; fire NO genomic rung) ──
    "cross-consortium-dependency",     # Broad↔Sanger CRISPR agreement — is the dependency reproducible?
    "dependency-predictability",       # is the dependency omics-learnable, and is it lineage-collapsed?
                                       # (predictability_lineage_collapsed directly flags the pan-cancer-vs-
                                       # indication scope-leak the biomarker rungs are gated against)

    # ── SPLICE-form facets (2) — VERDICT-INERT display (2026-08-20) ────────────────────
    # Aberrant splicing as a transcript-form alteration signal, homed alongside the SNV/CN/fusion
    # classes as DISPLAY facets (fire NO rule → the multi-class genomic verdict spine is byte-stable;
    # graduating splice to a verdict-driving class is a later rules+resolver stage). Previously
    # orphaned (consumed by no skill). TCGA SpliceSeq PSI (indication-gated).
    "tumor-splice-dysregulation",      # splice-dysregulation event(s) at the target (PSI shift vs normal)
    "tumor-splice-expression",         # per-splice-form expression (patient-tumor arm)
]

# The subtype panorama is DELIBERATELY kept off the CARDS spine. Its card is a panorama
# dispatcher that needs externally-resolved strata (subgroup_context.resolved_strata_ids) or
# it returns only a data-note — so it resolves on a separate, --subtypes-gated path (see
# _resolve_subtype_panorama). It is DESCRIPTIVE (per-stratum frequency), emits no verdict, and
# touches no resolver rung, so the whole-cohort verdict is byte-stable whether or not a subtype
# scope is passed.
SUBTYPE_CARDS = [
    "subgroup-stratified-mutation-frequency",   # SNV frequency by molecular subgroup
    "subgroup-stratified-copy-number",          # patient focal amp/del by subgroup (TCGA GISTIC per-sample)
    "subgroup-stratified-fusion",               # fusion recurrence by subgroup (usually underpowered per stratum)
]

# Per-axis subtype-panorama config: (card_id, headline_axis_key, cross-stratum delta field, display
# pattern key, delta threshold). The mutation axis keeps its original keys for backward-compatibility;
# the CN + fusion axes are the scope-coherence Phase 3 broadening (descriptive, verdict-inert).
_SUBTYPE_AXES = [
    ("subgroup-stratified-mutation-frequency", "subtype_axis",        "cross_subgroup_delta_frequency",          "subtype_mutation_pattern", 0.10),
    ("subgroup-stratified-copy-number",        "subtype_cn_axis",     "cross_subgroup_delta_high_amp_fraction",  "subtype_cn_pattern",       0.10),
    ("subgroup-stratified-fusion",             "subtype_fusion_axis", "cross_subgroup_delta_fusion_frequency",   "subtype_fusion_pattern",   0.05),
]

QUESTION = ("How is {target} genomically altered in {indication} — by SNV/indel "
            "(driver, biomarker-stratified dependency, or passenger), by copy-"
            "number (amplification/deletion), or a mix — and which class drives?")

# Cross-subgroup frequency delta at/above which the DESCRIPTIVE subtype panorama is flavored
# "subgroup-specific" (below it, with >=2 measured strata, "uniform"). Mirrors the
# subgroup-stratified-mutation-frequency card's own threshold; display-only, never a verdict input.
_SUBTYPE_DELTA_THRESHOLD = 0.10


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Multi-class genomic-alteration verdict, delegated to the shared declarative resolver.

    The verdict logic (SNV/indel priority × copy-number × fusion, precedence by effect
    strength then class) lives in resolvers/genomic_alteration.resolver.yaml (target-contracts),
    evaluated by the single interpreter every engine calls. A missing spec raises rather than
    falling back to a stale copy, so the two engines can never silently drift.
    """
    return resolve_or_raise(fired, "genomic_alteration")


# Per-alteration-class decomposition. The collapsed genomic_alteration verdict fuses SNV/indel,
# copy-number, and fusion into one multi_class scalar; this map reorganizes the ALREADY-computed
# per-card class fields into a first-class per-class breakdown (mirroring tumor-presence's
# presence_verdict_by_modality) so a consumer can see WHICH class carries the signal. It reuses
# fields already read for the headline and touches no resolver rung — the verdict stays byte-stable.
#   class -> (primary "verdict" field, {supporting_field_name: (card_id, field)})
_ALTERATION_CLASS_FIELDS: dict[str, tuple] = {
    "snv_indel": (
        ("mutation-type-counts", "mutation_landscape_class"),
        {"recurrence_class": ("mutation-hotspot-frequency", "driver_recurrence_class"),
         "stratified_dependency_class": ("mutation-stratified-dependency", "mutation_stratification_class")},
    ),
    "copy_number": (
        ("copy-number-distribution", "copy_number_class"),
        {"patient_class": ("copy-number-distribution", "patient_copy_number_class"),
         "stratified_dependency_class": ("copy-number-stratified-dependency", "cn_stratification_class"),
         "amp_expr_dependency_class": ("amp-expr-stratified-dependency", "amp_expr_stratification_class")},
    ),
    "fusion": (
        ("fusion-rearrangement-landscape", "fusion_class"),
        {"stratified_dependency_class": ("fusion-stratified-dependency", "fusion_stratification_class"),
         "genie_sv_recurrence_class": ("fusion-rearrangement-landscape", "genie_sv_recurrence_class")},
    ),
}


def _genomic_alteration_by_class(cards: list[dict]) -> dict:
    """Per-alteration-class breakdown: {class: {verdict, evidence_state, <supporting fields>}}.

    `verdict` is that class's OWN primary card call (SNV landscape / CN distribution / fusion
    recurrence) — not re-derived, so it cannot drift from the cards. `evidence_state` is
    `measured` when the primary field resolved, else `data_unavailable` (a NAMED gap, never a
    fabricated negative).

    Unlike the headline lifts, an absent card_id falls back to None (a named data_unavailable gap)
    rather than raising — the by-class map is tolerant of a card that did not resolve this run.
    """
    card_by_id = {c.get("card_id"): c for c in (cards or [])}

    def _field(card_id, field):
        card = card_by_id.get(card_id)
        return (card.get("summary") or {}).get(field) if card is not None else None

    out: dict[str, dict] = {}
    for cls, (primary, supporting) in _ALTERATION_CLASS_FIELDS.items():
        pval = _field(*primary)
        entry = {
            "verdict": pval,
            "evidence_state": "data_unavailable" if pval in (None, "data_unavailable") else "measured",
        }
        for name, (card_id, field) in supporting.items():
            entry[name] = _field(card_id, field)
        out[cls] = entry
    return out


# ── Scope decomposition (pan-cancer / indication / subtype) ──────────────────────────────────────
# The genomic_alteration verdict is a SCOPE HYBRID: the ladder-LEADING KO-dependency, variant-class
# shape, and drug-response signals are pan-cancer DepMap/PRISM cell-line calls (localised to the queried
# lineage only when powered, via each stratified card's `evidence_scope`), while patient recurrence,
# patient-focal CN, TCGA fusion recurrence, and the IntOGen driver role are indication-native. The
# one-word verdict never says at what scope it was earned; `genomic_alteration_by_class` re-expands the
# alteration CLASS but not the SCOPE. This reducer classifies the SCOPE of the DRIVING verdict and rolls
# up which evidence exists at each scope — ADDITIVE / verdict-inert (mirrors _genomic_alteration_by_class;
# the functional-requirement dependency_verdict_by_scope analog). It reads fields already emitted by the
# cards and touches no resolver rung, so the verdict spine stays byte-stable.
#   driving_rule prefix -> the stratified-dependency card whose `evidence_scope` localises that rung.
_DEP_RULE_SCOPE_CARD: dict[str, str] = {
    "mutant-":          "mutation-stratified-dependency",
    "cn-amplified-":    "copy-number-stratified-dependency",
    "fusion-positive-": "fusion-stratified-dependency",
    "amp-expr-":        "amp-expr-stratified-dependency",
}
# `evidence_scope` values meaning the dependency was localised to the queried indication's lineage.
_INDICATION_EVIDENCE_SCOPES = {"within_indication", "within_indication_mut_vs_pan_wt"}
_PAN_EVIDENCE_SCOPES = {"pan_lineage_evidence_only", "pan_no_indication"}
# driving_rule ids whose signal is inherently indication-native (patient tissue) ...
_INDICATION_ANCHORED_RULES = {
    "cn-patient-focal-amplified-supportive", "cn-patient-focal-deleted-supportive",
    "fusion-landscape-recurrent-driver-supportive",
    "snv-recurrence-top-driver-supportive",   # Phase 2 (pooled patient recurrence) — forward-compat
}
# ... vs pan-cancer cell-line landscape / variant-shape / pharmacology rungs.
_PAN_CANCER_RULES = {
    "cn-recurrently-amplified-supportive", "cn-recurrently-deleted-supportive",
    "mutation-drug-response-strongly-sensitive-supportive",
    "mut-lof-dominant-supportive", "mut-missense-dominant-supportive",
}


def _scope_of_driving_verdict(card_by_id: dict, driving_rule: str | None) -> str:
    """Classify the SCOPE at which the deterministic verdict was earned, from `driving_rule_id` + the
    driving card's own scope field. One of:
      - `indication_anchored`      — driving signal is within the queried indication's lineage/tissue
      - `pan_cancer_extrapolation` — driving signal is a pan-cancer/pan-lineage cell-line call
      - `mixed`                    — pan-cancer driving signal WITH indication-native corroboration
      - `not_applicable`           — no verdict fired
      - `unclassified`             — driving rule not mapped (defensive)
    A dependency rung reads its card's `evidence_scope`; landscape/shape/pharmacology rungs are statically
    indication-native vs pan-cancer. Verdict-inert (never feeds a resolver rung)."""
    if not driving_rule:
        return "not_applicable"

    def _f(card_id, field):
        return (card_by_id.get(card_id, {}).get("summary") or {}).get(field)

    def _indication_native_support() -> bool:
        return (_f("alteration-role", "intogen_scope") == "indication"
                or _f("mutation-hotspot-frequency", "driver_recurrence_class") in ("top_1pct", "top_decile")
                or _f("copy-number-distribution", "patient_focal_cn_class")
                in ("recurrent_focal_amplification", "recurrent_focal_deletion")
                or _f("fusion-rearrangement-landscape", "fusion_class") == "recurrent_fusion_driver")

    for prefix, card_id in _DEP_RULE_SCOPE_CARD.items():
        if driving_rule.startswith(prefix):
            scope = _f(card_id, "evidence_scope")
            if scope in _INDICATION_EVIDENCE_SCOPES:
                return "indication_anchored"
            if scope in _PAN_EVIDENCE_SCOPES:
                return "mixed" if _indication_native_support() else "pan_cancer_extrapolation"
            return "unclassified"
    if driving_rule in _INDICATION_ANCHORED_RULES:
        return "indication_anchored"
    if driving_rule in _PAN_CANCER_RULES:
        return "mixed" if _indication_native_support() else "pan_cancer_extrapolation"
    return "unclassified"


def _genomic_alteration_by_scope(cards: list[dict], driving_rule: str | None) -> dict:
    """Per-SCOPE breakdown: `{scope_of_driving_verdict, pan_cancer, indication, subtype}`.

    `scope_of_driving_verdict` is the load-bearing scalar (see _scope_of_driving_verdict). Each scope
    block lists the evidence that exists AT that scope plus an `evidence_present` flag, so a consumer can
    see indication-native corroboration even when a pan-cancer signal drove the verdict. The `subtype`
    block is a placeholder unless --subtypes was passed (main() patches it in); the whole-cohort spine is
    never subtype-scoped, so leaving it empty keeps the verdict byte-stable. Additive / verdict-inert."""
    card_by_id = {c.get("card_id"): c for c in (cards or [])}

    def f(card_id, field):
        return (card_by_id.get(card_id, {}).get("summary") or {}).get(field)

    def _measured(v):
        return v not in (None, "", "data_unavailable")

    # PAN-CANCER (DepMap/PRISM cell-line) — the ladder-leading dependency + variant-shape + drug-response,
    # each dependency carrying its own indication-localisation scope.
    pan = {
        "mutation_landscape_class":  f("mutation-type-counts", "mutation_landscape_class"),
        "copy_number_class":         f("copy-number-distribution", "copy_number_class"),
        "mutation_dependency_class": f("mutation-stratified-dependency", "mutation_stratification_class"),
        "mutation_dependency_scope": f("mutation-stratified-dependency", "evidence_scope"),
        "cn_dependency_class":       f("copy-number-stratified-dependency", "cn_stratification_class"),
        "cn_dependency_scope":       f("copy-number-stratified-dependency", "evidence_scope"),
        "fusion_dependency_class":   f("fusion-stratified-dependency", "fusion_stratification_class"),
        "fusion_dependency_scope":   f("fusion-stratified-dependency", "evidence_scope"),
        "amp_expr_dependency_class": f("amp-expr-stratified-dependency", "amp_expr_stratification_class"),
        "amp_expr_dependency_scope": f("amp-expr-stratified-dependency", "evidence_scope"),
        "drug_response_class":       f("mutation-drug-response", "drug_response_stratification_class"),
    }
    _pan_signal = ("mutation_landscape_class", "copy_number_class", "mutation_dependency_class",
                   "cn_dependency_class", "fusion_dependency_class", "amp_expr_dependency_class",
                   "drug_response_class")
    # INDICATION (patient tissue) — recurrence, patient-focal CN, TCGA fusion, IntOGen role, clonality.
    ind = {
        "pooled_driver_recurrence_class": f("mutation-hotspot-frequency", "pooled_driver_recurrence_class"),
        "driver_recurrence_class":       f("mutation-hotspot-frequency", "driver_recurrence_class"),
        "genie_driver_recurrence_class": f("mutation-hotspot-frequency", "genie_driver_recurrence_class"),
        "patient_focal_cn_class":        f("copy-number-distribution", "patient_focal_cn_class"),
        "fusion_class":                  f("fusion-rearrangement-landscape", "fusion_class"),
        "alteration_role":               f("alteration-role", "alteration_role"),
        "intogen_scope":                 f("alteration-role", "intogen_scope"),
        "clonality_class":               f("target-clonality", "clonality_class"),
    }
    _ind_signal = ("pooled_driver_recurrence_class", "driver_recurrence_class", "genie_driver_recurrence_class",
                   "patient_focal_cn_class", "fusion_class", "alteration_role")
    return {
        "scope_of_driving_verdict": _scope_of_driving_verdict(card_by_id, driving_rule),
        "pan_cancer":  {"evidence_present": any(_measured(pan[k]) for k in _pan_signal), **pan},
        "indication":  {"evidence_present": any(_measured(ind[k]) for k in _ind_signal), **ind},
        # subtype: patched by main() only when --subtypes is passed (byte-stable otherwise).
        "subtype":     {"evidence_present": False, "note": "pass --subtypes to populate the subtype panorama"},
    }


# Headline field table: (headline_key, card_id, summary_field). Every entry is a plain lift of a
# card summary field via _lift_field; keeping them declarative removes ~40 near-identical call
# sites and makes the mutation / copy-number / fusion / role / cohort-context axes scannable at a
# glance. All CARDS are always present in the resolved list, so no lookup here can raise.
_HEADLINE_FIELDS: list[tuple[str, str, str]] = [
    # ── SNV / indel axis ─────────────────────────────────────────────────────
    ("mutation_landscape_class",            "mutation-type-counts",           "mutation_landscape_class"),
    ("mutation_stratification_class",       "mutation-stratified-dependency", "mutation_stratification_class"),
    # Scope at which the stratified-dependency call was made (within-indication vs a pan-cancer
    # extrapolation), plus flags for a within-vs-pan disagreement and a pan-fallback strong→moderate cap.
    ("stratified_evidence_scope",           "mutation-stratified-dependency", "evidence_scope"),
    ("stratified_lineage_context_divergent","mutation-stratified-dependency", "lineage_context_divergent"),
    ("stratified_pan_fallback_capped",      "mutation-stratified-dependency", "pan_fallback_strong_capped_to_moderate"),
    # Pharmacological biomarker: genotype → on-target drug response (PRISM), complementing the CRISPR-KO
    # stratified dependency above.
    ("drug_response_stratification_class",  "mutation-drug-response",         "drug_response_stratification_class"),
    ("drug_response_delta_log2auc",         "mutation-drug-response",         "delta_log2auc_mut_vs_wt"),
    ("drug_response_n_on_target_compounds", "mutation-drug-response",         "n_on_target_compounds"),
    # Recurrence frequency + driver-recurrence percentile, from both WES (TCGA-MC3) and panel (GENIE).
    ("overall_mutation_frequency",          "mutation-hotspot-frequency",     "overall_mutation_frequency"),
    ("driver_recurrence_class",             "mutation-hotspot-frequency",     "driver_recurrence_class"),
    ("driver_recurrence_percentile",        "mutation-hotspot-frequency",     "driver_recurrence_percentile"),
    ("genie_driver_recurrence_class",       "mutation-hotspot-frequency",     "genie_driver_recurrence_class"),
    ("genie_mutation_frequency",            "mutation-hotspot-frequency",     "genie_mutation_frequency"),
    # POOLED multi-cohort recurrence (scope-coherence Phase 2) — VERDICT-DRIVING: top_1pct fires the
    # recurrent_snv_driver rung. TCGA-MC3 + GENIE + MSK-CHORD, summed-counts/summed-coverage.
    ("pooled_driver_recurrence_class",      "mutation-hotspot-frequency",     "pooled_driver_recurrence_class"),
    ("pooled_driver_recurrence_percentile", "mutation-hotspot-frequency",     "pooled_driver_recurrence_percentile"),
    ("pooled_mutation_frequency",           "mutation-hotspot-frequency",     "pooled_mutation_frequency"),
    ("pooled_recurrence_cohorts",           "mutation-hotspot-frequency",     "cohorts_contributing"),

    # ── Copy-number axis (cell-line verdict-driving + patient-tumour cross-check) ──
    ("copy_number_class",                   "copy-number-distribution",       "copy_number_class"),
    ("patient_copy_number_class",           "copy-number-distribution",       "patient_copy_number_class"),
    # Patient-tumour FOCAL CN (indication-native; the verdict-bearing +2/homdel gate, distinct from the
    # display-only any-gain patient_copy_number_class) — surfaced for genomic_alteration_by_scope.indication.
    ("patient_focal_cn_class",              "copy-number-distribution",       "patient_focal_cn_class"),
    ("cn_stratification_class",             "copy-number-stratified-dependency", "cn_stratification_class"),
    # Indication-localisation scope of each stratified-dependency sibling (mutation's is surfaced above as
    # stratified_evidence_scope) — the substrate for genomic_alteration_by_scope.scope_of_driving_verdict.
    ("cn_stratified_evidence_scope",        "copy-number-stratified-dependency", "evidence_scope"),
    ("fusion_stratification_class",         "fusion-stratified-dependency",   "fusion_stratification_class"),
    ("fusion_stratified_evidence_scope",    "fusion-stratified-dependency",   "evidence_scope"),
    ("amp_expr_stratification_class",       "amp-expr-stratified-dependency", "amp_expr_stratification_class"),
    ("amp_expr_stratified_evidence_scope",  "amp-expr-stratified-dependency", "evidence_scope"),

    # ── Fusion / rearrangement axis (TCGA consensus verdict + GENIE-SV breadth facet) ──
    ("fusion_class",                        "fusion-rearrangement-landscape", "fusion_class"),
    # Verdict-inert confidence tier on a recurrent_fusion_driver call: high_recurrent_partner (a
    # recurrent partner — reliable) vs moderate_promiscuous (target recurs, no recurrent partner — a
    # mixed bucket that also catches amplicon-artifact SVs at amplified oncogenes). Does not move the verdict.
    ("fusion_recurrence_confidence",        "fusion-rearrangement-landscape", "fusion_recurrence_confidence"),
    ("genie_sv_recurrence_class",           "fusion-rearrangement-landscape", "genie_sv_recurrence_class"),
    ("genie_sv_frequency",                  "fusion-rearrangement-landscape", "genie_sv_frequency"),
    ("genie_sv_recurrent_partners",         "fusion-rearrangement-landscape", "genie_sv_recurrent_partners"),

    # ── Typed driver role (OncoKB × IntOGen) ─────────────────────────────────
    ("alteration_role",                     "alteration-role",                "alteration_role"),
    ("functional_direction",                "alteration-role",                "functional_direction"),
    # IntOGen driver-call scope: indication (per-cancer-type) vs pan_cancer fallback — the indication
    # anchor for genomic_alteration_by_scope (a pan_cancer role is a weaker in-indication claim).
    ("intogen_scope",                       "alteration-role",                "intogen_scope"),

    # ── Additive signal-only axes ────────────────────────────────────────────
    ("functional_state_class",              "functional-gene-state",          "functional_state_class"),
    ("clonality_class",                     "target-clonality",               "clonality_class"),
    ("clonal_fraction",                     "target-clonality",               "clonal_fraction"),
    ("clonality_n_mutant_samples",          "target-clonality",               "n_mutant_samples"),
    ("event_correspondence_class",          "genomic-event-model-match",      "event_correspondence_class"),

    # ── Indication-level cohort context (target-independent) ─────────────────
    ("aneuploidy_burden_class",             "genomic-instability-state",      "aneuploidy_burden_class"),
    ("wgd_class",                           "genomic-instability-state",      "wgd_class"),
    ("msi_class",                           "genomic-instability-state",      "msi_class"),          # patient MSI (CRC+STAD)
    ("model_msi_class",                     "genomic-instability-state",      "model_msi_class"),    # model MSI (all lineages)
    ("ddr_context_class",                   "ddr-deficiency-context",         "ddr_context_class"),
    ("frac_hrd_high",                       "ddr-deficiency-context",         "frac_hrd_high"),
    ("dominant_mutational_process",         "mutational-signature-context",   "dominant_process"),   # patient SBS
    ("enriched_mutational_processes",       "mutational-signature-context",   "enriched_processes"),
    ("model_mmr_signature_class",           "genomic-instability-state",      "model_mmr_signature_class"),

    # ── Per-variant interpretation (CIViC) ───────────────────────────────────
    ("civic_variant_class",                 "variant-level-interpretation",   "civic_variant_class"),
    ("civic_oncogenic_variants",            "variant-level-interpretation",   "oncogenic_variants"),
    ("civic_resistance_variants",           "variant-level-interpretation",   "resistance_variants"),

    # ── Per-variant MEASURED functional effect (MAVEdb DMS/SGE; verdict-inert) ─
    ("mave_evidence_class",                 "variant-effect-mave-mavedb",     "mave_evidence_class"),
    ("mave_n_score_sets",                   "variant-effect-mave-mavedb",     "n_score_sets"),
    ("mave_score_median",                   "variant-effect-mave-mavedb",     "score_median"),

    # ── Q4 dependency CONFIDENCE (additive, verdict-inert) ────────────────────
    ("cross_consortium_class",              "cross-consortium-dependency",    "cross_consortium_class"),
    ("dependency_predictability_class",     "dependency-predictability",      "predictability_class"),
    ("dependency_predictability_feature",   "dependency-predictability",      "pred_dominant_feature_class"),
]


def _panorama_axis(card: dict | None, delta_field: str, pattern_key: str, threshold: float) -> dict:
    """Compact DISPLAY projection of one subtype-panorama card, mirroring the card's own thresholds
    (delta >= threshold → subgroup-specific; below with >=2 measured strata → uniform; else
    not-informative). Never a verdict; touches no resolver rung. `delta_field` is the card's own
    cross-stratum reducer scalar (frequency / high_amp_fraction / fusion_frequency)."""
    summary = (card or {}).get("summary") or {}
    per_subgroup = summary.get("per_subgroup_metrics") or []
    measured = [r for r in per_subgroup if r.get("evidence_state") == "measured"]
    delta = summary.get(delta_field)
    if len(measured) < 2 or delta is None:
        pattern = "not_informative"
    elif delta >= threshold:
        pattern = "subgroup_specific_pattern"
    else:
        pattern = "uniform_across_subgroups"
    label = delta_field.replace("cross_subgroup_delta_", "")     # e.g. frequency / high_amp_fraction
    return {
        pattern_key:              pattern,          # display-only flavor, NOT a verdict
        "n_subgroups_with_data":  summary.get("n_subgroups_with_data"),
        f"max_subgroup_{label}":  summary.get(f"max_subgroup_{label}"),
        f"min_subgroup_{label}":  summary.get(f"min_subgroup_{label}"),
        delta_field:              delta,
        "measured_strata":        [r.get("stratum") for r in measured],
        "_missing":               bool(card is None or card.get("_missing")),
        "_missing_reason":        (card or {}).get("_missing_reason"),
    }


def _resolve_subtype_panorama(target: str, indication: str,
                              subtypes: list[str]) -> dict:
    """DESCRIPTIVE subtype panoramas — resolve the three subgroup-stratified cards (SNV frequency,
    copy-number, fusion) across the requested strata. Each card is a panorama dispatcher that needs
    subgroup_context.resolved_strata_ids threaded (which is why they are off the whole-cohort CARDS
    list). Returns one compact per-axis projection per card for the headline — never a verdict, and
    none touches a resolver rung, so the whole-cohort verdict spine is byte-stable whether or not
    --subtypes is passed. The SNV axis keeps its original `subtype_axis` keys (backward-compatible);
    CN + fusion are the Phase 3 broadening.
    """
    subgroup_context = {"resolved_strata_ids": list(subtypes),
                        "catalog_status": "resolved_active"}
    sub_cards = resolve_cards(SUBTYPE_CARDS, target, indication,
                              subgroup_context=subgroup_context)
    by_id = {c["card_id"]: c for c in sub_cards}
    out: dict = {"cards": sub_cards, "scope_subtypes": list(subtypes), "axes": {}}
    for card_id, axis_key, delta_field, pattern_key, threshold in _SUBTYPE_AXES:
        out["axes"][axis_key] = _panorama_axis(by_id.get(card_id), delta_field, pattern_key, threshold)
    return out


def _lift_field(card_by_id: dict, card_id: str, field: str):
    """Prebuilt-index equivalent of get_card_field: same raise-on-unknown-card_id typo-guard and
    `summary.get(field)` semantics, but reuses one index so _build_headline does ~50 lifts against
    a single dict instead of rebuilding it per call. All _HEADLINE_FIELDS cards are always present."""
    if card_id not in card_by_id:
        raise KeyError(f"_lift_field: card_id {card_id!r} not found "
                       f"(available: {sorted(card_by_id)}). Check for a typo in the caller.")
    return (card_by_id[card_id].get("summary") or {}).get(field)


# ── canonical HEADLINE block (verdict + confidence + top tension) ────────────────────────────────
# The genomic declaration for the shared headline_core builder: the SNV/CN/FUS/DEP claim axes (the
# fourth concrete claim_vector_core instance — see _skills_common/genomic_claims.py), the multi-class
# genomic_alteration verdict vocabulary → human phrase, and the scope-leak (`pan_cancer_extrapolation`)
# as the skill-specific cross-class tension source. Verdict-INERT — a one-way projection over the
# already-computed headline (the genomic_alteration_profile spine stays byte-stable).
# The genomic_alteration verdict vocabulary (resolvers/genomic_alteration.resolver.yaml, target-contracts)
# → human phrase. Positives = the driver / dependency / recurrent-landscape rungs; negatives =
# passenger_pattern; the rest (mixed_pattern, insufficient) are neutral (gap / inconclusive).
_GENOMIC_VERDICT_PHRASE = {
    # biomarker-stratified dependency (the actionability "so what")
    "biomarker_stratified_dependency": "Biomarker-stratified genetic dependency",
    "moderate_biomarker_dependency":   "Moderate biomarker-stratified dependency",
    # driver calls
    "multi_class_driver":              "Multi-class alteration driver",
    "confirmed_driver":                "Confirmed driver",
    # LoF/tumor-suppressor drivers — a REAL driver alteration, but role-honest: not an
    # inhibitor/degrader green-light (you cannot drug a lost function). Neutral polarity.
    "multi_class_lof_driver":          "Multi-class loss-of-function (tumor-suppressor) driver",
    "confirmed_lof_driver":            "Confirmed loss-of-function (tumor-suppressor) driver",
    "drug_response_biomarker":         "Drug-response biomarker",
    # recurrent landscape drivers
    "recurrent_amplification_driver":  "Recurrent amplification driver",
    "recurrent_deletion_driver":       "Recurrent deletion driver",
    "recurrent_fusion_driver":         "Recurrent fusion driver",
    "recurrent_snv_driver":            "Recurrent SNV/indel driver",
    # variant-class spectrum shape
    "lof_dominant_pattern":            "LoF-dominant mutation pattern",
    "missense_dominant_pattern":       "Missense-dominant mutation pattern",
    # measured negative
    "passenger_pattern":               "Passenger (not a recurrent driver)",
    # gaps / inconclusive
    "mixed_pattern":                   "Mixed alteration pattern",
    "insufficient":                    "Insufficient evidence",
}

# The verdict tokens that are a POSITIVE alteration call (a driver / dependency / recurrent-landscape
# rung). passenger_pattern is the measured NEGATIVE; mixed_pattern + insufficient (+ anything unknown)
# are NEUTRAL. Sourced from the genomic_alteration resolver vocabulary so the polarity can't drift.
# NOTE (2026-08-24, PR-2a residual): lof_dominant_pattern / missense_dominant_pattern are mutation-SHAPE
# descriptors that fire ONLY when the alteration ROLE is unresolved (data_unavailable/passenger — a typed
# GoF/LoF role routes to confirmed_driver/confirmed_lof_driver instead). A shape-without-a-confirmed-role
# is NOT a positive driver call (it read oncogene-flavored 'positive' for CD47/TNKS), so they are NEUTRAL.
_GENOMIC_POSITIVE_VERDICTS = frozenset({
    "biomarker_stratified_dependency", "moderate_biomarker_dependency", "multi_class_driver",
    "confirmed_driver", "drug_response_biomarker", "recurrent_amplification_driver",
    "recurrent_deletion_driver", "recurrent_fusion_driver", "recurrent_snv_driver",
})
_GENOMIC_NEGATIVE_VERDICTS = frozenset({"passenger_pattern"})


def _genomic_verdict_polarity(v) -> str:
    """The skill's OWN reading of the collapsed multi-class verdict (colours the hero badge; never a
    gate). Genomic reports an alteration MIX — this is the polarity of the DOMINANT call. Reuses the
    resolver vocabulary so the polarity can't drift from the spine."""
    if v in _GENOMIC_POSITIVE_VERDICTS:
        return "positive"
    if v in _GENOMIC_NEGATIVE_VERDICTS:
        return "negative"
    return "neutral"


def _genomic_tension_extra(headline: dict):
    """The sharpest cross-class caveat: the verdict rests on a PAN-CANCER extrapolation (a pan-lineage
    cell-line dependency / spectrum call), not an in-indication signal — the scope leak the one-word
    verdict otherwise hides, surfaced by the existing genomic_alteration_by_scope decomposition."""
    scope = (headline.get("genomic_alteration_by_scope") or {}).get("scope_of_driving_verdict")
    if scope == "pan_cancer_extrapolation":
        return {"text": "verdict rests on a pan-cancer extrapolation, not an in-indication signal",
                "source": "genomic_alteration_by_scope.scope_of_driving_verdict", "severity": 3}
    return None


_GENOMIC_HEADLINE_SPEC = HeadlineSpec(
    gate="genomic_alteration",
    axis_labels={"SNV": "recurrent SNV/indel driver", "CN": "copy-number driver",
                 "FUS": "fusion driver", "DEP": "alteration confers dependency"},
    axis_keys=("SNV", "CN", "FUS", "DEP"),
    critical_axes=("SNV", "CN", "FUS", "DEP"),
    verdict_label=lambda v: _GENOMIC_VERDICT_PHRASE.get(v, str(v).replace("_", " ").strip().capitalize()),
    tension_extra=_genomic_tension_extra,
)


def _build_headline_block(headline: dict) -> dict:
    """Build the canonical Headline block from the already-computed genomic headline. Reads the
    collapsed multi-class verdict + the verdict-inert claim_vector / key_signals; never moves the spine.
    No certainty sidecar is emitted by this skill, so confidence derives from the claim_vector's
    corroboration (weakest-link, capped by conflict + coverage)."""
    v = headline.get("genomic_alteration_profile")
    return build_headline(headline, headline.get("claim_vector"), headline.get("key_signals"),
                          spec=_GENOMIC_HEADLINE_SPEC, verdict_token=v,
                          driving_rule_id=headline.get("driving_rule_id"),
                          verdict_polarity=_genomic_verdict_polarity(v))


def _build_headline(cards: list[dict], verdict: str, driving_rule: str | None,
                    fdr_provenance: dict) -> dict:
    """Assemble the deterministic headline: the computed verdict keys, every declarative field
    lift from _HEADLINE_FIELDS, then the card-availability roll-up."""
    card_by_id = {c["card_id"]: c for c in cards}
    headline: dict = {
        "genomic_alteration_profile":  verdict,
        "driving_rule_id":             driving_rule,
        # Per-alteration-class breakdown of the collapsed multi_class verdict (which class drives).
        "genomic_alteration_by_class": _genomic_alteration_by_class(cards),
        # Per-SCOPE breakdown + scope_of_driving_verdict: at what scope (pan-cancer / indication /
        # subtype) the collapsed verdict was earned. ADDITIVE / verdict-inert (subtype sub-block is
        # patched by main() only when --subtypes is passed).
        "genomic_alteration_by_scope": _genomic_alteration_by_scope(cards, driving_rule),
        # When >=2 stratified-dependency classes fired, their p-values were BH-corrected jointly and
        # any class with family-wise q >= 0.05 was demoted so a multi-class call is not over-credited.
        "stratified_family_wise_fdr":  fdr_provenance,
    }
    for key, card_id, field in _HEADLINE_FIELDS:
        headline[key] = _lift_field(card_by_id, card_id, field)
    headline["cards_available"] = sum(1 for c in cards if not c.get("_missing"))
    headline["cards_missing"]   = [c["card_id"] for c in cards if c.get("_missing")]
    # Additive, verdict-INERT: the claim vector (SNV/CN/FUS driver + DEP alteration-confers-dependency,
    # signal×corroboration) + a brief cited key-signals read — the WITHIN-lens integration this subskill
    # owns, built on the SHARED claim_vector_core contract (genomic-alteration is the fourth concrete
    # after presence + dependency + selectivity). Both PROJECT the headline just built (reusing
    # genomic_alteration_by_class as the single source of the per-class primaries); they NEVER touch the
    # genomic_alteration_profile spine (byte-stable). See _skills_common/genomic_claims.py.
    headline["claim_vector"] = genomic_claim_vector(headline, cards)
    headline["key_signals"] = genomic_key_signals(headline, cards)
    # Canonical HEADLINE block (verdict + confidence + top tension) — the concise, consumer-facing
    # headline message as deterministic text + a renderer-agnostic hero payload. A verdict-INERT
    # projection over the claim_vector / key_signals just built; best-effort so a formatting/read fault
    # in this display layer can NEVER discard the genomic spine already fully built in `headline` (same
    # degrade discipline tumor-presence applies). On the happy path this adds one key and no
    # _enrichment_errors, so the replay + golden-spine fixtures stay stable.
    try:
        headline["headline_block"] = _build_headline_block(headline)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        headline.setdefault("_enrichment_errors", {})["headline_block"] = f"{type(exc).__name__}: {exc}"
        headline["headline_block"] = None
    # The per-question (data · signal · confidence) LEADING table — a verdict-INERT projection over the
    # just-built headline + claim_vector (mirrors tumor-presence / tumor-selectivity). Carried through
    # _synthesis_facet so the composed target-profile dashboard renders the same table. Best-effort:
    # a formatting/read fault must NEVER discard the genomic spine already fully built in `headline`.
    try:
        headline["question_table"] = genomic_question_table(headline, cards)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        headline.setdefault("_enrichment_errors", {})["question_table"] = f"{type(exc).__name__}: {exc}"
        headline["question_table"] = None
    # Hierarchy-derived sub-group signals (signals-first). Wired HERE because this skill hand-rolls
    # main() and so bypasses the run_wired_skill fleet subgroup wiring; the tuned value→tier map gives
    # the alteration vocabulary correct polarity. Verdict-INERT, best-effort (never abort the spine).
    try:
        _sg = subgroup_signals_for(Path(__file__).resolve().parent.parent, cards,
                                   classify=make_value_classifier(_GENOMIC_VALUE_TIERS),
                                   claim_vector=headline.get("claim_vector"))
        if _sg:
            headline["subgroup_signals"] = _sg
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        headline.setdefault("_enrichment_errors", {})["subgroup_signals"] = f"{type(exc).__name__}: {exc}"
    return headline


# The uniform opt-in the target-profile fan-out looks for via getattr(module, "_synthesis_facet")
# (mirrors tumor-presence + functional-requirement). Lifts genomic-alteration's claim_vector (the
# SNV/CN/FUS driver + DEP alteration-confers-dependency SIGNAL decomposition) + key_signals to the
# composed synthesis, closing an arch-review gap (claim_vector was BUILT here but never surfaced to the
# cross-lens layer). This skill hand-rolls main() (no run_wired_skill), so the facet reconstructs the
# headline from the fan-out-resolved verdict_pair via _build_headline. VERDICT-INERT: nothing here
# enters `fired`/the resolver; the fan-out treats an absent/failed facet as no-facet.
_SYNTHESIS_FACET_KEYS = (
    "genomic_alteration_profile", "driving_rule_id",
    "genomic_alteration_by_class", "genomic_alteration_by_scope",
    "claim_vector", "key_signals",
    # the per-question (data·signal·confidence) rows — rendered as the leading table by target-profile too
    "question_table",
    # the canonical headline (verdict + confidence + top tension) — text + hero payload for every consumer
    "headline_block",
    # hierarchy-derived per-sub-group signals (SNV/CN/FUS/DEP; sources bound by measurement_type)
    "subgroup_signals",
)


# ── (strength, certainty) SIDECAR — 3rd certainty axis (CERTAINTY_MODEL.md). ADDITIVE + verdict-INERT:
#    computed beside the genomic verdict; never alters it. corroboration = the VERDICT-DISJOINT CIViC
#    per-variant oncogenicity (variant-level-interpretation.civic_variant_class — an independent curated
#    source confirming the driver claim; fires no resolver rung). Reviewed per-axis design (4-agent panel).
_GA_ORD = {"low": 0, "medium": 1, "high": 2}
_CERTAINTY_CORROBORATION_CARDS = frozenset({"variant-level-interpretation"})
_GA_STRONG_POS = {"biomarker_stratified_dependency", "multi_class_driver", "multi_class_lof_driver"}
_GA_MOD_POS = {"moderate_biomarker_dependency", "confirmed_driver", "confirmed_lof_driver",
               "drug_response_biomarker", "recurrent_amplification_driver", "recurrent_deletion_driver",
               "recurrent_fusion_driver", "recurrent_snv_driver"}
_GA_WEAK_POS = {"lof_dominant_pattern", "missense_dominant_pattern"}
_GA_NEG = {"passenger_pattern"}
_GA_NEUTRAL = {"mixed_pattern"}
_GA_NONE = {"insufficient", "data_unavailable", None}
_GA_DECISION_CARDS = ("mutation-type-counts", "mutation-stratified-dependency", "mutation-hotspot-frequency",
                      "copy-number-distribution", "copy-number-stratified-dependency",
                      "amp-expr-stratified-dependency", "fusion-stratified-dependency",
                      "fusion-rearrangement-landscape", "mutation-drug-response", "alteration-role")
# cards carrying a driving-class sample-count, tried in order (dependency-stratified n first, then the
# mutation spectrum / CN landscape n) — coverage = the driving class's power.
_GA_COVERAGE_N_CARDS = (("mutation-stratified-dependency", "n_cell_lines_evaluated"),
                        ("copy-number-stratified-dependency", "n_cell_lines_evaluated"),
                        ("fusion-stratified-dependency", "n_cell_lines_evaluated"),
                        ("amp-expr-stratified-dependency", "n_cell_lines_evaluated"),
                        ("mutation-type-counts", "mut_n_cell_lines_total"),
                        ("copy-number-distribution", "cn_n_cell_lines_evaluated"))


def _genomic_strength(v) -> str:
    if v in _GA_STRONG_POS:
        return "strong_positive"
    if v in _GA_MOD_POS:
        return "moderate_positive"
    if v in _GA_WEAK_POS:
        return "weak_positive"
    if v in _GA_NEG:
        return "negative"
    if v in _GA_NEUTRAL:
        return "neutral"
    return "none"


def _ga_coverage(cards) -> str:
    for cid, field in _GA_COVERAGE_N_CARDS:
        n = (card_summary(cards, cid) or {}).get(field)
        if isinstance(n, (int, float)):
            return "high" if n >= 20 else ("medium" if n >= 5 else "low")
    return "low"


def _ga_corroboration(civic_class) -> str:
    c = str(civic_class or "")
    if c == "oncogenic":
        return "high"
    if c == "likely_oncogenic":
        return "medium"
    if c in {"vus", "benign", "likely_benign"}:   # set literal (NOT a 3-tuple) — avoids the composer
        return "low"                              # card-read scanner misreading a value tuple as a card_id
    return "unmeasured"     # gene uncurated in CIViC → ignorance, carried in unknown_mass


def _ga_unknown_mass(cards) -> float:
    blind = 0
    for cid in _GA_DECISION_CARDS:
        s = card_summary(cards, cid)
        if not s or s.get("_missing"):
            blind += 1
    return round(blind / len(_GA_DECISION_CARDS), 4)


def _strength_certainty(cards, fired=None, verdict_pair=None) -> dict:
    """Fan-out SIDECAR hook (CERTAINTY_MODEL) — mirrors functional-requirement/selectivity. Standalone."""
    v = verdict_pair[0] if verdict_pair else (_verdict(fired)[0] if fired is not None else None)
    civic = (card_summary(cards, "variant-level-interpretation") or {}).get("civic_variant_class")
    coverage = _ga_coverage(cards)
    corroboration = _ga_corroboration(civic)
    components = [coverage] + ([corroboration] if corroboration != "unmeasured" else [])
    level = min(components, key=lambda c: _GA_ORD[c]) if components else "low"
    if v in _GA_NONE:
        level = "low"
    from _skills_common.signals_first import certainty_composite
    strength = _genomic_strength(v)
    return {
        "strength": strength,
        "certainty": {"level": level, "coverage": coverage, "corroboration": corroboration,
                      "unknown_mass": _ga_unknown_mass(cards)},
        # continuous portfolio-ranking primitive (verdict-inert; a NAMED projection, not canonical)
        "composite": certainty_composite(strength, level),
        "composite_basis": ("certainty-discounted genomic-alteration strength = peak signal tier × "
                            "weakest-link certainty; a NAMED [0,1] portfolio-ranking projection, not a verdict"),
        "provenance": {"civic_variant_class": civic},
        "_model_ref": "CERTAINTY_MODEL.md#genomic_alteration",
    }


# ── FACTORED-RECORD SHADOW (M1) — the genomic per-axis builder. VERDICT-INERT: emitted into
#    decision.json.claim_record_shadow and consumed by NOTHING (goldens untouched). Maps the
#    genomic_alteration verdict token onto the factored record's axis-specific coordinates; the
#    shared assembler owns shape + the open-world invariant + provenance. Mirrors _strength_certainty.
_GA_ROLE = {  # driver-role from the verdict (LoF-family verdicts carry loss-of-function role)
    "confirmed_lof_driver": "LoF", "multi_class_lof_driver": "LoF", "lof_dominant_pattern": "LoF",
}
# strength label -> ordinal magnitude level (informational; the finding.magnitude coordinate)
_GA_STRENGTH_TO_LEVEL = {
    "strong_positive": "strong", "moderate_positive": "moderate",
    "weak_positive": "weak", "negative": "moderate", "neutral": "weak", "none": "none",
}


def _ga_availability(v) -> str:
    """Map the genomic verdict to the availability TYPE. `data_unavailable` = open-world ignorance;
    `insufficient` = measured-but-underpowered; a passenger call is a measured NEGATIVE; a driver
    call is a measured POSITIVE."""
    if v == "data_unavailable" or v is None:
        return "not_wired"           # open-world → assembler forces state=unknown/direction=neutral
    if v == "insufficient":
        return "insufficient"
    if v in _GA_NEG:
        return "measured_negative"
    return "measured_positive"


def _ga_direction(v) -> str:
    if v in _GA_STRONG_POS or v in _GA_MOD_POS or v in _GA_WEAK_POS:
        return "supports"
    if v in _GA_NEG:
        return "opposes"
    return "neutral"


def _claim_record(cards, fired=None, verdict_pair=None) -> dict:
    """M1 shadow builder — standalone, mirrors _strength_certainty's call shape."""
    v, driving = (verdict_pair if verdict_pair else (_verdict(fired) if fired is not None else (None, None)))
    strength = _genomic_strength(v)
    sc = _strength_certainty(cards, fired=fired, verdict_pair=(v, driving))
    return assemble_claim_record(
        axis="genomic_alteration",
        state=(v or "insufficient"),
        direction=_ga_direction(v),
        availability=_ga_availability(v),
        magnitude={"level": _GA_STRENGTH_TO_LEVEL.get(strength, "none")},
        mechanism={"role": _GA_ROLE.get(v, "unknown")},
        certainty=sc["certainty"],
        fired=fired,
        cards=cards,
    )


def _synthesis_facet(cards, fired, verdict_pair):
    """Compact, VERDICT-INERT genomic-alteration facet for the composed synthesis prompt. Reconstructs
    the headline from the fan-out-resolved (verdict, driving_rule) via _build_headline (fdr provenance
    omitted — a within-run detail, not reconciliation-relevant) and returns claim_vector + key_signals +
    the per-class/per-scope breakdown. Never moves the verdict; safe to omit."""
    verdict, driving = verdict_pair if verdict_pair else (None, None)
    h = _build_headline(cards, verdict, driving, {})
    facet = {k: h.get(k) for k in _SYNTHESIS_FACET_KEYS}
    facet["_facet_note"] = (
        "Deterministic genomic-alteration facet (a FACET, not a gate; the multi-class genomic verdict is "
        "owned by the shared resolver and is verdict-inert to this projection). claim_vector is the "
        "SIGNAL decomposition — SNV / CN / FUS per-class driver + DEP alteration-confers-dependency, each "
        "a signal×corroboration tier; genomic_alteration_by_class/_by_scope name which class + at what "
        "scope the verdict was earned. The per-axis certainty roll-up is the separate certainty_by_axis sidecar.")
    return facet


def _llm_synthesis(cards, fired, verdict_pair, target, indication,
                   model_id=None, subtype=None):
    """Fan-out opt-in (mirrors _synthesis_facet): return the genomic-alteration lens's provenance-
    tagged llm_synthesis block for the COMPOSED target-profile run. Rebuilds the headline from the
    fan-out-resolved (verdict, driving_rule) via _build_headline (exactly as _synthesis_facet does),
    then narrates through the genomic synthesizer. Best-effort + VERDICT-INERT (the subtype arg is
    unused — genomic narrates whole-cohort; a failure is the caller's to swallow)."""
    from _skills_common.synthesis_genomic import synthesize_genomic_alteration
    verdict, driving = (verdict_pair or (None, None))
    headline = _build_headline(cards, verdict, driving, {})
    decision = {"target": target, "indication": indication, "headline": headline}
    return synthesize_genomic_alteration(decision, model_id)


def main() -> int:
    # PERF DEFAULT (2026-08-24): this skill HAND-ROLLS main() (it does not go through
    # run_wired_skill), so it never received the process-read-pool default that dispatcher.py sets
    # at the run_wired_skill entrypoint (see dispatcher.py: os.environ.setdefault("SKILLS_READ_POOL",
    # "process")). A standalone genomic-alteration CLI run reaches its 22 cards through resolve_cards
    # on the MAIN thread of a single-threaded process, where the forked read pool is both safe and the
    # fastest path (bypasses the GIL on the readers' pandas assembly — warm ERBB2/BRCA ~52s->~28s,
    # byte-identical output). Opt this entrypoint in unless the caller/env already chose a pool; scoped
    # HERE (not in resolve_cards) so the composed target-profile fan-out — which reads cards from
    # ThreadPoolExecutor worker threads — keeps the conservative thread default and never forks
    # unexpectedly. _read_cards_process still forks ONLY from a single-threaded main thread and degrades
    # to threads otherwise, so this is safe even here; escape hatch: SKILLS_READ_POOL=thread.
    import os
    os.environ.setdefault("SKILLS_READ_POOL", "process")
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--modality", default=None,
                    help="OPTIONAL post-hoc modality lens.")
    ap.add_argument("--subtypes", default=None,
                    help="OPTIONAL comma-separated molecular subtype/stratum ids "
                         "(e.g. 'MSI,MSS'). When set, resolves the DESCRIPTIVE "
                         "subgroup-stratified-mutation-frequency panorama across those strata. "
                         "Does NOT affect the whole-cohort verdict (byte-stable regardless).")
    ap.add_argument("--synthesize", action="store_true",
                    help="OPT-IN: attach an LLM narration of the deterministic verdict + alteration "
                         "mix + role + recurrence under decision['llm_synthesis']. NEVER alters the "
                         "verdict spine (the decision is byte-identical without this flag).")
    ap.add_argument("--synthesis-model", default=None,
                    help="Override the Bedrock synthesis model id (default: framework Opus).")
    args = ap.parse_args()

    cards = resolve_cards(CARDS, args.target, args.indication)
    # Correct the stratified-dependency family for multiplicity BEFORE firing rules. Mutates demoted
    # cards in place; no-op when <2 classes fire (so single-class calls stay byte-stable).
    fdr_provenance = _apply_family_wise_fdr(cards)
    fired = fired_rules(cards, axis="intracellular_intrinsic",
                        card_id_filter=CARDS)
    verdict, driving_rule = _verdict(fired)

    # Optional subtype panorama (DESCRIPTIVE, --subtypes-gated) — separate from the verdict spine.
    subtypes = [s.strip() for s in args.subtypes.split(",") if s.strip()] if args.subtypes else []
    subtype_result = _resolve_subtype_panorama(args.target, args.indication, subtypes) if subtypes else None

    headline = _build_headline(cards, verdict, driving_rule, fdr_provenance)

    # Subtype panorama (only present when --subtypes was passed): surfaced for the LLM/render, but
    # not a verdict input (spine byte-stable).
    if subtype_result is not None:
        headline["subtype_scope"] = subtype_result["scope_subtypes"]
        # One headline block per subtype axis (SNV / CN / fusion) — display-only, verdict-inert.
        axes = subtype_result["axes"]
        for axis_key, projection in axes.items():
            headline[axis_key] = projection
        # Reflect the subtype panoramas in the by-scope breakdown (still verdict-inert: descriptive, no
        # rung; the whole-cohort verdict is byte-stable regardless). evidence_present if ANY axis has data.
        _snv = axes.get("subtype_axis") or {}
        _any_data = any((ax.get("n_subgroups_with_data") or 0) >= 1 and not ax.get("_missing")
                        for ax in axes.values())
        headline["genomic_alteration_by_scope"]["subtype"] = {
            "evidence_present":               bool(_any_data),
            "subtype_mutation_pattern":       _snv.get("subtype_mutation_pattern"),
            "subtype_cn_pattern":             (axes.get("subtype_cn_axis") or {}).get("subtype_cn_pattern"),
            "subtype_fusion_pattern":         (axes.get("subtype_fusion_axis") or {}).get("subtype_fusion_pattern"),
            "n_subgroups_with_data":          _snv.get("n_subgroups_with_data"),
            "cross_subgroup_delta_frequency": _snv.get("cross_subgroup_delta_frequency"),
            "scope_subtypes":                 subtype_result["scope_subtypes"],
        }

    lenses = None
    invoked_lenses: dict = {}
    if args.modality:
        lenses = {args.modality: modality_lens(fired, args.modality)}
        invoked_lenses["modality"] = args.modality

    # The whole-cohort cards drive the verdict; the subtype panorama cards (if any) are appended to
    # the emitted package + LLM, but are NOT in `fired` — they touch no rung.
    emitted_cards = cards + (subtype_result["cards"] if subtype_result is not None else [])
    if subtype_result is not None:
        invoked_lenses["subtypes"] = subtype_result["scope_subtypes"]

    decision = make_decision_json(
        skill_name=SKILL_NAME,
        target=args.target, indication=args.indication,
        question=QUESTION.format(target=args.target, indication=args.indication),
        card_outputs=emitted_cards, fired=fired,
        headline=headline, modality_lenses=lenses,
    )

    # FACTORED-RECORD SHADOW (M1) — additive, verdict-INERT: emit the factored claim record beside
    # the legacy verdict spine, consumed by NOTHING. best-effort so a builder fault never breaks the
    # run (the decision.json verdict is already composed above). Whole-cohort cards drive the verdict,
    # so the shadow's provenance mirrors the whole-cohort `fired`/`cards` (not the subtype panorama).
    try:
        decision["claim_record_shadow"] = {"genomic_alteration": _claim_record(
            cards, fired=fired, verdict_pair=(verdict, driving_rule))}
    except Exception as e:  # noqa: BLE001 — shadow is non-authoritative; never break the spine
        decision["claim_record_shadow"] = {"_shadow_error": f"{type(e).__name__}: {e}"}

    # OPT-IN LLM synthesis. This skill hand-rolls main() (it does not use run_wired_skill), so it
    # narrates through the genomic-alteration lens here. Attached as a sibling key AFTER the
    # deterministic decision is composed, so it structurally cannot alter the verdict spine; a
    # synthesis failure (Bedrock auth/network) degrades to a note and never breaks the run.
    if args.synthesize:
        from _skills_common.synthesis_genomic import synthesize_genomic_alteration
        try:
            decision["llm_synthesis"] = synthesize_genomic_alteration(
                decision, args.synthesis_model)
        except Exception as e:  # noqa: BLE001 — synthesis is optional; never break the spine
            decision["llm_synthesis"] = {
                "_synthesis_error": f"{type(e).__name__}: {e}",
                "_note": "LLM synthesis unavailable; the deterministic verdict above is unaffected.",
            }

    # Canonical HEADLINE hero figure (figure_headline_hero.{svg,png,json}) — the one hero every skill
    # emits, rendered offline from decision['headline']['headline_block']. This skill hand-rolls main()
    # (no run_wired_skill / --figures gate); write_package COLLECTS whatever already exists under
    # figures/, so emit into args.out/figures BEFORE write_package. Best-effort: a render fault must
    # never break the run (the verdict spine + decision.json are already composed above).
    try:
        emit_headline_hero(decision, Path(args.out) / "figures")
    except Exception as e:  # noqa: BLE001 — display-only figure; never break the spine
        print(f"  (headline hero figure skipped: {type(e).__name__}: {e})")

    written = write_package(
        out_dir=args.out,
        decision=decision,
        card_outputs=emitted_cards,
        target=args.target,
        indication=args.indication,
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        invoked_lenses=invoked_lenses,
    )
    print(f"wrote data-package to {args.out}")
    print(f"  tables: {len(written['tables'])}  figures: {len(written['figures'])}")
    print()
    print(json.dumps(headline, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
