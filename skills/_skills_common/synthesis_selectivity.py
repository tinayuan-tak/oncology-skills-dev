"""synthesis_selectivity — opt-in LLM narration for the tumor-selectivity lens.

Sibling of _skills_common/synthesis.py (presence), same TWO-SLOT contract:
  SLOT 1 (deterministic, byte-stable): decision["headline"]["selectivity_class"] +
    every card field. Built upstream; this module NEVER writes to it.
  SLOT 2 (llm, provenance-tagged): decision["llm_synthesis"], a SIBLING key attached
    AFTER the decision is composed — structurally impossible to alter the verdict.

The LLM NARRATES the deterministic tumor-vs-normal selectivity call + its cross-
comparator robustness (TCGA-adjacent raw + ComBat + GTEx) + the per-sample
percentile-crossing corroboration. It NEVER mints or flips selectivity_class.

SINGLE-LENS scope: judge how much the SELECTIVITY evidence informs whether the target
has a therapeutic WINDOW (tumor-elevated over normal) — NOT modality, NOT absolute
abundance (that is presence's job), NOT dependency. Selectivity is the tumor-vs-normal
CONTRAST; a target can be abundant yet non-selective (no window) or selective yet
low-abundance (a window on a faint signal).
"""
from __future__ import annotations

from _skills_common.llm import EVIDENCE_ONLY_DIRECTIVE as _EVIDENCE_ONLY_DIRECTIVE

from typing import Optional

