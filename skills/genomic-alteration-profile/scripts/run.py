#!/usr/bin/env python3
"""genomic-alteration-profile — genomic alteration profile for a (target, indication).

Answers "how is this gene genomically altered in indication Y, and which
alteration class drives?" — spanning SNV/indel (mutation) + copy-number
(amplification/deletion) + fusion/rearrangement (LIVE, tcga-fusion-consensus-v1),
with additive role / allele-count / patient-model / subtype panorama layers.

REFRAMED 2026-07-14 from `mutation-profile` (which was SNV/indel only). The
copy-number-distribution card + its 11 rules already existed but were never
composed into a skill — the same gene is often a driver via DIFFERENT
alteration classes across indications (ERBB2 amp in breast/gastric vs mutation
in a lung subset; MET exon14-skip + amplification), so a mutation-only skill
implied "not a driver" for amplification-driven targets. This skill reports the
alteration MIX and which class drives. See docs/SKILLS_SCOPE_REVIEW_2026-07-14.md.

Consumes 8 whole-cohort cards (3 mutation + copy-number + fusion + role +
functional-gene-state M6 + genomic-event-model-match M11). A 9th card,
subgroup-stratified-mutation-frequency (tier:subtype), resolves ONLY on the
optional --subtypes panorama path — a DESCRIPTIVE per-stratum frequency landscape
that touches no resolver rung (the verdict spine stays byte-stable regardless).
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
    make_decision_json, write_package, get_card_field,
)
from _skills_common.resolver import resolve_verdict_for_gate

SKILL_NAME = "genomic-alteration-profile"
SKILL_VERSION = "2.1.1"      # 2.0.0 reframed from mutation-profile; 2.1.0 (2026-08-05): subtype panorama + driver-recurrence percentile + opt-in synthesis

CARDS = [
    # SNV / indel (mutation)
    "mutation-type-counts",
    "mutation-stratified-dependency",
    "mutation-hotspot-frequency",
    # Copy number (amplification / deletion) — card + rules already existed
    "copy-number-distribution",
    # Copy-number-STRATIFIED dependency (A1a, 2026-08-06) — the CN analog of
    # mutation-stratified-dependency: are AMPLIFIED cell lines Chronos-more-dependent? Its
    # cn-amplified-*-dependent rules fire the SAME biomarker_stratified_dependency verdict the
    # mutation path uses (resolver section 2b), closing the amplification-driven-oncogene gap
    # (ERBB2/MYC). VERDICT-MOVING but golden-snapshot byte-identical (new rule ids never fire on
    # old enumerated combos). Composed here so the genomic gate reads the amplification-addiction signal.
    "copy-number-stratified-dependency",
    # Fusion-STRATIFIED dependency (A1-fusion, 2026-08-06) — the gene-fusion analog of the mut/CN
    # stratified cards: are cell lines carrying a fusion INVOLVING the target Chronos-more-dependent?
    # Its fusion-positive-*-dependent rules fire the SAME biomarker_stratified_dependency verdict
    # (resolver section 2c; reuses the mutation verdict), recovering the fusion-driven-oncogene class
    # (EWSR1-FLI1/BCR-ABL1) that BOTH the mutation-only and CN-only paths miss (neither mutated nor
    # amplified). VERDICT-MOVING but golden-snapshot byte-identical (new rule ids never fire on old
    # enumerated combos). Distinct from fusion-rearrangement-landscape below (TCGA-patient recurrence,
    # signal-only) — this is the DepMap cell-line dependency-establishing test.
    "fusion-stratified-dependency",
    # Amp→expr→dep three-way (A1 amp-expr, 2026-08-06) — the CONJOINT sibling of copy-number-stratified-
    # dependency: are lines BOTH amplified AND high-expression for the target Chronos-more-dependent? Its
    # amp-expr-*-dependent rules fire the SAME biomarker_stratified_dependency verdict (resolver section
    # 2d; reuses the mutation verdict), capturing amplification-DRIVEN overexpression-addiction (ERBB2/
    # MYC/KRAS-amp) that the CN-only path (expression-blind) under-weights. VERDICT-MOVING but golden-
    # snapshot byte-identical (new rule ids never fire on old enumerated combos). Precedence mut > cn >
    # fusion > amp-expr (most-specific last).
    "amp-expr-stratified-dependency",
    # Genotype × DRUG-RESPONSE (Thread 4, 2026-08-09) — the PHARMACOLOGICAL sibling of the stratified-
    # dependency cards above. Are lines carrying an alteration in the target more SENSITIVE to a DRUG
    # that TARGETS it (PRISM Log2AUC), vs the CRISPR-KO dependency the mutation-stratified card measures?
    # ADDITIVE signal-only: its small_molecule rules reach the LLM/matrix + headline, touch NO resolver
    # rung (verdict spine byte-stable). Deliberately NOT fired as biomarker_stratified_dependency:
    # drug-sensitivity != KO-dependency. Live: BRAF→mutant_strongly_drug_sensitive (vemurafenib q=4.8e-11);
    # KRAS→sensitive (G12C/G12D-inhibitor era); EGFR→not_stratified (honest cell-panel negative).
    "mutation-drug-response",
    # Fusion / rearrangement — LIVE 2026-07-23 (tcga-fusion-consensus-v1, pan-TCGA 3-caller
    # consensus). fusion_class {recurrent_fusion_driver|sporadic_fusion|no_recurrent_fusion|
    # data_unavailable}. ADDITIVE signal-only: reaches the LLM/matrix + headline, touches NO
    # resolver rung (the genomic verdict spine stays byte-stable). Recurrent-fusion driver
    # corroborates the genomic alteration call; graceful data_unavailable for TCGA-absent targets.
    "fusion-rearrangement-landscape",
    # Typed driver-ROLE call (OncoKB × IntOGen) — the functional-role layer on the descriptive
    # cards above (frequency ≠ function). VERDICT-DRIVING: its alteration-role-gof-driver-supportive /
    # alteration-role-lof-driver-neutral rules fire the 12 confirmed_driver rungs (resolver §0) via
    # when_all_fired with a mut/cn driver rule — confirmed_driver is the HIGHEST-precedence genomic
    # verdict. (2026-08-08 review: this comment previously claimed "ADDITIVE / rules touch no resolver
    # rung / byte-stable" — that was FALSE; corrected. Nomination-gate-neutral, but it DOES set the
    # verdict.) Also in target-profile SUB_SKILL_CARDS[genomic-alteration-profile] (composer-consistency).
    "alteration-role",
    # Harmonized two-hit / biallelic-inactivation state (M6, functional_gene_state). The ALLELE-COUNT
    # layer: is the gene biallelically inactivated (completed two-hit → LoF) or only monoallelically
    # hit — mutation + allele-specific CN, patient (TCGA) + model (DepMap) arms. ADDITIVE signal-only:
    # its state signals + headline reach the LLM/matrix but touch NO resolver rung (the genomic
    # verdict spine stays byte-stable — wiring INTO the verdict is a later, riskier step). Phase-1
    # genetic-only vocab {wt, monoallelic, biallelic-genetic, uncertain}.
    "functional-gene-state",
    # Patient↔model genomic-event correspondence (M11, genomic_event_model_match — the canonical P3
    # join). Which DepMap models carry the SAME functional event as the tumors, and which are
    # dependent? The genomic sibling of recommended-models (expression-Q4). ADDITIVE signal-only:
    # feeds LLM/matrix + headline, touches NO resolver rung (verdict spine byte-stable). Corroborates
    # Required (C) — genotype-matched + dependent in-lineage models = a genotype-backed dependency basis.
    "genomic-event-model-match",
    # Genome-instability / aneuploidy burden (M7, genomic_instability_state). INDICATION-level,
    # target-INDEPENDENT cohort context: how chromosomally unstable is this cancer? (high CIN →
    # WGD/prognosis + copy-number-noise caveats). ADDITIVE signal-only: feeds LLM/matrix + headline,
    # touches NO resolver rung (verdict spine byte-stable). Reads tcga_aneuploidy_burden live.
    "genomic-instability-state",
    "ddr-deficiency-context",   # Track PI (2026-08-09): per-indication DDR/HRD cohort-context facet
                                # (PanCanAtlas DDR footprint, Knijnenburg 2018). VERDICT-INERT display
                                # facet (sibling of genomic-instability-state) — surfaces the cohort HRD
                                # prior (hrd_enriched/intermediate/low) that frames HRD-conditional
                                # hypotheses; touches NO resolver rung. Alteration-verdict byte-stable.
    "oncogenic-pathway-alteration",   # Sanchez-Vega 2018 (2026-08-10): per-indication oncogenic-pathway
                                      # ALTERATION frequency (10 pathways); VERDICT-INERT cohort context;
                                      # complements PROGENy activity. Reads oncogenic_pathway_alteration.
    # Per-VARIANT interpretation (variant_level_interpretation, CIViC). Closes the gene→variant gap:
    # every other mutation card is per-GENE (alteration-role = GoF/LoF per gene) or FREQUENCY
    # (recurrence), not FUNCTION — this names which specific variants are oncogenic (vs VUS/benign)
    # and which confer therapy resistance (EGFR T790M→TKIs, BRAF V600E→cetuximab). ADDITIVE
    # signal-only: feeds LLM/matrix + headline, touches NO resolver rung (verdict spine byte-stable).
    "variant-level-interpretation",
]

# SUBTYPE axis (2026-08-05 hardening) — kept OUT of the scalar CARDS list ON PURPOSE.
# subgroup-stratified-mutation-frequency (tier:subtype) is a PANORAMA card: its dispatcher
# needs externally-resolved strata (subgroup_context.resolved_strata_ids) or it returns only
# a data-note. So — mirroring target-profile's SUBTYPE_CARDS — it resolves on a SEPARATE,
# --subtypes-gated path (see _resolve_subtype_panorama below), never on the whole-cohort spine.
# DESCRIPTIVE panorama: recomputes frequency WITHIN each stratum's denominator (MSI/MSS,
# sidedness, GENIE line-of-therapy); emits per_subgroup_metrics + cross_subgroup_delta_frequency;
# NO verdict signal → touches NO resolver rung (the genomic_alteration verdict spine stays
# byte-stable whether or not a subtype scope is passed). The genomic analog of tumor-presence's
# tumor-rna-distribution-by-subtype.
SUBTYPE_CARDS = [
    "subgroup-stratified-mutation-frequency",
]

QUESTION = ("How is {target} genomically altered in {indication} — by SNV/indel "
            "(driver, biomarker-stratified dependency, or passenger), by copy-"
            "number (amplification/deletion), or a mix — and which class drives?")


# ── Composed-level family-wise FDR across the stratified-dependency classes (deferred-a) ──────────
# The 4 stratified-dependency cards (mutation / CN / fusion / amp-expr) each fire the SAME
# biomarker_stratified_dependency verdict from an INDEPENDENT Mann-Whitney test, each computed in its
# own method at its own per-card alpha (0.05). Across the family, the per-card alpha is UNCORRECTED —
# a gene tested on all 4 alteration classes has an inflated family-wise false-positive rate. The
# effect-size floor (|delta|>=0.2) already guards significance-only FPs, but multiplicity remains.
#
# There is NO shared compute point (the cards are architecturally decoupled — composability by
# design), so the correction MUST happen here, post-composition: collect the firing classes' p-values,
# apply Benjamini-Hochberg across the family, and DEMOTE any card whose BH-adjusted q >= alpha to its
# not_*_stratified class so its rule cannot fire. Only bites when >=2 classes fire (family size 1 →
# BH = identity → byte-stable for the common single-class case). Verdict-moving ONLY for genuinely
# multi-class targets where the weakest class fails the multiplicity-corrected bar.
_STRATIFIED_FAMILY = [
    # (card_id, class_field, p_field, firing_classes, demoted_class)
    ("mutation-stratified-dependency", "mutation_stratification_class", "hotspot_mannwhitney_p",
     {"mutant_strongly_dependent", "mutant_moderately_dependent"}, "not_mutation_stratified"),
    ("copy-number-stratified-dependency", "cn_stratification_class", "cn_stratification_mannwhitney_p",
     {"amplified_strongly_dependent", "amplified_moderately_dependent"}, "not_cn_stratified"),
    ("fusion-stratified-dependency", "fusion_stratification_class", "fusion_stratification_mannwhitney_p",
     {"fusion_positive_strongly_dependent", "fusion_positive_moderately_dependent"}, "not_fusion_stratified"),
    ("amp-expr-stratified-dependency", "amp_expr_stratification_class", "amp_expr_mannwhitney_p",
     {"amplified_overexpressed_strongly_dependent", "amplified_overexpressed_moderately_dependent"},
     "not_amp_expr_stratified"),
]


def _bh_qvalues(pvals: list[float]) -> list[float]:
    """Benjamini-Hochberg adjusted q-values for a list of p-values (order preserved)."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    q = [0.0] * m
    prev = 1.0
    for rank, idx in enumerate(reversed(order), start=1):
        k = m - rank + 1                       # descending rank
        val = min(prev, pvals[idx] * m / k)
        q[idx] = val
        prev = val
    return q


