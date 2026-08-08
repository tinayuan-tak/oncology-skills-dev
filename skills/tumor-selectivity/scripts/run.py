#!/usr/bin/env python3
"""tumor-selectivity — tumor-vs-normal selectivity for a single (target, indication).

W4d refactor (2026-07-09): calls the shared run_wired_skill dispatcher.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill
from _skills_common.resolver import resolve_verdict_for_gate
from _skills_common.synthesis_selectivity import synthesize_selectivity


SKILL_NAME = "tumor-selectivity"
SKILL_VERSION = "1.6.0"    # 2026-08-08: INC-4 — axis-C absolute surface-density facet (Tier-1 calibrated
                           #   copies/cell + floor standing + modality-viability flags). VERDICT-INERT
                           #   (display facet, no clamp — below-floor is a modality caveat, not a downgrade;
                           #   CD19 counterexample). selectivity_class byte-stable.
                           # 1.5.0: INC-3 — cell-type-resolved axis-D veto arm. sc-normal-celltype-
                           #   expression composed; sc_normal_safety_essential_class == critical_organ_liability
                           #   fires tvn-sc-normal-critical-organ-veto → downgrade. 3rd normal-breadth veto arm.
                           # 1.4.0: DEFERRED-2 pan-normal window veto arm.
                           # 1.3.0: F1 resolved-verdict emission + DEFERRED-3 purity facet.
                           # 1.2.0: opt-in --synthesize selectivity-lens narrator.

CARDS = [
    "tumor-vs-normal-selectivity",
    "tumor-vs-normal-percentile-crossing",   # Q2 — per-sample fraction-above-normal-p95 (corroborates
                                             # the aggregate log2FC at per-sample resolution). Its
                                             # tumor-vs-normal-crossing-* rules emit SM/degrader signals;
                                             # the selectivity RESOLVER stays keyed to the aggregate card
                                             # (verdict byte-stable — Q2 is additive signal/rationale).
    "modality-therapeutic-window",           # axis-B/E NORMAL-BREADTH VETO (conjunction redesign INC-1/2,
                                             # 2026-08-07): its therapeutic_window_class == no_therapeutic_window
                                             # (tumor below worst critical normal) fires tvn-no-therapeutic-
                                             # window-veto, which _verdict uses to DOWNGRADE a selective axis-A
                                             # call to selective_but_broadly_normal. The housekeeping fix:
                                             # over-expression vs tissue-of-origin is necessary but NOT
                                             # sufficient (best practice = tumor-to-WORST-normal window).
    "sc-normal-celltype-expression",         # INC-3 axis-D VETO (2026-08-08): cell-type-resolved normal safety.
                                             # sc_normal_safety_essential_class == critical_organ_liability
                                             # (target highly detected in an essential cell type of a NON-origin
                                             # critical organ — cardiomyocyte/hepatocyte/renal-tubule/HSC/neuron
                                             # — that bulk tissue medians dilute) fires tvn-sc-normal-critical-
                                             # organ-veto → _verdict downgrades a selective axis-A call. The 3rd
                                             # normal-breadth veto arm. origin_tissue_liability does NOT veto.
    "expression-purity-confound",            # DEFERRED-3 (2026-08-08 synthesis review): is the tumor-vs-normal
                                             # selectivity signal tumor-cell-intrinsic or stromal/immune
                                             # (microenvironment) content? The four-cell DESeq2 design has no
                                             # purity covariate, so a CAF/stromal gene high in bulk tumor can
                                             # read tumor_selective. ADDITIVE render-only facet (verdict-INERT
                                             # — its purity rules feed NO selectivity resolver rung; the
                                             # selectivity_class spine is byte-stable). Surfaces the caveat.
    "surface-abundance-density",             # INC-4 axis-C (2026-08-08): absolute surface DENSITY (copies/cell).
                                             # VERDICT-INERT facet — the Tier-1 calibrated absolute anchor
                                             # (grade A/B curated corpus) + its floor standing (Slaga 2018 TCE
                                             # 1000/cell, ADC 10000/cell). NOT a veto: below-floor is a MODALITY
                                             # caveat, not a target killer (CD19=110/cell is a validated CAR-T
                                             # antigen — high-avidity binders work below the soluble-TCE floor).
                                             # Feeds NO resolver rung; selectivity_class byte-stable. Un-anchored
                                             # targets → unmeasured (abstain; absence != low density).
]

# The axis-A "selective" verdicts the normal-breadth veto can downgrade (over-expressed, but the
# conjunction with no therapeutic window makes them not a real target).
_AXIS_A_SELECTIVE = frozenset({
    "strong_tumor_selective", "modest_tumor_selective", "field_effect_tumor_selective",
})
_WINDOW_VETO_RULE = "tvn-no-therapeutic-window-veto"
# DEFERRED-2 (2026-08-08): pan-normal companion veto. therapeutic_window is essential-organs-only;
# full_normal_window is tumor ÷ worst of the FULL normal atlas — catches a gene broad across
# NON-essential normals (TROP2/TACSTD2 salivary archetype) that clears the essential-organ window.
_FULL_NORMAL_VETO_RULE = "tvn-no-full-normal-window-veto"
# INC-3 (2026-08-08): cell-type-resolved axis-D veto — target highly detected in a safety-essential
# cell type of a NON-origin critical organ (sc_normal_safety_essential_class == critical_organ_liability).
_SC_NORMAL_VETO_RULE = "tvn-sc-normal-critical-organ-veto"
# All normal-breadth veto rules — ANY firing downgrades a selective axis-A call (worst-case conjunction).
# Precedence for the driving_rule LABEL when several fire: essential-organ window > pan-normal window >
# sc-normal cell-type (bulk window vetoes are the longer-standing instruments; all yield the same verdict).
_NORMAL_BREADTH_VETO_RULES = (_WINDOW_VETO_RULE, _FULL_NORMAL_VETO_RULE, _SC_NORMAL_VETO_RULE)

QUESTION = ("How selectively is {target} expressed in {indication} tumor "
            "tissue, and how robust is that call across independent tumor-vs-"
            "normal comparators (TCGA-adjacent raw + ComBat, GTEx-population "
            "raw)?")


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Tumor-vs-normal selectivity verdict — DELEGATES to the shared declarative
    resolver (gap #5, 2026-07-20). The if-chain that used to live here is now
    resolvers/selectivity.resolver.yaml (target-contracts), evaluated by the ONE
    interpreter both engines call. Proven byte-for-byte equivalent to the former
    if-chain by the golden-oracle test (test_resolver_flat_gates_oracle.py). A missing
    spec raises (the resolver is now the source of truth — NO silent fallback to a stale
    copy, which would reintroduce the drift this refactor eliminates)."""
    result = resolve_verdict_for_gate(fired, "selectivity")
    if result is None:
        raise RuntimeError(
            "selectivity resolver spec missing (target-contracts/resolvers/"
            "selectivity.resolver.yaml) — the verdict source of truth is absent.")
    # axis-B/E NORMAL-BREADTH VETO (conjunction redesign INC-1/2) — a DOCUMENTED post-resolver clamp
    # (the resolver's when_fired is single-card; this veto is a 2-card conjunction). Best practice:
    # tumor-vs-tissue-of-origin over-expression (axis A, the resolver verdict) is NECESSARY but NOT
    # SUFFICIENT — a gene with NO therapeutic window vs the worst critical normal (housekeeping:
    # GAPDH/ACTB/TUBB) is not a target regardless of its axis-A fold-change. When axis-A is selective
    # AND the therapeutic-window veto rule fired (modality-therapeutic-window therapeutic_window_class
    # == no_therapeutic_window), downgrade to selective_but_broadly_normal. One-directional: it can
    # only DOWNGRADE a selective call, never upgrade — F1-safe.
    verdict, driving = result
    # Worst-case conjunction: a selective axis-A call is downgraded if ANY normal-breadth veto fired —
    # the essential-organ window veto (INC-1/2) OR the pan-normal window veto (DEFERRED-2). One-
    # directional (only downgrades a selective call). driving_rule names the veto that fired (essential
    # takes precedence in the label when both fire — it is the stricter critical-organ signal).
    if verdict in _AXIS_A_SELECTIVE:
        fired_ids = {r.get("rule_id") for r in fired}
        # first veto in precedence order that fired names the downgrade (all yield the same verdict).
        for veto_rule in _NORMAL_BREADTH_VETO_RULES:
            if veto_rule in fired_ids:
                return ("selective_but_broadly_normal", veto_rule)
    return result


