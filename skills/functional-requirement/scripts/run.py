#!/usr/bin/env python3
"""functional-requirement — is target X a genetic dependency in indication Y.

Consumes 7 dependency-relevant cards (CRISPR + RNAi + concordance +
lineage-selectivity + paralog-buffering + prism-crispr chemical-genetic confirmation +
dependency-predictability) + the dependency-* rule subset.

The verdict is resolved from the first 6 cards via the shared dependency resolver;
dependency-predictability is META-evidence that drives a CONFIDENCE ANNOTATION only
(dependency_confidence_note), never the verdict (Gate-C gap 1, Option A, 2026-07-21).

W4d refactor (2026-07-09): calls the shared run_wired_skill dispatcher.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill
from _skills_common import get_card_field, resolve_cards
from _skills_common.resolver import resolve_verdict_for_gate
from _skills_common.synthesis_dependency import synthesize_dependency


SKILL_NAME = "functional-requirement"
SKILL_VERSION = "1.3.1"   # 1.3.1 (2026-08-08): fix 2 headline field-name drift bugs — rnai_call read
                          #        `dependency_class` (card emits `rnai_dependency_class`) + lineage_selectivity
                          #        read `lineage_selectivity_class` (card emits `enrichment_class`); both were
                          #        silently None despite live data. Display-only — verdict spine byte-stable.
                          # 1.3.0: opt-in --subtypes DESCRIPTIVE dependency-by-molecular-subgroup
                          #        panorama (subgroup-stratified-dependency; e.g. MSI_H vs MSS).
                          #        Verdict-inert (touches no rung); byte-stable without the flag.
                          # 1.2.0: opt-in --synthesize LLM narration (dependency lens) — two-slot,
                          #        verdict-inert; FULL evidence set + Axis-2 controls + Axis-3 omnibus.

CARDS = [
    "pan-cancer-crispr-dependency-distribution",
    "pan-cancer-rnai-dependency-distribution",
    "crispr-rnai-dependency-concordance",
    "dependency-lineage-selectivity",
    "paralog-buffering",                        # Layer 6d addition
    "prism-crispr-concordance",                 # E-PRISM re-home 2026-07-20 — chemical-genetic
                                                # CONFIRMATION arm (gate C). Its triangulated_target_engaged
                                                # class fires e7-triangulated-target-engaged-supportive, which
                                                # the dependency resolver now reads as
                                                # chemical_genetic_confirmed_dependent (a positive-only,
                                                # veto-safe confirmation). The card is ALSO in tractability-
                                                # small-molecule's CARDS (E1: "a compound was found") — one
                                                # measurement routes many-to-many to gates; each gate's
                                                # resolver/snapshot reads only its own rule_ids.
    "dependency-predictability",                # Gate-C gap 1 (Option A, 2026-07-21) — META-evidence
                                                # ("how omics-predictable is this dependency, and by what?").
                                                # Composed so it RUNS; it feeds a CONFIDENCE ANNOTATION only
                                                # (dependency_confidence_note), NEVER the verdict/resolver.
                                                # predictability is about a dependency call, not a call itself.
    "expression-dependency-correlation",        # Gate-C biomarker facet (2026-07-22): "expression
                                                # predicts dependency" (patient-selection). Was ORPHANED —
                                                # present in target-profile's render maps (title/role/
                                                # reports_into) + has a live dispatcher, but was in NO
                                                # sub-skill CARDS, so correlation_class never computed +
                                                # rendered empty. Render-only facet (its expression-biomarker-*
                                                # rules feed NO resolver — verdict-inert), grouped with the
                                                # dependency stratification facets. Also added to
                                                # target-profile SUB_SKILL_CARDS[functional-requirement].
    "abundance-dependency",                     # Q7 PROTEIN arm of expression-as-biomarker-of-dependency
                                                # (2026-07-22): "protein abundance predicts dependency".
                                                # Sibling of expression-dependency-correlation (RNA arm) —
                                                # composed alongside it so the biomarker facet can compare
                                                # RNA vs protein (preferred_assay). ADDITIVE render-only facet
                                                # (abundance-dependency-* rules feed NO resolver → dependency
                                                # verdict byte-stable). Biology axis; no modality facet.
    "recommended-models",                       # Q4 patient↔model correspondence (2026-07-22). Routes to
                                                # Gate C as MODEL-BACKED-DEPENDENCY corroboration (its
                                                # master-plan Patient-pop/Q10 home was deleted in #62). Its
                                                # recommended-models-* rules emit SM/degrader supportive on
                                                # well_modeled (a screenable, model-backed dependency basis);
                                                # ADDITIVE — feed NO resolver ladder → dependency verdict
                                                # byte-stable. Also in target-profile SUB_SKILL_CARDS.
]

# SUBTYPE axis (2026-08-06) — kept OUT of the scalar CARDS list ON PURPOSE, mirroring
# genomic-alteration-profile's SUBTYPE_CARDS. subgroup-stratified-dependency (tier:subtype) is a
# PANORAMA card: its dispatcher needs externally-resolved strata (subgroup_context.resolved_strata_ids)
# or it returns only a data-note — so it resolves on a SEPARATE, --subtypes-gated path (the
# dispatcher's subtype_panorama_fn hook), never on the whole-cohort verdict spine. DESCRIPTIVE:
# recomputes per-stratum Chronos WITHIN each subgroup's cell-line set (e.g. MSI_H vs MSS), emitting
# per_subgroup_metrics + cross_subgroup_delta_dependency; NO verdict signal → touches NO resolver rung
# (the dependency verdict is byte-stable whether or not a subtype scope is passed). The dependency
# analog of genomic-alteration's subgroup-stratified-mutation-frequency + tumor-presence's
# tumor-rna-distribution-by-subtype. NOTE: DepMap per-indication molecular strata are frequently
# UNDERPOWERED (few cell lines per subgroup) — the card tags subgroup_n<30 `underpowered`, and the
# panorama surfaces the evidence_state so an underpowered stratum is never over-read.
SUBTYPE_CARDS = [
    "subgroup-stratified-dependency",
]

# Cross-stratum delta threshold mirroring the card's interpretation_hints
# (meaningful_subgroup_delta). Display-only flavor label, NOT a verdict.
_MEANINGFUL_SUBGROUP_DELTA = 0.10


def _resolve_dependency_subtype_panorama(target: str, indication: str | None,
                                         subtypes: list) -> dict:
    """DESCRIPTIVE dependency-by-subgroup panorama — resolve subgroup-stratified-dependency across
    the requested strata (e.g. MSI_H, MSS). Mirrors genomic-alteration's _resolve_subtype_panorama:
    the card is a PANORAMA dispatcher, so it needs subgroup_context.resolved_strata_ids threaded or
    it returns only a data-note (why it is NOT in the whole-cohort CARDS list).

    Returns the {cards, scope_subtypes, subtype_dependency_panorama} projection the dispatcher's
    subtype_panorama_fn hook expects. NO resolver rung is touched, so the dependency verdict spine
    is byte-stable whether or not --subtypes is passed. Reads the card's ACTUAL emitted field names
    (per_subgroup_metrics rows: stratum/class/evidence_state/median_chronos/subgroup_n;
    cross_subgroup_delta_dependency reducer)."""
    subgroup_context = {"resolved_strata_ids": list(subtypes),
                        "catalog_status": "resolved_active"}
    sub_cards = resolve_cards(SUBTYPE_CARDS, target, indication,
                              subgroup_context=subgroup_context)
    dep = next((c for c in sub_cards
                if c["card_id"] == "subgroup-stratified-dependency"), None)
    summary = (dep or {}).get("summary") or {}
    per_subgroup = summary.get("per_subgroup_metrics") or []
    # Only MEASURED strata are admissible for comparison (underpowered/absent are inadmissible —
    # the card's own discipline: DepMap per-subgroup cell-line n is frequently below the floor).
    measured = [r for r in per_subgroup if r.get("evidence_state") == "measured"]
    delta = summary.get("cross_subgroup_delta_dependency")

    # Compact pattern label mirroring the card's interpretation_hints (delta on median_chronos):
    # >= 0.10 with >=2 measured strata = subgroup-specific; < 0.10 with >=2 = uniform; else n/a.
    # DISPLAY-ONLY flavor — NOT a verdict.
    if len(measured) < 2 or delta is None:
        pattern = "not_informative"
    elif abs(delta) >= _MEANINGFUL_SUBGROUP_DELTA:
        pattern = "subgroup_specific_dependency"
    else:
        pattern = "uniform_across_subgroups"

    return {
        "cards": sub_cards,
        "scope_subtypes": list(subtypes),
        "subtype_dependency_panorama": {
            "subtype_dependency_pattern":       pattern,   # display-only flavor, NOT a verdict
            "n_subgroups_with_data":            summary.get("n_subgroups_with_data"),
            "max_subgroup_dependency":          summary.get("max_subgroup_dependency"),
            "min_subgroup_dependency":          summary.get("min_subgroup_dependency"),
            "cross_subgroup_delta_dependency":  delta,
            "measured_strata":                  [r.get("stratum") for r in measured],
            # surface per-stratum class + power so an underpowered stratum is never over-read
            "per_stratum":                      [{"stratum": r.get("stratum"),
                                                  "class": r.get("class"),
                                                  "evidence_state": r.get("evidence_state"),
                                                  "median_chronos": r.get("median_chronos"),
                                                  "subgroup_n": r.get("subgroup_n")}
                                                 for r in per_subgroup],
            "_missing": bool(dep is None or dep.get("_missing")),
            "_missing_reason": (dep or {}).get("_missing_reason"),
        },
    }

# The verdicts that ARE a real dependency call (positive or veto) — the ones a predictability
# confidence note meaningfully sharpens. On insufficient/discordant/underpowered verdicts the
# note stays neutral (there is no call to be confident in).
_DEPENDENCY_CALL_VERDICTS = frozenset({
    "concordant_dependent", "lineage_selective", "selective_dependent",
    "chemical_genetic_confirmed_dependent", "broadly_dependent",
    "non_dependent", "non_dependent_paralog_buffered", "pan_essential_killer",
})


def _dependency_confidence_note(verdict: str, predictability_class: str | None) -> dict:
    """Gate-C gap 1 (Option A): a CONFIDENCE ANNOTATION over the dependency verdict, derived
    from dependency-predictability meta-evidence. NEVER changes the verdict or the resolver —
    predictability answers "how omics-learnable is this dependency, and by what feature?", which
    sharpens CONFIDENCE in a call, it is not itself a dependency call.

    Returns {confidence, note} where confidence ∈ {high, moderate, standard, unknown}:
      - only annotates when the verdict is an actual dependency call (_DEPENDENCY_CALL_VERDICTS);
        otherwise `standard` with no meta-claim (nothing to be confident about).
      - own_omics_driven  → high: the dependency is predictable from the target's OWN omics — a
        biomarker-hypothesis-bearing call.
      - context_or_driver_dependent → moderate: predictable, but from lineage/driver context (the
        biomarker is the context, not the target).
      - weakly_predictable / unpredictable → standard: the call stands on the genetic evidence
        itself; predictability adds no biomarker handle (NOT a downgrade of the verdict).
      - data_unavailable / None → unknown: predictability not computed (E5 v2 coverage gap)."""
    if verdict not in _DEPENDENCY_CALL_VERDICTS:
        return {"confidence": "standard",
                "note": "Predictability annotation applies only to an actual dependency call."}
    pc = predictability_class
    if pc == "own_omics_driven":
        return {"confidence": "high",
                "note": "Dependency is predictable from the target's own omics "
                        "(biomarker-hypothesis-bearing) — higher confidence in the call."}
    if pc == "context_or_driver_dependent":
        return {"confidence": "moderate",
                "note": "Dependency is omics-predictable, but from lineage/driver context rather "
                        "than the target's own features — the biomarker is the context."}
    if pc in ("weakly_predictable", "unpredictable"):
        return {"confidence": "standard",
                "note": "Dependency is not well explained by omics — the call rests on the genetic "
                        "evidence itself; no omics biomarker handle (not a verdict downgrade)."}
    # data_unavailable or absent
    return {"confidence": "unknown",
            "note": "Predictability not computed for this target (E5 precompute coverage gap)."}

QUESTION = ("Is {target} a genetic dependency in {indication}, and how does "
            "the call hold up across CRISPR, RNAi, concordance, lineage-"
            "selectivity, and paralog-buffering views?")


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Verdict — DELEGATES to the shared declarative resolver (gap #5, 2026-07-20).
    The former if-chain now lives in resolvers/dependency.resolver.yaml (target-contracts),
    evaluated by the ONE interpreter both engines call. Proven byte-for-byte equivalent to
    the former if-chain by the golden-oracle test. A missing spec raises (the resolver is
    the source of truth — no silent fallback to a stale copy, which would reintroduce drift)."""
    result = resolve_verdict_for_gate(fired, "dependency")
    if result is None:
        raise RuntimeError(
            "dependency resolver spec missing (target-contracts/resolvers/dependency.resolver.yaml) "
            "— the verdict source of truth is absent.")
    return result

