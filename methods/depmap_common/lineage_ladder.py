"""Indication-conditioned stratified-dependency ladder (genomic-alteration review T2.0).

The 4 DepMap stratified-dependency methods (mutation / cn / fusion / amp-expr) historically ran
pan-DepMap and DISCARDED the indication — so a lineage-context-dependent oncogene (the archetype:
BRAF, strongly BRAF-addicted in melanoma/thyroid but NOT in CRC) read a confident pan-cancer
biomarker_stratified_dependency while wearing an "in indication Y" label — the textbook clinical
false-positive.

This module implements the approved GRACEFUL-DEGRADATION LADDER at the READ layer (compute kernels
stay pure + byte-stable):
  1. WITHIN-LINEAGE: if the indication maps to a DepMap lineage AND the within-lineage split clears
     the method's floor → use the within-lineage result. evidence_scope = "within_indication".
  2. PAN-LINEAGE FALLBACK: else → use the pan-DepMap result, but DOWNGRADE a `*strongly*` class to
     its `*moderately*` sibling (we cannot confirm the strong effect is indication-specific).
     evidence_scope = "pan_lineage_evidence_only".
  3. DIVERGENCE FLAG: when BOTH ran and disagree in direction (within-lineage says not-dependent but
     pan says dependent, or vice-versa) → lineage_context_divergent = True (surfaced, not silenced).

The caller supplies a `compute(restricted_or_full_dicts) -> result` thunk and the class-field key;
this module owns only the lineage restriction + the ladder decision, so all 4 methods share ONE
implementation. Reuses the shared INDICATION_TO_DEPMAP_LINEAGE map (no fork).
"""
from __future__ import annotations

from typing import Callable, Optional


def models_in_lineage(model_metadata: dict, indication: Optional[str]) -> Optional[set]:
    """ModelIDs whose OncotreeLineage matches the indication's DepMap lineage.

    Returns None if the indication is missing/unmapped (→ caller uses pan-DepMap, no within arm).
    Empty set is possible (mapped lineage with no lines in the metadata) → also treated as "no
    within arm" by the caller's floor check."""
    if not indication:
        return None
    # Import here (not at module top) to avoid a circular import — depmap_chronos imports depmap_common.
    from methods.depmap_chronos.read import INDICATION_TO_DEPMAP_LINEAGE
    lineage = INDICATION_TO_DEPMAP_LINEAGE.get(str(indication).upper().strip())
    if lineage is None:
        return None
    return {mid for mid, meta in model_metadata.items()
            if (meta or {}).get("OncotreeLineage") == lineage}


# strongly → moderately downgrade map, per stratified method's class vocabulary. The pan-lineage
# fallback cannot confirm a strong effect is indication-specific, so it is capped at moderate.
_STRONG_TO_MODERATE = {
    "mutant_strongly_dependent": "mutant_moderately_dependent",
    "amplified_strongly_dependent": "amplified_moderately_dependent",
    "fusion_positive_strongly_dependent": "fusion_positive_moderately_dependent",
    # amp-expr emits the fully-spelled label pair (depmap_amp_expr_dependency.cli._LABELS);
    # keep these in exact sync with that method's strong/moderate strings.
    "amplified_overexpressed_strongly_dependent": "amplified_overexpressed_moderately_dependent",
}

# classes that mean "a positive dependency call" (for the divergence check)
_DEPENDENT_CLASSES = set(_STRONG_TO_MODERATE) | set(_STRONG_TO_MODERATE.values())


def apply_lineage_ladder(compute: Callable[[Optional[set], Optional[set]], dict],
                         class_key: str,
                         model_metadata: dict,
                         indication: Optional[str]) -> dict:
    """Run the 3-rung indication-conditioning ladder + attach provenance.

    `compute(mut_models, wt_models)` runs the method's stratification restricting the MUTANT arm to
    `mut_models` and the WT/comparator arm to `wt_models` (None = all DepMap lines for that arm). It
    must return a dict carrying `class_key`; insufficiency is detected via "insufficient" in the class.

    THE 3 RUNGS (the middle one added 2026-08-09 after a live backtest found high-prevalence drivers
    — e.g. BRAF in melanoma, mutated in 53/78 lines so only 25 WT < the 30-WT floor — were wrongly
    downgraded in exactly the lineages where the biomarker is STRONGEST):
      1. FULL WITHIN-LINEAGE  compute(L, L)  → evidence_scope=within_indication
      2. LINEAGE-MUT vs PAN-WT compute(L, None) → evidence_scope=within_indication_mut_vs_pan_wt
         (keeps the lineage-specific MUTANT arm — where indication-specificity lives — but borrows
         WT power from the whole panel; used when rung 1 is WT-underpowered but lineage mutants ≥ floor)
      3. PAN-LINEAGE FALLBACK  compute(None, None) + strong→moderate downgrade
         → evidence_scope=pan_lineage_evidence_only (only when even lineage mutants are too few)

    Provenance added: evidence_scope, lineage_evidence_scope_reason, lineage_context_divergent,
    pan_lineage_<class_key> (audit), pan_lineage_raw_<class_key> (when downgraded).
    """
    pan = compute(None, None)
    pan_class = pan.get(class_key)

    restrict = models_in_lineage(model_metadata, indication)
    if not restrict:
        pan["evidence_scope"] = "pan_no_indication"
        pan["lineage_evidence_scope_reason"] = (
            "indication unmapped to a DepMap lineage" if indication else "no indication supplied")
        pan["lineage_context_divergent"] = False
        return pan

    def _finish(res, scope, reason):
        cls = res.get(class_key)
        res["evidence_scope"] = scope
        res["lineage_evidence_scope_reason"] = reason
        res["lineage_context_divergent"] = (
            (cls in _DEPENDENT_CLASSES) != (pan_class in _DEPENDENT_CLASSES))
        res[f"pan_lineage_{class_key}"] = pan_class
        return res

    # RUNG 1 — full within-lineage (both arms in-lineage).
    within = compute(restrict, restrict)
    if "insufficient" not in str(within.get(class_key)):
        return _finish(within, "within_indication",
                       f"within-lineage split cleared the floor ({indication})")

    # RUNG 2 — lineage MUTANT arm vs PAN WT (fixes the high-prevalence-driver under-call).
    hybrid = compute(restrict, None)
    if "insufficient" not in str(hybrid.get(class_key)):
        return _finish(hybrid, "within_indication_mut_vs_pan_wt",
                       f"within-lineage WT arm underpowered ({indication}); "
                       "lineage-mutant vs pan-DepMap-WT comparator")

    # RUNG 3 — pan-lineage fallback, strong→moderate (even lineage mutants too few to indication-confirm).
    downgraded = _STRONG_TO_MODERATE.get(pan_class)
    if downgraded:
        pan[f"pan_lineage_raw_{class_key}"] = pan_class
        pan[class_key] = downgraded
    pan["evidence_scope"] = "pan_lineage_evidence_only"
    pan["lineage_evidence_scope_reason"] = (
        f"within-lineage underpowered even mut-vs-pan-WT ({indication}); pan-DepMap"
        + (" (strong→moderate: not indication-confirmed)" if downgraded else ""))
    pan["lineage_context_divergent"] = False
    return pan
