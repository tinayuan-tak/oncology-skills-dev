"""synthesis_tractability_sm — opt-in LLM narration for the tractability-small-molecule lens.

Sibling of _skills_common/synthesis_dependency.py + synthesis_surface_modality.py, same TWO-SLOT contract:
  SLOT 1 (deterministic, byte-stable): decision["headline"]["druggability_snapshot"] + driving_rule_id +
    the additive degrader_snapshot + every tractability card field. Built upstream; NEVER written here.
  SLOT 2 (llm, provenance-tagged): decision["llm_synthesis"], a SIBLING key attached AFTER the decision
    is composed — structurally impossible to alter the verdict.

The LLM NARRATES the composed druggability_snapshot (well_covered / chemically_confirmed_genetic /
chemically_active / tool_compound_only / weakly_active / discordant / structurally_ligandable /
structurally_intractable / chemically_unhit / insufficient) across the small-molecule evidence: PRISM
chemical activity (has a compound actually hit it?), PRISM↔CRISPR/RNAi concordance (is the chemical
effect ON-TARGET, or off-target/discordant?), forward structural ligandability (a druggable pocket even
absent a compound — the KRAS-G12C-before-sotorasib case), and the omics-predictability confidence handle.
It also narrates the additive DEGRADER read (degradation = KO-like complete removal ≠ catalytic
inhibition; a dependency without a pocket can still be a degrader prospect). It NEVER mints or flips the
druggability_snapshot.

SINGLE-LENS scope: judge how much the SMALL-MOLECULE tractability evidence supports pursuing the target
with an SM (or degrader) — is there a real, ON-TARGET chemical handle, a druggable pocket, or neither? Do
NOT assess genetic dependency magnitude, surface/biologics modality, expression, or mutation (other lenses).

FULL-EVIDENCE discipline (H1 drops-nulls): reads the WHOLE tractability card set, each present /
DATA_UNAVAILABLE / not-present. Field names are the ACTUAL keys tractability-small-molecule/scripts/
run.py::_headline emits (feedback_synthesis_reader_real_field_names).
"""
from __future__ import annotations

from typing import Optional