def _headline(cards, fired, verdict_pair):
    v, drv = verdict_pair or ("insufficient", None)
    predictability_class = get_card_field(cards, "dependency-predictability", "predictability_class")
    confidence = _dependency_confidence_note(v, predictability_class)
    return {
        "dependency_verdict":       v,
        "driving_rule_id":          drv,
        "crispr_call":              get_card_field(cards, "pan-cancer-crispr-dependency-distribution",
                                          "dependency_class"),
        "rnai_call":                get_card_field(cards, "pan-cancer-rnai-dependency-distribution",
                                          "rnai_dependency_class"),   # 2026-08-08 fix: card emits rnai_dependency_class (prefixed), not dependency_class → was silently None

        "concordance_call":         get_card_field(cards, "crispr-rnai-dependency-concordance",
                                          "concordance_class"),
        "lineage_selectivity":      get_card_field(cards, "dependency-lineage-selectivity",
                                          "enrichment_class"),   # 2026-08-08 fix: card emits enrichment_class (the rule keys on it too); lineage_selectivity_class never existed → was silently None

        "paralog_buffering_class":  get_card_field(cards, "paralog-buffering",
                                          "paralog_buffering_class"),
        "strongest_paralog_symbol": get_card_field(cards, "paralog-buffering",
                                          "strongest_paralog_symbol"),
        # Gate-C gap 1 (Option A): predictability CONFIDENCE annotation over the verdict —
        # additive; the verdict + driving_rule_id above are untouched.
        "predictability_class":     predictability_class,
        "pred_dominant_feature_class": get_card_field(cards, "dependency-predictability",
                                            "pred_dominant_feature_class"),
        "dependency_confidence":    confidence["confidence"],
        "dependency_confidence_note": confidence["note"],
        # Q4 patient↔model correspondence — model-backed-dependency corroboration (render facet):
        "model_correspondence_class": get_card_field(cards, "recommended-models", "correspondence_class"),
        "n_positive_models_in_lineage": get_card_field(cards, "recommended-models", "n_positive_models_in_lineage"),
        # Q7 protein abundance → dependency (render facet, biomarker-assay comparison vs the RNA arm):
        "abundance_dependency_class": get_card_field(cards, "abundance-dependency", "abundance_dependency_class"),
        "protein_dependency_pearson_r": get_card_field(cards, "abundance-dependency", "protein_dependency_pearson_r"),
    }


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="intracellular_intrinsic",
        question=QUESTION,
        verdict_fn=_verdict,
        headline_fn=_headline,
        # Opt-in --synthesize narrates through the DEPENDENCY lens (its own tool schema + prompt,
        # foregrounding the selective-vs-pan-essential distinction). Two-slot / verdict-inert: the
        # dispatcher attaches decision['llm_synthesis'] as a sibling key AFTER the spine is composed,
        # so it is structurally impossible for the narration to alter dependency_verdict. Without this
        # synthesize_fn the dispatcher would fall back to the PRESENCE narrator (wrong lens).
        synthesize_fn=synthesize_dependency,
        # Opt-in --subtypes resolves the DESCRIPTIVE dependency-by-molecular-subgroup panorama
        # (subgroup-stratified-dependency; e.g. MSI_H vs MSS). Verdict-inert: its cards touch no
        # resolver rung, so the dependency verdict is byte-identical without --subtypes.
        subtype_panorama_fn=_resolve_dependency_subtype_panorama,
    ))
