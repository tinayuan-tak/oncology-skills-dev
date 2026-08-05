"""synthesis — opt-in LLM narration over a DETERMINISTIC decision spine.

The final, optional layer of the contextualized-interpretation enhancement. It
NARRATES the deterministic rule-fired verdict + the contextualized interpretation
axes (all-gene percentile, control-benchmark position, across-subtype effect size)
that the skill already computed — it does NOT re-derive interpretation from raw
numbers, and it NEVER mints or flips a verdict.

TWO-SLOT DESIGN (mirrors target-profile's proven pattern — see _skills_common/llm.py):
  SLOT 1 (deterministic, byte-stable): decision["headline"]["presence_verdict"] +
    presence_verdict_by_modality + every card field. Built upstream; this module
    NEVER writes to it.
  SLOT 2 (llm, provenance-tagged): decision["llm_synthesis"]. A SIBLING key attached
    AFTER the decision is composed, so it is structurally impossible for the narration
    to alter the verdict. Every field carries _source: llm_synthesized / _model_id /
    _prompt_hash (via _skills_common.llm.synthesize_structured).

The LLM consumes the CONTEXTUALIZED outputs as INPUTS ("here is where the target sits
vs all genes / vs controls / across subtypes — explain why that matters for this
target") rather than the raw distributions — which keeps its job interpretation-of-
interpretation, not re-computation (the latter would reintroduce non-reproducibility).

OPT-IN: only runs when the caller passes --synthesize. A run WITHOUT the flag emits a
decision.json that is byte-identical to the pre-synthesis artifact.
"""
from __future__ import annotations

from typing import Optional

