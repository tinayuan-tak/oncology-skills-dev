"""synthesis_dependency — opt-in LLM narration for the functional-requirement (dependency) lens.

Sibling of _skills_common/synthesis_selectivity.py + synthesis_genomic.py, same TWO-SLOT contract:
  SLOT 1 (deterministic, byte-stable): decision["headline"]["dependency_verdict"] +
    driving_rule_id + every dependency card field. Built upstream; this module NEVER writes to it.
  SLOT 2 (llm, provenance-tagged): decision["llm_synthesis"], a SIBLING key attached
    AFTER the decision is composed — structurally impossible to alter the verdict.

The LLM NARRATES the rank-ordered dependency verdict + how it holds up across the FULL evidence
set (CRISPR + RNAi + concordance + lineage-selectivity + paralog-buffering + PRISM chemical-genetic
confirmation + predictability confidence) PLUS the two contextualized axes this hardening added:
  Axis-2 the control-benchmark position (pan-essential ceiling vs non-essential floor), and
  Axis-3 the across-lineage variance-explained omnibus (ε²).
It NEVER mints or flips the dependency_verdict.

SINGLE-LENS scope: judge how much the DEPENDENCY (genetic requirement) evidence supports pursuing
the target — is it a real, SELECTIVE genetic dependency (a therapeutic window), a pan-essential
(broad-tox liability, NOT a win), or non-dependent? Do NOT assess expression, mutation, or
therapeutic modality (those are other lenses / the composed target-profile's job).

FULL-EVIDENCE discipline (the H1 "drops-nulls" lesson from project_synthesis_layer_review): this
narrator reads the WHOLE dependency card set, each in one of three states
(present / DATA_UNAVAILABLE / not-present-this-run), so a measured null is decision-useful, never
silently dropped. Field names are the ACTUAL keys functional-requirement/scripts/run.py::_headline
emits (feedback_synthesis_reader_real_field_names).
"""
from __future__ import annotations

from typing import Optional