SYNTHESIS_TOOL_NAME = "emit_tractability_sm_synthesis"
SYNTHESIS_TOOL_SCHEMA = {
    "type": "object",
    "description": ("Assess, from the SMALL-MOLECULE tractability lens ALONE, how much this lens informs "
                    "whether the target is druggable by a small molecule (or degrader) in this cancer. "
                    "Reason ACROSS the gathered evidence (PRISM chemical activity, PRISM↔CRISPR/RNAi "
                    "concordance / on-target engagement, forward structural ligandability, omics "
                    "predictability); do NOT restate a different verdict, and do NOT assess genetic "
                    "dependency magnitude, surface/biologics modality, expression, or mutation."),
    "properties": {
        "tractability_relevance_for_target": {
            "type": "string",
            "enum": ["strongly_supports", "supports_with_caveats", "neutral_uninformative",
                     "argues_against"],
            "description": ("The headline judgment: how much does the SMALL-MOLECULE evidence support "
                            "pursuing this target? strongly_supports = a compound has hit it AND the "
                            "chemical effect is on-target (tracks CRISPR/RNAi), or a clearly druggable "
                            "pocket exists. supports_with_caveats = qualified (tool-compound-only, weakly "
                            "active, or a pocket without a compound yet — forward ligandability). "
                            "neutral_uninformative = no compound found and no structural handle "
                            "(chemically_unhit / insufficient) — SM is NOT the reason to pursue; rationale "
                            "must come from other lenses. argues_against = evidence against a tractable SM "
                            "handle, INCLUDING a DISCORDANT read (compound active but off-target — its "
                            "effect is mechanistically unlinked) or a measured structural-intractability "
                            "(disordered/low-confidence fold). A SINGLE-LENS read; informs confidence, "
                            "NEVER mints or flips the verdict.")},
        "tractability_rationale": {
            "type": "string",
            "description": ("2-4 sentences in a scientific-publication register (Results/Discussion voice: "
                            "declarative, factual, no promotional adjectives such as 'promising' or "
                            "'exciting'). Integrate the deterministic druggability_snapshot, the PRISM "
                            "chemical activity, whether that activity is ON-TARGET (PRISM↔CRISPR/RNAi "
                            "concordance) or discordant/off-target, any forward structural ligandability "
                            "(a druggable pocket absent a compound), and the omics-predictability "
                            "confidence. On FIRST use of a technical term, gloss it in plain language — "
                            "e.g. 'PRISM (a pooled screen measuring how strongly each of hundreds of "
                            "compounds kills each cell line)'. Ground every claim in the provided fields; "
                            "state DATA_UNAVAILABLE gaps rather than omitting them.")},
        "on_target_vs_structural_read": {
            "type": "string",
            "description": ("1-2 sentences, same publication register, on the central SM distinction: is "
                            "there a RETROSPECTIVE on-target chemical handle (a compound has hit the target "
                            "AND the effect tracks the genetic dependency — the strongest evidence), a "
                            "FORWARD structural handle only (a druggable pocket but no compound yet — a "
                            "genuine prospect, e.g. KRAS-G12C before sotorasib), or NEITHER? Foreground a "
                            "DISCORDANT read explicitly: chemical activity that does NOT track CRISPR/RNAi "
                            "signals an off-target effect and does not count as tractability. Also give the "
                            "additive DEGRADER read where relevant (degradation removes the whole protein — "
                            "KO-like — so a dependency without a catalytic pocket can still be a degrader "
                            "prospect), noting the degrader machinery check is not yet assessed.")},
        "confidence_qualifier": {
            "type": "string",
            "enum": ["well_supported", "supported_with_caveats", "weakly_supported",
                     "insufficient_evidence"],
            "description": ("How completely the available evidence supports the relevance read above (compound "
                            "coverage, concordance strength, structural-model quality, predictability). A "
                            "confidence read on the EVIDENCE — it does not change the deterministic verdict.")},
        "key_caveat": {
            "type": "string",
            "description": ("The single most important limitation a reader should carry, stated factually in "
                            "one sentence (e.g. tool-compound-only activity, PRISM↔CRISPR discordance / "
                            "off-target concern, a pocket with no compound yet, an absent/low-confidence "
                            "structural model, or a predictability gap), or 'none' if none.")},
    },
    "required": ["tractability_relevance_for_target", "tractability_rationale",
                 "on_target_vs_structural_read", "confidence_qualifier", "key_caveat"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You are a computational-oncology analyst writing the small-molecule tractability section of a "
    "target-evaluation dossier. Reason ACROSS the SMALL-MOLECULE evidence for a (target, indication) and "
    "judge how much this lens informs whether the target is druggable by a small molecule (or degrader) — "
    "is there a real, ON-TARGET chemical handle, a druggable pocket, or neither? This is a single-lens "
    "assessment. You NARRATE and INTEGRATE the provided fields; you never invent facts and you never change "
    "the deterministic, rule-computed druggability_snapshot / degrader_snapshot (they are FIXED upstream). "
    "REGISTER — write to scientific-publication standard: the voice of a methods/results section. "
    "Declarative, precise, factual; complete sentences; active voice. Report each value with its meaning, "
    "never bare. Do NOT use promotional or editorialising language (avoid 'promising', 'exciting', "
    "'compelling', 'robustly', 'clearly'); let the evidence carry the claim. Concise but readable — a "
    "domain biologist who is not a chemist or computational specialist must follow it without a glossary. "
    "PLAIN-LANGUAGE TERMS — on FIRST use of any technical term, add a short parenthetical gloss, e.g.: "
    "PRISM (a pooled screen measuring how strongly each of hundreds of small molecules kills each cell "
    "line); chemical-genetic concordance (whether a compound's kill pattern tracks the CRISPR/RNAi genetic "
    "dependency — agreement indicates the compound acts ON its intended target rather than off-target); "
    "forward ligandability (a druggable pocket predicted from protein STRUCTURE even before any compound "
    "is known); degrader (a molecule that tags the whole protein for destruction — KO-like complete "
    "removal, unlike a catalytic inhibitor). Gloss once, then use freely. "
    "THE CENTRAL DISTINCTION — ON-TARGET CHEMICAL vs FORWARD STRUCTURAL vs NEITHER: the strongest SM "
    "evidence is RETROSPECTIVE and on-target — a compound has actually hit the target AND its effect "
    "tracks the genetic dependency (chemical-genetic concordance). A FORWARD structural handle (a "
    "druggable pocket with no compound yet) is a real but weaker prospect (the KRAS-G12C switch-II pocket "
    "before sotorasib). Chemical activity that is DISCORDANT with the genetic dependency signals an "
    "OFF-TARGET effect and argues AGAINST tractability — do not present it as support. A measured "
    "structural intractability (disordered / low-confidence fold, no pocket) is a negative read. "
    "DEGRADER LENS: degradation models COMPLETE protein removal (KO-like), so a target with a genetic "
    "dependency but no catalytic pocket can still be a degrader prospect; note that the full degrader "
    "machinery check (E3 ligase / CRBN / VHL / proteasome) is not yet assessed. Report DATA_UNAVAILABLE "
    "gaps plainly — a measured null is informative. "
    "SCOPE: address only the small-molecule tractability lens. Do not discuss genetic dependency magnitude, "
    "surface / biologics modality (ADC / TCE / antibody), expression level, or mutation/alteration status; "
    "those belong to other sections of the dossier."
)

# Deterministic plain-language legend (attached as a SIBLING key; see synthesis_dependency).
METRIC_LEGEND = {
    "druggability_snapshot": ("The composed small-molecule tractability call: from strongest to weakest — "
                              "well_covered / chemically_confirmed_genetic / chemically_active / "
                              "tool_compound_only / weakly_active (a compound hits it, in decreasing "
                              "strength); discordant (compound active but OFF-target); "
                              "structurally_ligandable (a druggable pocket, no compound yet); "
                              "structurally_intractable / chemically_unhit / insufficient (no handle). "
                              "Computed by rule; the narration explains it, it does not change it."),
    "prism_activity_class": ("PRISM chemical activity — whether any of the hundreds of screened small "
                             "molecules kills cell lines dependent on the target. A pooled compound-"
                             "sensitivity screen; the primary RETROSPECTIVE evidence a compound exists."),
    "prism_crispr_concord": ("Chemical-genetic concordance: whether the PRISM compound kill pattern TRACKS "
                             "the CRISPR/RNAi genetic dependency. Agreement indicates the compound acts ON "
                             "its intended target; discordance signals an off-target effect (argues "
                             "against tractability)."),
    "hotspot_pocket_adjacency": ("Forward structural ligandability — whether the protein STRUCTURE (PDB / "
                                 "AlphaFold) presents a druggable pocket, and whether a mutation hotspot "
                                 "sits in or beside it, even absent a known compound (the KRAS-G12C "
                                 "switch-II case). A prospective SM handle."),
    "pdb_coverage_class": ("How much of the protein has an experimental 3-D structure (PDB) — structural "
                           "confidence for the ligandability read; low coverage falls back to AlphaFold "
                           "prediction (a caveat)."),
    "predictability_class": ("Whether the underlying dependency is predictable from the cell lines' "
                             "molecular features — a CONFIDENCE annotation on the tractability call, not "
                             "the call itself."),
    "degrader_snapshot": ("The additive DEGRADER read (degradation = KO-like complete protein removal, "
                          "unlike catalytic inhibition): strong_degrader_rationale / degrader_rationale / "
                          "degrader_opposed / degrader_unviable / insufficient. The full degrader machinery "
                          "check (E3 ligase / CRBN / VHL / proteasome) is not yet assessed."),
}


def _fmt(v, nd=2):
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def build_user_prompt(decision: dict, subtype_query: Optional[str] = None) -> str:
    """Assemble the LLM input from the DETERMINISTIC tractability decision spine. Narrates the composed
    druggability_snapshot grounded in the FULL evidence (not just the verdict). Field names are the ACTUAL
    keys tractability-small-molecule/scripts/run.py::_headline emits; each card rendered present /
    DATA_UNAVAILABLE / not-present so a measured null is never silently dropped."""
    h = decision.get("headline", {}) or {}
    target = decision.get("target"); indication = decision.get("indication")
    card_list = decision.get("cards", [])
    present_ids = {c["card_id"] for c in card_list}
    missing = {c["card_id"] for c in card_list if c.get("_missing")}

    def _card_state(card_id: str) -> str:
        if card_id in missing:
            return "DATA_UNAVAILABLE (measured, no usable value)"
        if card_id not in present_ids:
            return "not present in this run"
        return "measured"

    lines = [
        f"TARGET: {target}    INDICATION: {indication}",
        "",
        "DETERMINISTIC VERDICT (fixed — narrate, do not change):",
        f"  druggability_snapshot: {h.get('druggability_snapshot')}  (driving_rule: {h.get('driving_rule_id')})",
        f"  degrader_snapshot (additive): {h.get('degrader_snapshot')}  "
        f"(driving_rule: {h.get('degrader_driving_rule_id')})  "
        f"degradability_machinery: {h.get('degradability_machinery')}",
        "",
        "RETROSPECTIVE CHEMICAL EVIDENCE — has a compound actually hit the target?",
        f"  prism_activity_class: {h.get('prism_activity_class')}   "
        f"(prism-compound-activity: {_card_state('prism-compound-activity')})",
        "",
        "ON-TARGET ENGAGEMENT — does the chemical effect TRACK the genetic dependency (or is it off-target)?",
        f"  prism_crispr_concord: {h.get('prism_crispr_concord')}   "
        f"(prism-crispr-concordance: {_card_state('prism-crispr-concordance')})",
        "",
        "FORWARD STRUCTURAL LIGANDABILITY — a druggable pocket even absent a compound (KRAS-G12C case):",
        f"  hotspot_pocket_adjacency: {h.get('hotspot_pocket_adjacency')}   "
        f"hotspot_in_druggable_pocket: {h.get('hotspot_in_druggable_pocket')}",
        f"  pdb_coverage_class: {h.get('pdb_coverage_class')}   "
        f"alphafold_confidence_class: {h.get('alphafold_confidence_class')}   "
        f"(structure-features-static: {_card_state('structure-features-static')})",
        "",
        "PREDICTABILITY (META-evidence — how omics-learnable is the underlying dependency; a CONFIDENCE handle):",
        f"  predictability_class: {h.get('predictability_class')}   "
        f"(dependency-predictability: {_card_state('dependency-predictability')})",
        "",
        "TASK: using emit_tractability_sm_synthesis, judge how much the SMALL-MOLECULE tractability lens "
        f"informs whether {target} is worth pursuing with a small molecule (or degrader) in {indication}. "
        "Reason ACROSS the evidence — do not just restate the snapshot. Foreground the ON-TARGET-vs-"
        "FORWARD-STRUCTURAL-vs-NEITHER distinction: a DISCORDANT chemical read (active but off-target) "
        "ARGUES AGAINST tractability, it is NOT support; a druggable pocket without a compound is a genuine "
        "forward prospect. Give the additive DEGRADER read (KO-like removal — a dependency without a pocket "
        "can still be a degrader prospect; machinery check pending). If there is no compound and no "
        "structural handle, say SM tractability is UNINFORMATIVE and the rationale must come from other "
        "lenses. Do NOT discuss dependency magnitude, surface/biologics modality, expression, or mutation. "
        "Ground every claim in the fields; state DATA_UNAVAILABLE gaps plainly.",
    ]
    return "\n".join(lines)


def synthesize_tractability_sm(decision: dict, model_id: Optional[str] = None,
                               subtype_query: Optional[str] = None) -> dict:
    """Run the opt-in tractability-SM narration over a composed decision. Returns the provenance-tagged
    llm_synthesis block. Raises are the CALLER's to handle (the dispatcher degrades to a note on failure —
    synthesis is never allowed to break the deterministic run)."""
    from _skills_common.llm import synthesize_structured
    user_prompt = build_user_prompt(decision, subtype_query=subtype_query)
    result = synthesize_structured(
        system_prompt=_SYSTEM,
        user_prompt=user_prompt,
        tool_name=SYNTHESIS_TOOL_NAME,
        tool_schema=SYNTHESIS_TOOL_SCHEMA,
        model_id=model_id,
    )
    if isinstance(result, dict) and "_synthesis_error" not in result:
        result.setdefault("metric_legend", METRIC_LEGEND)
    return result