# The structured-output contract. Categorical fields use fixed enums so the narration
# stays validatable; free-text fields are bounded. The LLM must call THIS tool.
SYNTHESIS_TOOL_NAME = "emit_presence_synthesis"
SYNTHESIS_TOOL_SCHEMA = {
    "type": "object",
    "description": ("Narrate the tumor-presence read for a (target, indication): a concise "
                    "interpretation of the DETERMINISTIC verdict in light of the contextualized "
                    "axes (all-gene percentile, control-benchmark position, subtype effect). "
                    "Do NOT contradict or restate a different verdict — explain the one given."),
    "properties": {
        "headline_narrative": {
            "type": "string",
            "description": ("2-4 sentences. What the presence read MEANS for this target in this "
                            "indication, grounding every claim in the provided fields (cite the "
                            "percentile / control position / subtype effect). Neutral, decision-useful.")},
        "abundance_interpretation": {
            "type": "string",
            "description": ("1-2 sentences on the all-gene percentile + control_position: is the "
                            "target abundant RELATIVE to all genes and to known antigens? Name the "
                            "control comparison (e.g. 'above all positive controls').")},
        "subtype_interpretation": {
            "type": "string",
            "description": ("1-2 sentences on the across-subtype effect (subtype_effect_size_class + "
                            "which_subtypes_separate): is subtype a patient-selection axis, and which "
                            "stratum stands out? If data_unavailable/negligible, say so plainly.")},
        "confidence_qualifier": {
            "type": "string",
            "enum": ["well_supported", "supported_with_caveats", "weakly_supported",
                     "insufficient_evidence"],
            "description": ("How well the CONTEXTUALIZED evidence supports the deterministic verdict. "
                            "This is a CONFIDENCE read on the existing verdict — it does NOT change it.")},
        "key_caveat": {
            "type": "string",
            "description": ("The single most important caveat a reviewer should carry (purity confound, "
                            "coverage gap, proxy-normal, subtype underpowering, etc.), or 'none' if none.")},
    },
    "required": ["headline_narrative", "abundance_interpretation", "subtype_interpretation",
                 "confidence_qualifier", "key_caveat"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You are a computational-oncology target-evaluation assistant. You NARRATE a "
    "deterministic, rule-computed tumor-presence verdict — you never invent, contradict, "
    "or re-rank it. Every claim you make must be grounded in the numeric fields provided; "
    "do not introduce facts not present in the input. The verdict and all class labels are "
    "FIXED upstream; your job is to explain what they mean, in light of the contextualized "
    "interpretation axes (percentile among all genes, position vs known control antigens, "
    "and across-subtype effect size). Be concise, neutral, and decision-useful. If an axis "
    "is data_unavailable, say so plainly rather than speculating."
)


def _fmt(v, nd=1):
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def build_user_prompt(decision: dict) -> str:
    """Assemble the LLM input from the DETERMINISTIC decision spine. Pulls the verdict +
    the contextualized axes out of the headline (and the cards for the control detail), so
    the model narrates the computed interpretation, never the raw distributions."""
    h = decision.get("headline", {}) or {}
    target = decision.get("target"); indication = decision.get("indication")
    # locate the contextualized fields (they live on the card summaries + are partly
    # elevated into the headline). Read defensively — any may be absent.
    cards = {c["card_id"]: (c.get("summary") or {}) for c in decision.get("cards", [])}
    tumor_rna = cards.get("tumor-rna-distribution", {})
    subtype = cards.get("tumor-rna-distribution-by-subtype", {})

    lines = [
        f"TARGET: {target}    INDICATION: {indication}",
        "",
        "DETERMINISTIC VERDICT (fixed — narrate, do not change):",
        f"  presence_verdict: {h.get('presence_verdict')}  (driving_rule: {h.get('driving_rule_id')})",
        "",
        "AXIS 1 — ALL-GENE PERCENTILE (where the target sits among ALL genes in this context):",
        f"  tumor all-gene percentile: {_fmt(tumor_rna.get('allgene_percentile'))} "
        f"({tumor_rna.get('allgene_percentile_class')})",
        f"  context: {tumor_rna.get('allgene_percentile_context')}",
        "",
        "AXIS 2 — CONTROL-BENCHMARK POSITION (vs known positive/negative antigens, same scale):",
        f"  control_position_class: {tumor_rna.get('control_position_class')}",
        f"  control_position: {tumor_rna.get('control_position')}",
        f"  positive controls (percentile): {tumor_rna.get('control_positives')}",
        f"  negative controls (percentile): {tumor_rna.get('control_negatives')}",
        f"  negatives excluded (lineage-conflict): {tumor_rna.get('control_negatives_excluded_lineage_conflict')}",
        "",
        "AXIS 3 — ACROSS-SUBTYPE EFFECT (is subtype a patient-selection axis?):",
        f"  subtype_effect_size_class: {subtype.get('subtype_effect_size_class')}  "
        f"(variance_explained ε²={_fmt(subtype.get('subtype_variance_explained'), 3)})",
        f"  which_subtypes_separate: {subtype.get('which_subtypes_separate')}",
        f"  subtype_stratification_class: {subtype.get('subtype_stratification_class')}",
        "",
        "SUPPORTING CONTEXT:",
        f"  tumor_expression_class: {tumor_rna.get('tumor_expression_class')}  "
        f"median_log2tpm: {_fmt(tumor_rna.get('median_log2tpm'), 2)}",
        f"  purity_confound_class: {h.get('purity_confound_class')}",
        "",
        "Narrate this read using emit_presence_synthesis. Ground every claim in the fields above.",
    ]
    return "\n".join(lines)


def synthesize_presence(decision: dict, model_id: Optional[str] = None) -> dict:
    """Run the opt-in narration over a composed decision. Returns the provenance-tagged
    llm_synthesis block (to be attached as decision['llm_synthesis']). Raises are the
    CALLER's to handle (the dispatcher degrades to a note on failure — synthesis is
    never allowed to break the deterministic run)."""
    from _skills_common.llm import synthesize_structured
    user_prompt = build_user_prompt(decision)
    return synthesize_structured(
        system_prompt=_SYSTEM,
        user_prompt=user_prompt,
        tool_name=SYNTHESIS_TOOL_NAME,
        tool_schema=SYNTHESIS_TOOL_SCHEMA,
        model_id=model_id,
    )
