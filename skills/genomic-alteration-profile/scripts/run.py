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
    make_decision_json, write_package,
)
from _skills_common.resolver import resolve_or_raise
# The family-wise FDR across the stratified-dependency classes is single-sourced in
# _skills_common.card_preprocessors so all three resolution paths apply it identically:
# this skill's main(), the target-profile fan-out, and compose-dashboard's gate spine.
# apply_family_wise_fdr is used by main(); _bh_qvalues is re-exported for this skill's tests.
from _skills_common.card_preprocessors import (  # noqa: F401
    apply_family_wise_fdr as _apply_family_wise_fdr, _bh_qvalues,
)

SKILL_NAME = "genomic-alteration-profile"
SKILL_VERSION = "2.6.0"

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
    "variant-level-interpretation",    # per-variant oncogenicity + therapy-resistance alleles (CIViC)
    "target-clonality",                # is the driver mutation truncal (durable) or subclonal (relapse-prone)?
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
    return headline


def main() -> int:
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
