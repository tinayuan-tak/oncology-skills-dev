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
# Normal-breadth VETO clamp — SINGLE-SOURCED in _skills_common.selectivity_veto (F1, 2026-08-13) so BOTH
# this standalone skill AND the compose-dashboard engine (compose_core.resolve_gate_spine) apply the
# IDENTICAL clamp. Names re-exported here for the skill's own tests + local readability.
from _skills_common.selectivity_veto import (  # noqa: F401
    _AXIS_A_SELECTIVE, _NORMAL_BREADTH_VETO_RULES, _WINDOW_VETO_RULE,
    _FULL_NORMAL_VETO_RULE, _SC_NORMAL_VETO_RULE, apply_normal_breadth_veto,
)


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

QUESTION = ("How selectively is {target} expressed in {indication} tumor "
            "tissue, and how robust is that call across independent tumor-vs-"
            "normal comparators (TCGA-adjacent raw + ComBat, GTEx-population "
            "raw)?")


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Tumor-vs-normal selectivity verdict — DELEGATES to the shared declarative
    resolver (gap #5, 2026-07-20). The if-chain that used to live here is now
    resolvers/selectivity.resolver.yaml (target-contracts), evaluated by the ONE
    interpreter both engines call. The resolver mapping + the normal-breadth veto clamp are
    guarded by tests/test_verdict.py (resolver-outcome mapping + all 3 veto arms) and
    _skills_common/tests/test_compose_core.py (F1: resolve_gate_spine applies the same clamp);
    the resolver spec itself is validated by target-contracts/validators/validate_resolvers.py.
    A missing spec raises (the resolver is the source of truth — NO silent fallback to a stale
    copy, which would reintroduce the drift this refactor eliminates)."""
    result = resolve_verdict_for_gate(fired, "selectivity")
    if result is None:
        raise RuntimeError(
            "selectivity resolver spec missing (target-contracts/resolvers/"
            "selectivity.resolver.yaml) — the verdict source of truth is absent.")
    # NORMAL-BREADTH VETO (INC-1/2 conjunction) — the resolver verdict (axis-A tumor-vs-origin
    # over-expression) is NECESSARY but NOT SUFFICIENT: a gene with NO therapeutic window vs the worst
    # critical normal (housekeeping GAPDH/ACTB, or the TROP2/TACSTD2 broadly-normal surface archetype)
    # is not a target regardless of its fold-change. This post-resolver clamp downgrades a selective
    # axis-A call to selective_but_broadly_normal when ANY normal-breadth veto fired. SINGLE-SOURCED in
    # _skills_common.selectivity_veto (F1, 2026-08-13) so the compose-dashboard engine applies it too
    # (it previously dropped the clamp, resolving raw via compose_core.resolve_gate_spine). One-directional.
    verdict, driving = result
    return apply_normal_breadth_veto(verdict, driving, fired)


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
