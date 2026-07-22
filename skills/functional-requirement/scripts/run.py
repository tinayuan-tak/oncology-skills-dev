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
from _skills_common.resolver import resolve_verdict_for_gate


SKILL_NAME = "functional-requirement"
SKILL_VERSION = "1.1.0"

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
    def _get(cid: str, key: str):
        for c in cards:
            if c["card_id"] == cid:
                return (c["summary"] or {}).get(key)
        return None

    v, drv = verdict_pair or ("insufficient", None)
    predictability_class = _get("dependency-predictability", "predictability_class")
    confidence = _dependency_confidence_note(v, predictability_class)
    return {
        "dependency_verdict":       v,
        "driving_rule_id":          drv,
        "crispr_call":              _get("pan-cancer-crispr-dependency-distribution",
                                          "dependency_class"),
        "rnai_call":                _get("pan-cancer-rnai-dependency-distribution",
                                          "dependency_class"),
        "concordance_call":         _get("crispr-rnai-dependency-concordance",
                                          "concordance_class"),
        "lineage_selectivity":      _get("dependency-lineage-selectivity",
                                          "lineage_selectivity_class"),
        "paralog_buffering_class":  _get("paralog-buffering",
                                          "paralog_buffering_class"),
        "strongest_paralog_symbol": _get("paralog-buffering",
                                          "strongest_paralog_symbol"),
        # Gate-C gap 1 (Option A): predictability CONFIDENCE annotation over the verdict —
        # additive; the verdict + driving_rule_id above are untouched.
        "predictability_class":     predictability_class,
        "pred_dominant_feature_class": _get("dependency-predictability",
                                            "pred_dominant_feature_class"),
        "dependency_confidence":    confidence["confidence"],
        "dependency_confidence_note": confidence["note"],
        # Q4 patient↔model correspondence — model-backed-dependency corroboration (render facet):
        "model_correspondence_class": _get("recommended-models", "correspondence_class"),
        "n_positive_models_in_lineage": _get("recommended-models", "n_positive_models_in_lineage"),
        # Q7 protein abundance → dependency (render facet, biomarker-assay comparison vs the RNA arm):
        "abundance_dependency_class": _get("abundance-dependency", "abundance_dependency_class"),
        "protein_dependency_pearson_r": _get("abundance-dependency", "protein_dependency_pearson_r"),
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
    ))