def _headline(cards, fired, verdict_pair):
    # id-lookup (NOT cards[0]) — robust to card order now that a 2nd card (Q2 percentile-crossing)
    # composes into this skill. Each card's summary is fetched by its card_id.
    def _summary(cid):
        for c in cards:
            if c.get("card_id") == cid:
                return c.get("summary") or {}
        return {}
    tvn = _summary("tumor-vs-normal-selectivity")
    pcx = _summary("tumor-vs-normal-percentile-crossing")   # Q2 per-sample corroboration
    # RESOLVED verdict from _verdict (includes the normal-breadth veto downgrade). Prior to 2026-08-08
    # this headline IGNORED verdict_pair and emitted the raw pre-veto tvn.selectivity_class — so a
    # veto-downgraded target (selective_but_broadly_normal) was NEVER emitted anywhere in decision.json,
    # AND the synthesis narrator read the pre-veto class and over-claimed selectivity. Now the resolved
    # verdict is the headline `selectivity_class`; the raw axis-A class is preserved separately for
    # transparency/audit. (synthesis-review Finding 1 — the foundation the veto arms rest on.)
    resolved_verdict, resolved_driving = (verdict_pair or (tvn.get("selectivity_class"), None))
    return {
        "selectivity_class":  resolved_verdict,               # RESOLVED (post-veto) — the audit spine
        "driving_rule_id":    resolved_driving,               # the rule that set it (e.g. the veto rule)
        "axis_a_selectivity_class": tvn.get("selectivity_class"),  # raw tumor-vs-origin class (pre-veto)
        "cells_supporting":   tvn.get("cells_supporting"),
        "cells_ran":          tvn.get("cells_ran"),
        "dominant_direction": tvn.get("dominant_direction"),
        "discordant":         tvn.get("discordant"),
        "sig_all_cells":      tvn.get("sig_all_cells"),
        "max_abs_log2fc":     tvn.get("max_abs_log2fc"),
        "data_schema":        tvn.get("_schema"),
        # Axis-1 selectivity contextualization (SEL-1) — where this gene's fold-change sits among
        # ALL genes in-indication. DISPLAY facet, verdict-inert (also read by the synthesis prompt).
        "selectivity_allgene_percentile":       tvn.get("selectivity_allgene_percentile"),
        "selectivity_allgene_percentile_class": tvn.get("selectivity_allgene_percentile_class"),
        # Q2 per-sample percentile-crossing (namespaced to avoid the selectivity_class collision):
        "percentile_crossing_class":       pcx.get("selectivity_class"),
        "fraction_tumor_above_normal_p95": pcx.get("fraction_tumor_above_normal_p95"),
        "distribution_overlap_tumor_normal": pcx.get("distribution_overlap_tumor_normal"),
        # DEFERRED-3 purity-confound facet (verdict-INERT — display/caveat only, feeds no resolver rung).
        # Is the tumor-vs-normal selectivity signal tumor-cell-intrinsic or driven by stromal/immune
        # microenvironment content the bulk DESeq2 design can't separate? microenvironment_confounded
        # flags a possible false ADC/degrader window from stromal expression.
        "purity_confound_class":       _summary("expression-purity-confound").get("purity_confound_class"),
        "expression_purity_pearson_r": _summary("expression-purity-confound").get("expression_purity_pearson_r"),
        # INC-4 axis-C absolute-density facet (VERDICT-INERT — display only; feeds no resolver/clamp,
        # selectivity_class byte-stable). Tier-1 calibrated copies/cell + floor standing + modality-
        # viability flags. below_tce_floor is a MODALITY caveat, NOT a downgrade (CD19 counterexample).
        # density_floor_verdict == 'unmeasured' for un-anchored targets (abstain; absence != low density).
        "absolute_surface_density_class":   _summary("surface-abundance-density").get("absolute_density_class"),
        "absolute_copies_per_cell":         _summary("surface-abundance-density").get("absolute_copies_per_cell"),
        "absolute_density_grade":           _summary("surface-abundance-density").get("absolute_density_grade"),
        "density_floor_verdict":            _summary("surface-abundance-density").get("density_floor_verdict"),
        "is_tce_viable":                    _summary("surface-abundance-density").get("is_tce_viable"),
        "is_adc_high_payload_viable":       _summary("surface-abundance-density").get("is_adc_high_payload_viable"),
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
        # Opt-in --synthesize narrates through the SELECTIVITY lens (its own tool schema + prompt),
        # NOT the presence narrator the dispatcher used to hardcode. Two-slot / verdict-inert.
        synthesize_fn=synthesize_selectivity,
    ))