SYNTHESIS_TOOL_NAME = "emit_dependency_synthesis"
SYNTHESIS_TOOL_SCHEMA = {
    "type": "object",
    "description": ("Assess, from the DEPENDENCY (genetic-requirement) lens ALONE, how much this lens "
                    "informs whether the target is worth pursuing in this cancer. Reason ACROSS the "
                    "gathered evidence (CRISPR + RNAi + concordance + lineage + paralog-buffering + "
                    "PRISM chemical-genetic confirmation + predictability) and the control-benchmark + "
                    "lineage-omnibus context; do NOT restate a different verdict, and do NOT assess "
                    "expression, mutation, or therapeutic modality (other lenses' job)."),
    "properties": {
        "dependency_relevance_for_target": {
            "type": "string",
            "enum": ["strongly_supports", "supports_with_caveats", "neutral_uninformative",
                     "argues_against"],
            "description": ("The headline judgment: how much does the DEPENDENCY evidence support "
                            "pursuing this target? strongly_supports = a real, SELECTIVE genetic "
                            "dependency (a therapeutic window) corroborated across assays. "
                            "supports_with_caveats = dependency present but qualified (single assay, "
                            "CRISPR/RNAi discordant, paralog-buffered, lineage-restricted, underpowered). "
                            "neutral_uninformative = not distinguishing (non-dependent pooled, or "
                            "insufficient) — dependency is NOT the reason to pursue; rationale must come "
                            "from other lenses. argues_against = evidence against a tractable dependency, "
                            "INCLUDING a PAN-ESSENTIAL read (broad-tox liability — being as essential as "
                            "ribosomal/proteasome controls argues AGAINST, it is not a win). A SINGLE-LENS "
                            "read; it informs confidence, NEVER mints or flips the verdict.")},
        "dependency_rationale": {
            "type": "string",
            "description": ("2-4 sentences in a scientific-publication register (Results/Discussion voice: "
                            "declarative, factual, no promotional adjectives such as 'promising' or "
                            "'exciting'). Integrate the deterministic dependency_verdict, the CRISPR and "
                            "RNAi calls and their agreement, lineage-selectivity, paralog buffering, and "
                            "any PRISM chemical-genetic confirmation. State plainly whether the target is a "
                            "SELECTIVE dependency, a PAN-ESSENTIAL gene (a broad-toxicity liability), or "
                            "non-dependent, and foreground assay disagreement where present. On FIRST use "
                            "of a technical metric, gloss it in plain language for a non-computational "
                            "reader — e.g. 'CRISPR knockout fitness score (Chronos; 0 = no effect on "
                            "growth, about -1 = a typically essential gene, more negative = stronger "
                            "dependency)'. Report numbers with their scale, not bare. Ground every claim in "
                            "the provided fields; state DATA_UNAVAILABLE gaps rather than omitting them.")},
        "selectivity_vs_pan_essential_read": {
            "type": "string",
            "description": ("1-2 sentences, same publication register, on the central distinction: is this "
                            "a SELECTIVE dependency (required in the relevant tumour context but not in all "
                            "cells — a therapeutic window) or a PAN-ESSENTIAL liability (required in "
                            "essentially all cells, including normal tissue)? Ground it in the "
                            "control-benchmark position (where the target's knockout score sits between the "
                            "pan-essential 'ceiling' and non-essential 'floor') and the across-lineage "
                            "effect size (ε², the fraction of dependency variation explained by lineage; "
                            "gloss it in plain language). A pan-essential read is a safety concern, not a "
                            "target advantage — state that plainly. Do not assert a window the controls do "
                            "not support.")},
        "confidence_qualifier": {
            "type": "string",
            "enum": ["well_supported", "supported_with_caveats", "weakly_supported",
                     "insufficient_evidence"],
            "description": ("How completely the available evidence supports the relevance read above "
                            "(assay agreement, screen panel size/power, predictability, paralog and PRISM "
                            "coverage). A confidence read on the EVIDENCE — it does not change the "
                            "deterministic verdict.")},
        "key_caveat": {
            "type": "string",
            "description": ("The single most important limitation a reader should carry, stated factually "
                            "in one sentence (e.g. CRISPR/RNAi disagreement, paralog buffering, an "
                            "underpowered pooled screen, pan-essential toxicity, lineage-restricted "
                            "signal, or a predictability gap), or 'none' if none.")},
    },
    "required": ["dependency_relevance_for_target", "dependency_rationale",
                 "selectivity_vs_pan_essential_read", "confidence_qualifier", "key_caveat"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You are a computational-oncology analyst writing the dependency section of a target-evaluation "
    "dossier. Reason ACROSS the DEPENDENCY (genetic-requirement) evidence for a (target, indication) and "
    "judge how much this lens informs whether the target is worth pursuing — is it a real, SELECTIVE "
    "genetic dependency (a therapeutic window), a PAN-ESSENTIAL gene, or non-dependent? This is a "
    "single-lens assessment. You NARRATE and INTEGRATE the provided fields; you never invent facts and "
    "you never change the deterministic, rule-computed dependency_verdict or class labels (they are FIXED "
    "upstream). "
    "REGISTER — write to scientific-publication standard: the voice of a methods/results section. "
    "Declarative, precise, and factual; complete sentences; active voice. Report each number with its "
    "scale and direction, never bare. Do NOT use promotional or editorialising language (avoid "
    "'promising', 'exciting', 'compelling', 'robustly', 'clearly'); let the evidence carry the claim. "
    "Concise but readable — a domain biologist who is not a statistician must follow it without a glossary. "
    "PLAIN-LANGUAGE METRICS — on FIRST use of any technical quantity, add a short parenthetical gloss so a "
    "non-computational reader can interpret it, e.g.: CRISPR/Chronos knockout fitness score (0 = knocking "
    "out the gene does not affect growth; ~ -1 = the effect seen for a typically essential gene; more "
    "negative = a stronger dependency); RNAi/DEMETER2 (an independent knockDOWN measure of the same "
    "requirement); epsilon-squared / ε² (the fraction of the dependency's variation across lineages that "
    "lineage explains, 0-1; ~0.01 negligible, ~0.06 moderate, ~0.14 large); ohnolog (a paralogue arising "
    "from ancient whole-genome duplication). Gloss once, then use the term freely. "
    "THE CENTRAL DISTINCTION — SELECTIVE vs PAN-ESSENTIAL (this inverts the usual reading): a dependency "
    "is a favourable target signal only if it is SELECTIVE — required in the relevant tumour context but "
    "sparing normal tissue. A pan-essential gene (as essential as the ribosomal / proteasome / "
    "core-machinery controls; knockout fitness score deep and uniform across lineages) is a broad-toxicity "
    "liability, not an advantage — inhibiting it would affect all dividing cells. A read at the "
    "pan-essential control level therefore argues AGAINST the target on this lens; the favourable position "
    "is BETWEEN the control bands (dependent, but not pan-essential). State this plainly; do not present "
    "pan-essentiality as support. "
    "ASSAY AGREEMENT: CRISPR (knockout) and RNAi (knockdown) probe loss-of-function by independent "
    "mechanisms; concordance between them strengthens the call, and discordance is a limitation to state "
    "explicitly. A buffering paralogue, an underpowered pooled screen, or a signal confined to one lineage "
    "each qualify the call. Report DATA_UNAVAILABLE gaps plainly — a measured null is informative. "
    "SCOPE: address only the dependency lens. Do not discuss expression level, mutation/alteration status, "
    "or therapeutic modality (small-molecule / degrader / ADC / etc.); those belong to other sections of "
    "the dossier."
)

# Deterministic plain-language legend for the metrics the narration cites. Attached to the output
# as a SIBLING key (metric_legend) so a non-computational reader always has an accurate, byte-stable
# reference — independent of what the LLM writes (the model may gloss inline, but this guarantees a
# correct definition and cannot drift or hallucinate). Ordered from most- to least-referenced.
METRIC_LEGEND = {
    "chronos_score": ("CRISPR knockout fitness score (Chronos). 0 = knocking the gene out does not "
                      "change cell growth; about -1 = the depletion seen for a typically essential "
                      "gene; more negative = a stronger dependency. Values are medians across the "
                      "screened cell-line panel."),
    "rnai_demeter2": ("An independent knockDOWN measure of the same gene requirement (RNAi, DEMETER2 "
                      "score). Agreement between the CRISPR knockout and RNAi knockdown reads "
                      "strengthens a dependency call; disagreement is a caveat."),
    "dep_control_position": ("Where the target's knockout fitness score sits relative to curated "
                             "control genes on the same scale: the pan-essential 'ceiling' (genes "
                             "essential in nearly all cells, e.g. ribosomal/proteasome) and the "
                             "non-essential 'floor' (genes with no fitness effect). 'between_controls' "
                             "= a selective dependency (the favourable position); "
                             "'as_essential_as_pan_essential' = a broad-toxicity liability, not a win; "
                             "'non_dependent_near_negatives' = no dependency."),
    "epsilon_squared": ("ε² (epsilon-squared): the fraction of the dependency's variation across "
                        "lineages that lineage membership explains, from 0 to 1. Rough bands: below "
                        "~0.06 negligible (dependency is similar across lineages), ~0.06-0.14 "
                        "moderate, above ~0.14 large (dependency is concentrated in particular "
                        "lineages). A pan-essential gene reads negligible (uniformly essential)."),
    "paralog_buffering": ("A paralogue (a related gene with overlapping function) can compensate when "
                          "the target alone is knocked out, masking a true dependency in single-gene "
                          "screens. 'strong'/'partial' buffering flags this; an ohnolog partner "
                          "(from ancient whole-genome duplication) is the highest-confidence case."),
    "predictability": ("Whether the dependency can be predicted from the cell lines' molecular "
                       "features, and from which feature. 'own_omics_driven' means the target's own "
                       "profile predicts it (a candidate patient-selection biomarker); this is a "
                       "confidence annotation on the call, not the call itself."),
}


def _fmt(v, nd=2):
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def build_user_prompt(decision: dict, subtype_query: Optional[str] = None) -> str:
    """Assemble the LLM input from the DETERMINISTIC dependency decision spine. Narrates the
    rank-ordered verdict grounded in the FULL gathered evidence (not just the verdict) + the two
    contextualized axes. Field names are the ACTUAL keys functional-requirement/scripts/run.py::
    _headline emits, and each card is rendered in one of THREE states (present / DATA_UNAVAILABLE /
    not-present) so a measured null is never silently dropped (the H1 drops-nulls lesson)."""
    h = decision.get("headline", {}) or {}
    target = decision.get("target"); indication = decision.get("indication")
    card_list = decision.get("cards", [])
    cards = {c["card_id"]: (c.get("summary") or {}) for c in card_list}
    present_ids = {c["card_id"] for c in card_list}
    missing = {c["card_id"] for c in card_list if c.get("_missing")}

    def _card_state(card_id: str) -> str:
        if card_id in missing:
            return "DATA_UNAVAILABLE (measured, no usable value)"
        if card_id not in present_ids:
            return "not present in this run"
        return "measured"

    # Axis-2 control-benchmark + Axis-3 lineage-omnibus live in the two distribution/lineage card
    # summaries (display-only fields the readers now emit).
    crispr = cards.get("pan-cancer-crispr-dependency-distribution", {})
    lineage = cards.get("dependency-lineage-selectivity", {})

    lines = [
        f"TARGET: {target}    INDICATION: {indication}",
        "",
        "DETERMINISTIC VERDICT (fixed — narrate, do not change):",
        f"  dependency_verdict: {h.get('dependency_verdict')}  (driving_rule: {h.get('driving_rule_id')})",
        "",
        "GENETIC EVIDENCE — the full gathered read (cite measured values; a null is decision-useful):",
        f"  CRISPR call:  {h.get('crispr_call')}   "
        f"(pan-cancer-crispr-dependency-distribution: {_card_state('pan-cancer-crispr-dependency-distribution')})",
        f"  RNAi call:    {h.get('rnai_call')}   "
        f"(pan-cancer-rnai-dependency-distribution: {_card_state('pan-cancer-rnai-dependency-distribution')})",
        f"  concordance:  {h.get('concordance_call')}   "
        f"(crispr-rnai-dependency-concordance: {_card_state('crispr-rnai-dependency-concordance')}) "
        "— do CRISPR + RNAi AGREE?",
        f"  lineage_selectivity: {h.get('lineage_selectivity')}   "
        f"(dependency-lineage-selectivity: {_card_state('dependency-lineage-selectivity')})",
        "",
        "PARALOG BUFFERING (a paralog can mask the single-gene KO → false non-dependence):",
        f"  paralog_buffering_class: {h.get('paralog_buffering_class')}   "
        f"strongest_paralog: {h.get('strongest_paralog_symbol')}   "
        f"(paralog-buffering: {_card_state('paralog-buffering')})",
        "",
        "CHEMICAL-GENETIC CONFIRMATION (PRISM compound kill tracking CRISPR+RNAi dependency):",
        f"  (prism-crispr-concordance: {_card_state('prism-crispr-concordance')})",
        "",
        "PREDICTABILITY (META-evidence — how omics-learnable is this dependency; a CONFIDENCE handle):",
        f"  predictability_class: {h.get('predictability_class')}  "
        f"dominant_feature: {h.get('pred_dominant_feature_class')}",
        f"  dependency_confidence: {h.get('dependency_confidence')} — {h.get('dependency_confidence_note')}",
        "",
        "AXIS-2 — CONTROL-BENCHMARK POSITION (INVERTED: near pan-essential = tox liability, NOT a win):",
        f"  dep_control_position_class: {crispr.get('dep_control_position_class')}",
        f"  dep_control_position: {crispr.get('dep_control_position')}",
        f"  target median Chronos: {_fmt(crispr.get('dep_control_target_chronos'))}  "
        f"(pan-essential ceiling {_fmt(crispr.get('dep_control_pan_essential_ceiling'))}, "
        f"non-essential floor {_fmt(crispr.get('dep_control_non_essential_floor'))})",
        f"  context: {crispr.get('dep_control_position_context')}",
        "",
        "AXIS-3 — ACROSS-LINEAGE OMNIBUS (is the dependency concentrated by lineage, or uniform?):",
        f"  lineage_omnibus_effect_size_class: {lineage.get('lineage_omnibus_effect_size_class')}  "
        f"(variance_explained ε²={_fmt(lineage.get('lineage_variance_explained'), 3)})",
        f"  which_lineages_separate: {lineage.get('which_lineages_separate')}",
        f"  enrichment_class (per-lineage threshold view): {lineage.get('enrichment_class')}",
        "",
        "PATIENT↔MODEL CORROBORATION (render facet — is the dependency backed by lineage-matched models?):",
        f"  model_correspondence_class: {h.get('model_correspondence_class')}  "
        f"n_positive_models_in_lineage: {h.get('n_positive_models_in_lineage')}",
        "",
        "TASK: using emit_dependency_synthesis, judge how much the DEPENDENCY lens informs whether "
        f"{target} is worth pursuing in {indication}. Reason ACROSS the evidence — do not just restate "
        "the verdict. Foreground the SELECTIVE-vs-PAN-ESSENTIAL distinction: a pan-essential read "
        "(as_essential_as_pan_essential + negligible lineage ε²) ARGUES AGAINST the target (broad tox), "
        "it is NOT support. If CRISPR and RNAi disagree, or a paralog buffers, or the pooled call is "
        "underpowered, foreground that. If the target is non-dependent/insufficient, say dependency is "
        "UNINFORMATIVE and the rationale must come from other lenses. Do NOT discuss expression, "
        "mutation, or modality. Ground every claim in the fields; state DATA_UNAVAILABLE gaps plainly.",
    ]
    return "\n".join(lines)


def synthesize_dependency(decision: dict, model_id: Optional[str] = None,
                          subtype_query: Optional[str] = None) -> dict:
    """Run the opt-in dependency narration over a composed decision. Returns the provenance-tagged
    llm_synthesis block. Raises are the CALLER's to handle (the dispatcher degrades to a note on
    failure — synthesis is never allowed to break the deterministic run)."""
    from _skills_common.llm import synthesize_structured
    user_prompt = build_user_prompt(decision, subtype_query=subtype_query)
    result = synthesize_structured(
        system_prompt=_SYSTEM,
        user_prompt=user_prompt,
        tool_name=SYNTHESIS_TOOL_NAME,
        tool_schema=SYNTHESIS_TOOL_SCHEMA,
        model_id=model_id,
    )
    # Attach the deterministic plain-language metric legend as a sibling key, so a
    # non-computational reader always has an accurate reference for the quantities the narration
    # cites — independent of (and not overridable by) the LLM's inline glosses. Only attach on a
    # successful narration (a degraded {_synthesis_error} block stays minimal + diagnostic).
    if isinstance(result, dict) and "_synthesis_error" not in result:
        result.setdefault("metric_legend", METRIC_LEGEND)
    return result