SYNTHESIS_TOOL_NAME = "emit_selectivity_synthesis"
SYNTHESIS_TOOL_SCHEMA = {
    "type": "object",
    "description": ("Assess, from the tumor-vs-normal SELECTIVITY lens ALONE, how much this lens "
                    "informs whether the target has a therapeutic WINDOW in this cancer. Reason "
                    "ACROSS the comparators (TCGA-adjacent raw + ComBat, GTEx-population raw) and the "
                    "per-sample percentile-crossing corroboration; do NOT restate a different verdict, "
                    "do NOT assess modality or absolute abundance (that is presence's job)."),
    "properties": {
        "selectivity_relevance_for_target": {
            "type": "string",
            "enum": ["strongly_supports", "supports_with_caveats", "neutral_uninformative",
                     "argues_against"],
            "description": ("The headline judgment: how much does the SELECTIVITY evidence support a "
                            "therapeutic window? strongly_supports = robust tumor-elevation over normal "
                            "concordant across independent comparators. supports_with_caveats = "
                            "selective but qualified (one comparator only, modest fold-change, proxy "
                            "normal). neutral_uninformative = not distinguishing (no elevation, or "
                            "present-but-flat) — selectivity is NOT the reason to pursue this target. "
                            "argues_against = tumor-DEPLETED or discordant across comparators. A "
                            "SINGLE-LENS read; it informs confidence, NEVER mints/flips a verdict.")},
        "selectivity_rationale": {
            "type": "string",
            "description": ("2-4 sentences REASONING ACROSS the evidence: integrate the deterministic "
                            "selectivity_class, how many comparator cells supported it (cells_supporting "
                            "/ cells_ran), whether they were discordant, the max fold-change, and the "
                            "per-sample percentile-crossing (fraction of tumors above the normal p95). "
                            "Say explicitly whether a therapeutic window IS or IS NOT supported, and if "
                            "the comparators disagree, foreground that. Ground every claim in the "
                            "fields; cite DATA_UNAVAILABLE gaps rather than omitting them.")},
        "comparator_robustness": {
            "type": "string",
            "description": ("1-2 sentences on ROBUSTNESS: is the selectivity call consistent across the "
                            "TCGA-adjacent (raw + ComBat) and GTEx-population comparators, or does it "
                            "hinge on one? A call supported by only one cell is weaker than a concordant "
                            "multi-comparator call. If cells were discordant, say which direction each "
                            "went. Do NOT invent a comparator that did not run.")},
        "confidence_qualifier": {
            "type": "string",
            "enum": ["well_supported", "supported_with_caveats", "weakly_supported",
                     "insufficient_evidence"],
            "description": ("How well the gathered evidence supports the selectivity read above (data "
                            "completeness/quality: number of comparators, significance, per-sample "
                            "corroboration, proxy-normal). A CONFIDENCE read — it does not change the "
                            "deterministic verdict.")},
        "key_caveat": {
            "type": "string",
            "description": ("The single most important caveat a reviewer should carry (proxy/adjacent "
                            "normal contamination, single-comparator support, batch confound, modest "
                            "fold-change, wide CI), or 'none' if none.")},
    },
    "required": ["selectivity_relevance_for_target", "selectivity_rationale",
                 "comparator_robustness", "confidence_qualifier", "key_caveat"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You are a computational-oncology target-evaluation assistant. Your PURPOSE here is narrow: reason "
    "ACROSS the tumor-vs-normal SELECTIVITY evidence for a (target, indication) and judge HOW MUCH THIS "
    "LENS INFORMS whether the target has a therapeutic WINDOW — i.e. is it elevated in tumor over the "
    "matched/population normal, robustly across independent comparators? This is a SINGLE-LENS "
    "assessment. You NARRATE and INTEGRATE; you never invent facts and you never change the "
    "deterministic, rule-computed selectivity_class (it is FIXED upstream). "
    "WHAT 'SELECTIVITY' MEANS HERE: the tumor-vs-normal CONTRAST, distinct from ABUNDANCE. A target can "
    "be abundant yet non-selective (no window — presence's job, not this lens) or selective on a faint "
    "signal. Judge the window, not the level. "
    "REGISTER — write to scientific-publication standard: the voice of a methods/results section. "
    "Declarative, precise, and factual; complete sentences; active voice. Report each number with its "
    "scale and direction, never bare. Do NOT use promotional or editorialising language (avoid "
    "'promising', 'exciting', 'compelling', 'robustly', 'clearly'); let the evidence carry the claim. "
    "Concise but readable — a domain biologist who is not a statistician must follow it without a glossary. "
    "PLAIN-LANGUAGE METRICS — on FIRST use of any technical quantity, add a short parenthetical gloss so a "
    "non-computational reader can interpret it, e.g.: log2 fold-change (log2 of the tumor-vs-normal "
    "expression ratio; +1 = 2x higher in tumour, 0 = no difference); fraction-of-tumours-above-normal-p95 "
    "(share of tumour samples exceeding the 95th percentile of the normal distribution — a per-sample "
    "window measure); ComBat (a batch-effect correction applied to the adjacent-normal comparator); "
    "all-gene selectivity percentile (where this target's fold-change ranks among all genes in the "
    "indication). Gloss once, then use the term freely. "
    "ROBUSTNESS DISCIPLINE: a call concordant across TCGA-adjacent (raw + ComBat) and GTEx-population is "
    "stronger than one resting on a single comparator; discordance across comparators is a real caveat "
    "to foreground. State DATA_UNAVAILABLE gaps plainly — a null result is decision-useful. "
    "SCOPE DISCIPLINE: do NOT discuss therapeutic MODALITY, surface accessibility, dependency, or "
    "absolute expression level. Those belong to other lenses / the composed target-profile synthesis."
    + _EVIDENCE_ONLY_DIRECTIVE
)

# Deterministic plain-language legend for the metrics this narration cites — attached to the output
# as a sibling key (metric_legend) so a non-computational reader always has an accurate, byte-stable
# reference, independent of the LLM's inline glosses. Mirrors synthesis_dependency.METRIC_LEGEND.
METRIC_LEGEND = {
    "log2_fold_change": ("log2 of the tumour-vs-normal expression ratio. 0 = equal in tumour and "
                         "normal; +1 = 2x higher in tumour; -1 = 2x lower. The tumour-vs-normal "
                         "CONTRAST — distinct from absolute abundance."),
    "fraction_tumor_above_normal_p95": ("The share of tumour samples whose expression exceeds the "
                                        "95th percentile of the matched-normal distribution. A "
                                        "per-sample window measure: high = a clean tumour-high "
                                        "population above normal, even if medians overlap."),
    "distribution_overlap_tumor_normal": ("How much the tumour and normal expression distributions "
                                          "overlap (0 = fully separated, 1 = identical). Lower = a "
                                          "cleaner therapeutic window."),
    "comparator_cells": ("Independent tumour-vs-normal comparisons: TCGA tumour vs adjacent normal "
                         "(raw and ComBat batch-corrected) and tumour vs the GTEx normal-tissue "
                         "population. A call supported by more concordant comparators is stronger."),
    "selectivity_allgene_percentile": ("Where this target's tumour-vs-normal fold-change ranks among "
                                       "ALL genes in the indication (0-100). High = unusually "
                                       "selective relative to the transcriptome, not just elevated."),
}


def _fmt(v, nd=2):
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def build_user_prompt(decision: dict, subtype_query: Optional[str] = None) -> str:
    """Assemble the LLM input from the DETERMINISTIC selectivity decision spine. Narrates the
    computed selectivity call + cross-comparator robustness + per-sample corroboration, grounded
    in the actual headline fields the skill emits (verified against run.py::_headline)."""
    h = decision.get("headline", {}) or {}
    target = decision.get("target"); indication = decision.get("indication")
    card_list = decision.get("cards", [])
    cards = {c["card_id"]: (c.get("summary") or {}) for c in card_list}
    missing = {c["card_id"] for c in card_list if c.get("_missing")}
    tvn = cards.get("tumor-vs-normal-selectivity", {})

    def _tvn_state():
        return "DATA_UNAVAILABLE (measured, no usable value)" if \
            "tumor-vs-normal-selectivity" in missing else "measured"

    lines = [
        f"TARGET: {target}    INDICATION: {indication}",
        "",
        "DETERMINISTIC VERDICT (fixed — narrate, do not change):",
        f"  selectivity_class: {h.get('selectivity_class')}  (state: {_tvn_state()})",
        f"  dominant_direction: {h.get('dominant_direction')}   discordant: {h.get('discordant')}",
        # NORMAL-BREADTH VETO transparency: when the resolved verdict is selective_but_broadly_normal,
        # the raw axis-A (tumor-vs-tissue-of-origin) class was DOWNGRADED because there is no
        # therapeutic window vs the worst critical normal. Narrate the downgrade — do NOT re-assert the
        # pre-veto axis-A class as if it were the call.
        (f"  ⚠ NORMAL-BREADTH VETO APPLIED: axis-A was {h.get('axis_a_selectivity_class')} "
         f"(tumor-vs-origin over-expression) but was DOWNGRADED to {h.get('selectivity_class')} — "
         f"no therapeutic window vs the worst critical normal (driving_rule: {h.get('driving_rule_id')}). "
         f"This is the load-bearing selectivity conclusion; over-expression alone is NOT a window."
         if h.get("selectivity_class") == "selective_but_broadly_normal"
         else f"  axis_a_selectivity_class (raw tumor-vs-origin, pre-veto): {h.get('axis_a_selectivity_class')}"),
        "",
        "COMPARATOR ROBUSTNESS (how many independent tumor-vs-normal cells supported the call):",
        f"  cells_supporting / cells_ran: {h.get('cells_supporting')} / {h.get('cells_ran')}",
        f"  significant in ALL cells: {h.get('sig_all_cells')}",
        f"  max_abs_log2fc: {_fmt(h.get('max_abs_log2fc'))}",
        "",
        "ALL-GENE SELECTIVITY PERCENTILE (Axis-1 — where this target's fold-change sits among ALL",
        "genes in this indication; the relative-selectivity frame, if available):",
        f"  selectivity_allgene_percentile: {_fmt(tvn.get('selectivity_allgene_percentile'))} "
        f"({tvn.get('selectivity_allgene_percentile_class')})",
        f"  context: {tvn.get('selectivity_allgene_percentile_context')}",
        "",
        "PER-SAMPLE PERCENTILE-CROSSING (corroboration — fraction of tumors above the normal p95):",
        f"  percentile_crossing_class: {h.get('percentile_crossing_class')}",
        f"  fraction_tumor_above_normal_p95: {_fmt(h.get('fraction_tumor_above_normal_p95'))}",
        f"  distribution_overlap_tumor_normal: {_fmt(h.get('distribution_overlap_tumor_normal'))}",
        "",
        "TASK: using emit_selectivity_synthesis, judge how much the tumor-vs-normal SELECTIVITY lens "
        f"informs whether {target} has a therapeutic window in {indication}. Reason ACROSS the "
        "comparators + per-sample corroboration — do not just restate the verdict. If the target is "
        "present but NOT tumor-elevated over normal, say selectivity is UNINFORMATIVE for a window and "
        "the rationale must come from other lenses. Foreground comparator discordance if present. Do "
        "NOT discuss modality or absolute abundance. Ground every claim in the fields; state "
        "DATA_UNAVAILABLE gaps plainly.",
    ]
    return "\n".join(lines)


def synthesize_selectivity(decision: dict, model_id: Optional[str] = None,
                           subtype_query: Optional[str] = None) -> dict:
    """Run the opt-in selectivity narration over a composed decision. Returns the provenance-
    tagged llm_synthesis block. Raises are the CALLER's to handle (the dispatcher degrades to a
    note on failure — synthesis is never allowed to break the deterministic run)."""
    from _skills_common.llm import synthesize_structured
    user_prompt = build_user_prompt(decision, subtype_query=subtype_query)
    result = synthesize_structured(
        system_prompt=_SYSTEM,
        user_prompt=user_prompt,
        tool_name=SYNTHESIS_TOOL_NAME,
        tool_schema=SYNTHESIS_TOOL_SCHEMA,
        model_id=model_id,
    )
    # Attach the deterministic plain-language metric legend (sibling key), on a successful
    # narration only — a degraded {_synthesis_error} block stays minimal. Mirrors synthesis_dependency.
    if isinstance(result, dict) and "_synthesis_error" not in result:
        result.setdefault("metric_legend", METRIC_LEGEND)
    return result