def _apply_family_wise_fdr(cards: list[dict], alpha: float = 0.05) -> dict:
    """Collect the FIRING stratified-dependency classes across the family, BH-correct their p-values
    jointly, and DEMOTE (mutate the card's class in place) any whose family-wise q >= alpha. Returns a
    provenance dict {family_size, tested, demoted, family_wise_q} for the headline. No-op (byte-stable)
    when <2 classes fire."""
    card_by_id = {c["card_id"]: c for c in cards}
    firing = []
    for card_id, class_field, p_field, firing_classes, demoted in _STRATIFIED_FAMILY:
        c = card_by_id.get(card_id)
        if not c:
            continue
        summ = c.get("summary") or {}
        cls, p = summ.get(class_field), summ.get(p_field)
        if cls in firing_classes and isinstance(p, (int, float)):
            firing.append({"card_id": card_id, "class_field": class_field, "p": float(p),
                           "class": cls, "demoted": demoted, "summary": summ})
    if len(firing) < 2:
        # family size 0 or 1 → no multiplicity to correct → byte-stable
        return {"family_size": len(firing), "tested": [f["card_id"] for f in firing],
                "demoted": [], "family_wise_q": {}, "corrected": False}

    qs = _bh_qvalues([f["p"] for f in firing])
    demoted, fam_q = [], {}
    for f, q in zip(firing, qs):
        fam_q[f["card_id"]] = round(q, 6)
        if q >= alpha:
            # demote: rewrite the class so fired_rules cannot fire the stratified rule
            f["summary"][f["class_field"]] = f["demoted"]
            f["summary"]["_family_wise_fdr_demoted"] = True
            f["summary"]["_family_wise_q"] = round(q, 6)
            demoted.append(f["card_id"])
    return {"family_size": len(firing), "tested": [f["card_id"] for f in firing],
            "demoted": demoted, "family_wise_q": fam_q, "corrected": True}


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Multi-class genomic-alteration verdict — DELEGATES to the shared declarative resolver
    (gap #5 conversion, 2026-07-22). The former inline multi-axis if-chain (SNV/indel priority ×
    copy-number, combined into multi_class_driver) now lives in
    resolvers/genomic_alteration.resolver.yaml (target-contracts), evaluated by the ONE interpreter
    both engines call. Proven byte-for-byte equivalent to the former if-chain across all 256 (2^8)
    fired-set combinations by the pre-swap oracle + frozen in the golden snapshot. A missing spec
    raises (the resolver is the source of truth — NO silent fallback to a stale copy, which would
    reintroduce the drift this refactor eliminates)."""
    result = resolve_verdict_for_gate(fired, "genomic_alteration")
    if result is None:
        raise RuntimeError(
            "genomic_alteration resolver spec missing (target-contracts/resolvers/"
            "genomic_alteration.resolver.yaml) — the verdict source of truth is absent.")
    return result


def _resolve_subtype_panorama(target: str, indication: str,
                              subtypes: list[str]) -> dict:
    """DESCRIPTIVE subtype panorama — resolve subgroup-stratified-mutation-frequency
    across the requested strata. Mirrors target-profile's subtype tier: the card is a
    PANORAMA dispatcher, so it needs subgroup_context.resolved_strata_ids threaded or it
    returns only a data-note (which is why it is NOT in the whole-cohort CARDS list).

    Returns a compact projection for the headline's `subtype_axis` block — never a verdict.
    NO resolver rung is touched here, so the genomic_alteration verdict spine is byte-stable
    whether or not --subtypes is passed.
    """
    subgroup_context = {"resolved_strata_ids": list(subtypes),
                        "catalog_status": "resolved_active"}
    sub_cards = resolve_cards(SUBTYPE_CARDS, target, indication,
                              subgroup_context=subgroup_context)
    freq = next((c for c in sub_cards
                 if c["card_id"] == "subgroup-stratified-mutation-frequency"), None)
    summary = (freq or {}).get("summary") or {}
    per_subgroup = summary.get("per_subgroup_metrics") or []
    measured = [r for r in per_subgroup if r.get("evidence_state") == "measured"]
    delta = summary.get("cross_subgroup_delta_frequency")

    # Compact pattern label mirroring the card's own interpretation_hints (delta >= 0.10 =
    # subgroup-specific; delta < 0.10 with >=2 measured strata = uniform; else not-informative).
    # DISPLAY-ONLY — this is a data-note flavor string, not a verdict.
    if len(measured) < 2 or delta is None:
        pattern = "not_informative"
    elif delta >= 0.10:
        pattern = "subgroup_specific_pattern"
    else:
        pattern = "uniform_across_subgroups"

    return {
        "cards": sub_cards,
        "scope_subtypes": list(subtypes),
        "subtype_panorama": {
            "subtype_mutation_pattern":       pattern,     # display-only flavor, NOT a verdict
            "n_subgroups_with_data":          summary.get("n_subgroups_with_data"),
            "max_subgroup_frequency":         summary.get("max_subgroup_frequency"),
            "min_subgroup_frequency":         summary.get("min_subgroup_frequency"),
            "cross_subgroup_delta_frequency": delta,
            "measured_strata":                [r.get("stratum") for r in measured],
            "_missing": bool(freq is None or freq.get("_missing")),
            "_missing_reason": (freq or {}).get("_missing_reason"),
        },
    }


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
    # Composed-level family-wise FDR (deferred-a): correct the stratified-dependency family for
    # multiplicity BEFORE firing rules. Mutates demoted cards in place; no-op when <2 classes fire.
    fdr_provenance = _apply_family_wise_fdr(cards)
    fired = fired_rules(cards, axis="intracellular_intrinsic",
                        card_id_filter=CARDS)
    verdict, driving_rule = _verdict(fired)

    # Optional subtype panorama (DESCRIPTIVE, --subtypes-gated) — separate from the verdict spine.
    subtypes = [s.strip() for s in args.subtypes.split(",") if s.strip()] if args.subtypes else []
    subtype_result = _resolve_subtype_panorama(args.target, args.indication, subtypes) if subtypes else None

    headline = {
        "genomic_alteration_profile":    verdict,
        "driving_rule_id":               driving_rule,
        # Family-wise FDR provenance (deferred-a): when >=2 stratified-dependency classes fired, their
        # p-values were BH-corrected jointly; any class with family-wise q >= 0.05 was demoted (its rule
        # suppressed) so a multi-class call is not over-credited by uncorrected multiplicity.
        "stratified_family_wise_fdr":    fdr_provenance,
        # SNV / indel axis
        "mutation_landscape_class":      get_card_field(cards, "mutation-type-counts",
                                              "mutation_landscape_class"),
        "mutation_stratification_class": get_card_field(cards, "mutation-stratified-dependency",
                                              "mutation_stratification_class"),
        # Indication-conditioning provenance (T2.0, 2026-08-09) — at what SCOPE was the stratified
        # dependency call made? within_indication (within-lineage split) / within_indication_mut_vs_pan_wt
        # (lineage mutants vs pan-DepMap WT — high-prevalence-driver lineages) / pan_lineage_evidence_only
        # (within-lineage underpowered → pan-DepMap, strong capped to moderate) / pan_no_indication.
        # Surfaced so a reader/LLM knows whether the biomarker call is indication-specific or a
        # pan-cancer extrapolation; lineage_context_divergent flags a within-vs-pan disagreement.
        "stratified_evidence_scope":     get_card_field(cards, "mutation-stratified-dependency",
                                              "evidence_scope"),
        "stratified_lineage_context_divergent": get_card_field(cards, "mutation-stratified-dependency",
                                              "lineage_context_divergent"),
        # True when a pan-fallback STRONG stratified call was de-rated to moderate because the
        # within-lineage mutant arm was underpowered (tissue confound unresolved) — signals a
        # pan-cancer extrapolation, not indication-specific evidence (T2.0).
        "stratified_pan_fallback_capped": get_card_field(cards, "mutation-stratified-dependency",
                                              "pan_fallback_strong_capped_to_moderate"),
        # Pharmacological biomarker (Thread 4): genotype → on-target DRUG-response (PRISM Log2AUC),
        # the complement to the CRISPR-KO stratified dependency above. Verdict-inert facet.
        "drug_response_stratification_class": get_card_field(cards, "mutation-drug-response",
                                              "drug_response_stratification_class"),
        "drug_response_delta_log2auc":    get_card_field(cards, "mutation-drug-response",
                                              "delta_log2auc_mut_vs_wt"),
        "drug_response_n_on_target_compounds": get_card_field(cards, "mutation-drug-response",
                                              "n_on_target_compounds"),
        "overall_mutation_frequency":    get_card_field(cards, "mutation-hotspot-frequency",
                                              "overall_mutation_frequency"),
        # Driver-recurrence percentile (Axis-1 contextualization, 2026-08-05) — is this gene's
        # recurrence unusual among all mutated genes in-indication? DISPLAY facet, verdict-inert.
        # TCGA-MC3 (whole-exome, ~1k pts) + GENIE (panel, ~35x pts, coverage-correct) — two distinct
        # comparators surfaced side by side (2026-08-06). Both verdict-inert.
        "driver_recurrence_class":       get_card_field(cards, "mutation-hotspot-frequency",
                                              "driver_recurrence_class"),
        "driver_recurrence_percentile":  get_card_field(cards, "mutation-hotspot-frequency",
                                              "driver_recurrence_percentile"),
        "genie_driver_recurrence_class": get_card_field(cards, "mutation-hotspot-frequency",
                                              "genie_driver_recurrence_class"),
        "genie_mutation_frequency":      get_card_field(cards, "mutation-hotspot-frequency",
                                              "genie_mutation_frequency"),
        # Copy-number axis (cell-line, verdict-driving) + PATIENT-tumour CN cross-check (TCGA GISTIC,
        # indication-specific, verdict-inert). Surfacing both lets the LLM/reviewer flag cell-line↔patient
        # CN discrepancies (a locus amplified in patients but not the cell-line panel, or vice versa).
        "copy_number_class":             get_card_field(cards, "copy-number-distribution",
                                              "copy_number_class"),
        "patient_copy_number_class":     get_card_field(cards, "copy-number-distribution",
                                              "patient_copy_number_class"),
        # Copy-number-STRATIFIED dependency (A1a) — amplified-vs-neutral Chronos split; the
        # amplification-addiction biomarker (ERBB2/MYC). Fires biomarker_stratified_dependency via
        # the resolver's section-2b rungs (reuses the mutation verdict). Surfaced for the LLM/matrix.
        "cn_stratification_class":       get_card_field(cards, "copy-number-stratified-dependency",
                                              "cn_stratification_class"),
        # Fusion-STRATIFIED dependency (A1-fusion) — fusion-positive-vs-negative Chronos split; the
        # fusion-addiction biomarker (EWSR1-FLI1/BCR-ABL1). Fires biomarker_stratified_dependency via
        # the resolver's section-2c rungs (reuses the mutation verdict). Surfaced for the LLM/matrix.
        # DISTINCT from fusion_class below (TCGA-patient recurrence facet) — this is the cell-line
        # dependency-establishing signal.
        "fusion_stratification_class":   get_card_field(cards, "fusion-stratified-dependency",
                                              "fusion_stratification_class"),
        # Amp→expr→dep three-way (A1 amp-expr) — conjoint amplified+overexpressed-vs-rest Chronos split;
        # amplification-DRIVEN overexpression-addiction (ERBB2/MYC/KRAS-amp). Fires
        # biomarker_stratified_dependency via the resolver's section-2d rungs (reuses the mutation
        # verdict). Surfaced for the LLM/matrix. The conjoint refinement the CN-only class under-weights.
        "amp_expr_stratification_class": get_card_field(cards, "amp-expr-stratified-dependency",
                                              "amp_expr_stratification_class"),
        # Fusion / rearrangement axis — LIVE (tcga-fusion-consensus-v1). fusion_class is the TCGA
        # 3-caller-consensus verdict (deep, 33 tissues); the genie_sv_* fields are the pan-cohort
        # BREADTH complement (GENIE 271k panel tumors, coverage-correct — genie-sv-recurrence-v1,
        # 2026-08-06). All DISPLAY facets: the fusion axis touches NO resolver rung (spine byte-stable).
        "fusion_class":                  get_card_field(cards, "fusion-rearrangement-landscape",
                                              "fusion_class"),
        "genie_sv_recurrence_class":     get_card_field(cards, "fusion-rearrangement-landscape",
                                              "genie_sv_recurrence_class"),
        "genie_sv_frequency":            get_card_field(cards, "fusion-rearrangement-landscape",
                                              "genie_sv_frequency"),
        "genie_sv_recurrent_partners":   get_card_field(cards, "fusion-rearrangement-landscape",
                                              "genie_sv_recurrent_partners"),
        # Typed driver-role axis (OncoKB × IntOGen)
        "alteration_role":               get_card_field(cards, "alteration-role", "alteration_role"),
        "functional_direction":          get_card_field(cards, "alteration-role", "functional_direction"),
        # Allele-count / biallelic-inactivation axis (M6, functional_gene_state) — signal-only,
        # does NOT feed the verdict (additive; the resolver spine is byte-stable).
        "functional_state_class":        get_card_field(cards, "functional-gene-state", "functional_state_class"),
        # Patient↔model genomic-event correspondence (M11) — signal-only, does NOT feed the verdict.
        "event_correspondence_class":    get_card_field(cards, "genomic-event-model-match", "event_correspondence_class"),
        # Genome-instability / aneuploidy burden (M7) — INDICATION cohort context, target-independent.
        # signal-only, does NOT feed the verdict. Phase 3a adds a 2nd genome-state axis: wgd_class
        # (whole-genome-doubling prevalence, ABSOLUTE) — same card, also cohort-level + verdict-inert.
        "aneuploidy_burden_class":       get_card_field(cards, "genomic-instability-state", "aneuploidy_burden_class"),
        "wgd_class":                     get_card_field(cards, "genomic-instability-state", "wgd_class"),
        # MSI prevalence (Phase 3a) — cohort-level, CRC+STAD only (data_unavailable elsewhere = unlabelled,
        # not measured-negative). Same card, verdict-inert.
        "msi_class":                     get_card_field(cards, "genomic-instability-state", "msi_class"),
        # MODEL-side MSI (DepMap, all lineages) — the complement filling NSCLC/PAAD where patient MSI
        # is data_unavailable. Same card, cohort-level, verdict-inert.
        "model_msi_class":               get_card_field(cards, "genomic-instability-state", "model_msi_class"),
        # DDR/HRD cohort context (Track PI) — INDICATION-level, target-independent, verdict-inert.
        # The cohort HRD prior (hrd_enriched/intermediate/low) that frames the PARP1/HRD-blind axis.
        "ddr_context_class":             get_card_field(cards, "ddr-deficiency-context", "ddr_context_class"),
        "frac_hrd_high":                 get_card_field(cards, "ddr-deficiency-context", "frac_hrd_high"),
        # MODEL mutational-signature (DepMap SBS) — MMR-signature cross-validates MSI (independent signal);
        # cohort-level, verdict-inert. (SBS3-HRD is a weak proxy, kept in the card not the headline.)
        "model_mmr_signature_class":     get_card_field(cards, "genomic-instability-state", "model_mmr_signature_class"),
        # Per-VARIANT interpretation (CIViC) — the gene→variant axis: WHICH variants are oncogenic
        # (vs the gene-level role) + which confer therapy resistance. signal-only, verdict-inert.
        "civic_variant_class":           get_card_field(cards, "variant-level-interpretation", "civic_variant_class"),
        "civic_oncogenic_variants":      get_card_field(cards, "variant-level-interpretation", "oncogenic_variants"),
        "civic_resistance_variants":     get_card_field(cards, "variant-level-interpretation", "resistance_variants"),
        "cards_available":               sum(1 for c in cards if not c.get("_missing")),
        "cards_missing":                 [c["card_id"] for c in cards if c.get("_missing")],
    }

    # SUBTYPE axis (2026-08-05) — DESCRIPTIVE panorama; only present when --subtypes was passed.
    # Surfaced in the headline for the LLM/render, but NOT a verdict input (spine byte-stable).
    if subtype_result is not None:
        headline["subtype_scope"] = subtype_result["scope_subtypes"]
        headline["subtype_axis"] = subtype_result["subtype_panorama"]

    lenses = None
    invoked_lenses: dict = {}
    if args.modality:
        lenses = {args.modality: modality_lens(fired, args.modality)}
        invoked_lenses["modality"] = args.modality

    # The whole-cohort cards drive the verdict; the subtype panorama cards (if any) are
    # appended for the emitted package + LLM, but are NOT in `fired` — they touch no rung.
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

    # OPT-IN LLM synthesis (two-slot). This skill hand-rolls main() (does NOT use run_wired_skill),
    # so it copies the dispatcher's opt-in block — narrating through the GENOMIC-ALTERATION lens
    # (its own tool schema + prompt). Attached as a SIBLING key decision['llm_synthesis'] AFTER the
    # deterministic decision is composed → structurally cannot alter the verdict spine. A synthesis
    # failure (Bedrock auth/network) degrades to a note; the deterministic run never breaks.
    if args.synthesize:
        from _skills_common.synthesis_genomic import synthesize_genomic_alteration
        try:
            decision["llm_synthesis"] = synthesize_genomic_alteration(
                decision, args.synthesis_model, None)
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
