"""synthesis_surface_modality — opt-in LLM narration for the surface-modality-fit (biologics) lens.

Sibling of _skills_common/synthesis_dependency.py + synthesis_selectivity.py + synthesis_genomic.py,
same TWO-SLOT contract:
  SLOT 1 (deterministic, byte-stable): decision["headline"]["surface_modality_verdict"] + fit_class +
    driving_rule_id + every surface card field. Built upstream; this module NEVER writes to it.
  SLOT 2 (llm, provenance-tagged): decision["llm_synthesis"], a SIBLING key attached AFTER the
    decision is composed — structurally impossible to alter the verdict.

The LLM NARRATES the composed surface-modality fit_class (ADC-preferred / TCE-preferred / both-viable /
neither-viable / isoform-dependent / modality-ambiguous / insufficient) and how it holds up across the
surface evidence: topology (is there an accessible extracellular domain?), surfaceome-family routing,
structural pocket, antigen surface-density, normal-tissue liability (the killer axis for TCE), confirmed
cell-surface protein evidence, shed-ectodomain liability (a soluble-antigen sink), and within-tumour
antigen homogeneity (the TCE-escape axis). It NEVER mints or flips the surface_modality_verdict.

SINGLE-LENS scope: judge how much the SURFACE-BIOLOGY evidence supports a BIOLOGICS modality (ADC / TCE /
antibody) — is the target accessible on the cell surface, tumour-selective enough, and homogeneous enough
for the delivery mechanism? Do NOT assess genetic dependency, small-molecule druggability, expression
magnitude per se, or mutation (those are other lenses).

FULL-EVIDENCE discipline (the H1 "drops-nulls" lesson): this narrator reads the WHOLE surface card set,
each in one of three states (present / DATA_UNAVAILABLE / not-present-this-run), so a measured null is
decision-useful, never silently dropped. Field names are the ACTUAL keys surface-modality-fit/scripts/
run.py::_headline emits (feedback_synthesis_reader_real_field_names).
"""
from __future__ import annotations

from _skills_common.llm import EVIDENCE_ONLY_DIRECTIVE as _EVIDENCE_ONLY_DIRECTIVE

from typing import Optional

SYNTHESIS_TOOL_NAME = "emit_surface_modality_synthesis"
SYNTHESIS_TOOL_SCHEMA = {
    "type": "object",
    "description": ("Assess, from the SURFACE-BIOLOGY (biologics-modality) lens ALONE, how much this lens "
                    "informs whether the target is approachable by an ADC, T-cell engager (TCE), or "
                    "antibody in this cancer. Reason ACROSS the gathered surface evidence (topology / "
                    "accessible ECD, surfaceome family, structural pocket, antigen surface-density, "
                    "normal-tissue liability, confirmed cell-surface protein, shed-ectodomain liability, "
                    "within-tumour homogeneity); do NOT restate a different verdict, and do NOT assess "
                    "genetic dependency, small-molecule druggability, or mutation (other lenses' job)."),
    "properties": {
        "surface_modality_relevance_for_target": {
            "type": "string",
            "enum": ["strongly_supports", "supports_with_caveats", "neutral_uninformative",
                     "argues_against"],
            "description": ("The headline judgment: how much does the SURFACE evidence support a biologics "
                            "modality? strongly_supports = an accessible, tumour-selective surface antigen "
                            "with a clear preferred modality (ADC and/or TCE) and no disqualifying liability. "
                            "supports_with_caveats = surface-approachable but qualified (thin protein "
                            "confirmation, shed-antigen sink, heterogeneous within-tumour expression, "
                            "moderate normal-tissue expression, or an ambiguous ADC-vs-TCE call). "
                            "neutral_uninformative = surface biology does not distinguish the target "
                            "(insufficient topology/family evidence) — rationale must come from other "
                            "lenses. argues_against = a disqualifying surface read (no accessible ECD / "
                            "intracellular, essential-normal-tissue expression for a TCE, or a dominant "
                            "shed sink). A SINGLE-LENS read; it informs confidence, NEVER mints or flips "
                            "the verdict.")},
        "surface_modality_rationale": {
            "type": "string",
            "description": ("2-4 sentences in a scientific-publication register (Results/Discussion voice: "
                            "declarative, factual, no promotional adjectives such as 'promising' or "
                            "'exciting'). Integrate the deterministic fit_class, the topology/accessible-ECD "
                            "call, surfaceome family, any structural pocket, antigen surface-density, "
                            "normal-tissue liability, confirmed surface-protein evidence, shed liability, and "
                            "within-tumour homogeneity. State plainly which biologics modality (if any) the "
                            "surface biology supports and why. On FIRST use of a technical term, gloss it in "
                            "plain language for a non-computational reader — e.g. 'extracellular domain (the "
                            "part of the protein outside the cell, which an antibody can bind)'. Ground every "
                            "claim in the provided fields; state DATA_UNAVAILABLE gaps rather than omitting.")},
        "adc_vs_tce_read": {
            "type": "string",
            "description": ("1-2 sentences, same publication register, on the modality DISCRIMINATION: does "
                            "the surface biology favour an ADC, a TCE, both, or neither, and why? Ground it "
                            "in the axes that separate them: ADCs tolerate moderate normal-tissue expression "
                            "(bystander payload) but need internalisation + adequate antigen density; TCEs "
                            "are far less forgiving of normal-tissue expression (on-target/off-tumour "
                            "toxicity) and are sensitive to within-tumour antigen HETEROGENEITY (antigen-"
                            "negative tumour cells escape killing) and to a shed ectodomain (a soluble decoy "
                            "sink). State the killer axis where one fires. If the call is genuinely "
                            "ambiguous or isoform-dependent, say so.")},
        "confidence_qualifier": {
            "type": "string",
            "enum": ["well_supported", "supported_with_caveats", "weakly_supported",
                     "insufficient_evidence"],
            "description": ("How completely the available surface evidence supports the relevance read above "
                            "(topology confidence, protein-surface confirmation depth, density/homogeneity "
                            "coverage, normal-tissue breadth). A confidence read on the EVIDENCE — it does "
                            "not change the deterministic verdict.")},
        "key_caveat": {
            "type": "string",
            "description": ("The single most important limitation a reader should carry, stated factually in "
                            "one sentence (e.g. surface localisation inferred from RNA only / not protein-"
                            "confirmed, a shed-ectodomain sink, within-tumour heterogeneity, essential "
                            "normal-tissue expression, an absent structural model, or an ADC-vs-TCE ambiguity), "
                            "or 'none' if none.")},
    },
    "required": ["surface_modality_relevance_for_target", "surface_modality_rationale",
                 "adc_vs_tce_read", "confidence_qualifier", "key_caveat"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You are a computational-oncology analyst writing the surface-modality (biologics) section of a "
    "target-evaluation dossier. Reason ACROSS the SURFACE-BIOLOGY evidence for a (target, indication) and "
    "judge how much this lens informs whether the target is approachable by an antibody-drug conjugate "
    "(ADC), a T-cell engager (TCE), or a naked antibody. This is a single-lens assessment. You NARRATE "
    "and INTEGRATE the provided fields; you never invent facts and you never change the deterministic, "
    "rule-computed surface_modality_verdict / fit_class (they are FIXED upstream). "
    "REGISTER — write to scientific-publication standard: the voice of a methods/results section. "
    "Declarative, precise, factual; complete sentences; active voice. Report each value with its meaning, "
    "never bare. Do NOT use promotional or editorialising language (avoid 'promising', 'exciting', "
    "'compelling', 'robustly', 'clearly'); let the evidence carry the claim. Concise but readable — a "
    "domain biologist who is not a structural or computational specialist must follow it without a glossary. "
    "PLAIN-LANGUAGE TERMS — on FIRST use of any technical term, add a short parenthetical gloss, e.g.: "
    "extracellular domain / ECD (the portion of the protein outside the cell membrane, accessible to an "
    "antibody); topology (whether and how the protein spans the membrane — a single-pass surface protein "
    "with a large ECD is the favourable case); shed ectodomain (ECD cleaved and released into blood, which "
    "can act as a soluble decoy that soaks up the drug); antigen density (copies of the target per cell — "
    "ADC payload delivery scales with it); within-tumour homogeneity (the fraction of malignant cells "
    "expressing the antigen — a TCE requires high homogeneity because antigen-negative cells escape "
    "killing). Gloss once, then use the term freely. "
    "MODALITY DISCRIMINATION (the central reasoning): an ADC and a TCE make DIFFERENT demands. An ADC "
    "needs an accessible, internalising surface antigen at adequate density and tolerates MODERATE "
    "normal-tissue expression (the cytotoxic payload's bystander effect provides a buffer). A TCE is far "
    "LESS forgiving of normal-tissue expression (on-target/off-tumour T-cell toxicity), and is additionally "
    "sensitive to within-tumour antigen HETEROGENEITY (antigen-negative tumour cells escape) and to a shed "
    "ectodomain (a soluble decoy sink). Essential-normal-tissue expression is a TCE killer; a dominant shed "
    "sink or marked heterogeneity argues against a TCE while an ADC may remain viable. State the killer axis "
    "where one fires; if the surface biology cannot separate ADC from TCE, say the call is ambiguous. "
    "ACCESSIBILITY FIRST: a biologics modality REQUIRES an accessible extracellular domain. If topology "
    "indicates no ECD / an intracellular or non-membrane protein, the surface lens argues AGAINST all "
    "biologics regardless of other signals — state that plainly. Protein-level surface confirmation "
    "strengthens the call; an RNA-only inference is a caveat to state explicitly. Report DATA_UNAVAILABLE "
    "gaps plainly — a measured null is informative. "
    "SCOPE: address only the surface-biology / biologics-modality lens. Do not discuss genetic dependency, "
    "small-molecule druggability, expression magnitude per se, or mutation/alteration status; those belong "
    "to other sections of the dossier."
    + _EVIDENCE_ONLY_DIRECTIVE
)

# Deterministic plain-language legend for the metrics the narration cites. Attached as a SIBLING key
# (metric_legend) so a non-computational reader always has an accurate, byte-stable reference —
# independent of what the LLM writes. Ordered from most- to least-referenced.
METRIC_LEGEND = {
    "fit_class": ("The composed biologics-modality call for the target's surface biology: "
                  "adc_preferred / tce_preferred / both_viable / neither_viable / "
                  "isoform_dependent_undefined / modality_ambiguous / insufficient. It is computed by "
                  "rule from the surface cards below; the narration explains it, it does not change it."),
    "topology_class": ("Whether the protein presents an accessible extracellular domain (ECD) — the part "
                       "outside the cell an antibody can bind. A single-pass membrane protein with a large "
                       "ECD is the favourable case; no ECD / intracellular argues against all biologics."),
    "surface_density_class": ("Antigen density — copies of the target per cell. ADC payload delivery scales "
                              "with density; low density weakens an ADC. Graded from measured (grades A/B) "
                              "to inferred (grade D)."),
    "normal_tissue_breadth_class": ("How broadly the target is expressed in normal tissues. ADCs tolerate "
                                    "moderate normal expression (bystander payload buffer); TCEs do not "
                                    "(on-target/off-tumour toxicity). Essential-tissue expression is a TCE "
                                    "killer."),
    "shed_liability_class": ("Whether the extracellular domain is shed (cleaved and released into blood), "
                             "where it can act as a soluble decoy that soaks up the drug before it reaches "
                             "the tumour — a particular liability for TCEs."),
    "tce_homogeneity_class": ("The fraction of malignant cells expressing the antigen within a tumour "
                              "(single-cell). A TCE requires high homogeneity because antigen-negative "
                              "tumour cells escape T-cell killing; marked heterogeneity argues against a TCE."),
    "surface_confirmation_class": ("Whether cell-surface localisation is confirmed at the PROTEIN level "
                                   "(vs inferred from RNA alone). Protein confirmation strengthens any "
                                   "biologics call; an RNA-only inference is a caveat."),
}


def _fmt(v, nd=2):
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def build_user_prompt(decision: dict, subtype_query: Optional[str] = None) -> str:
    """Assemble the LLM input from the DETERMINISTIC surface-modality decision spine. Narrates the
    composed fit_class grounded in the FULL surface evidence (not just the verdict). Field names are the
    ACTUAL keys surface-modality-fit/scripts/run.py::_headline emits, and each card is rendered in one of
    THREE states (present / DATA_UNAVAILABLE / not-present) so a measured null is never silently dropped."""
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
        f"  surface_modality_verdict: {h.get('surface_modality_verdict')}  "
        f"(driving_rule: {h.get('driving_rule_id')})",
        f"  fit_class (composed): {h.get('fit_class')}   "
        f"(adc-tce-modality-fit: {_card_state('adc-tce-modality-fit')})",
        "",
        "ACCESSIBILITY — is there a bindable extracellular domain? (the gate for ALL biologics):",
        f"  topology_class: {h.get('topology_class')}   "
        f"(surface-topology-and-ptm: {_card_state('surface-topology-and-ptm')})",
        f"  family_class: {h.get('family_class')}   "
        f"(surfaceome-family-classification: {_card_state('surfaceome-family-classification')})",
        f"  hotspot_pocket_adjacency_call: {h.get('hotspot_pocket_adjacency_call')}   "
        f"(structure-features-static: {_card_state('structure-features-static')})",
        "",
        "PROTEIN-LEVEL SURFACE CONFIRMATION (RNA-only inference is a caveat; protein confirmation is stronger):",
        f"  surface_confirmation_class: {h.get('surface_confirmation_class')}   "
        f"(n_celllines_detected: {h.get('surface_confirmation_n_celllines')})   "
        f"(protein-surface-evidence: {_card_state('protein-surface-evidence')})",
        "",
        "ADC AXIS — antigen density (payload delivery scales with it):",
        f"  surface_density_class: {h.get('surface_density_class')}   "
        f"(surface-abundance-density: {_card_state('surface-abundance-density')})",
        "",
        "NORMAL-TISSUE LIABILITY (the TCE KILLER axis; ADC tolerates moderate expression via bystander payload):",
        f"  normal_tissue_breadth_class: {h.get('normal_tissue_breadth_class')}   "
        f"essential_tissue_flag: {h.get('essential_tissue_flag')}   "
        f"safety_flags: {h.get('normal_tissue_safety_flags')}   "
        f"(normal-tissue-liability: {_card_state('normal-tissue-liability')})",
        "",
        "SHED-ECTODOMAIN LIABILITY (a soluble decoy sink — a particular TCE liability):",
        f"  shed_liability_class: {h.get('shed_liability_class')}   "
        f"serum_marker: {h.get('shed_serum_marker')}   "
        f"(shed-ectodomain-liability: {_card_state('shed-ectodomain-liability')})",
        "",
        "WITHIN-TUMOUR HOMOGENEITY (the TCE-ESCAPE axis — antigen-negative cells evade a TCE):",
        f"  tce_homogeneity_class: {h.get('tce_homogeneity_class')}   "
        f"malignant_detection_fraction: {_fmt(h.get('malignant_detection_fraction'))}   "
        f"(tumor-scrna-celltype-expression: {_card_state('tumor-scrna-celltype-expression')})",
        "",
        "THERAPEUTIC-WINDOW ARC (per-modality tumour-vs-normal window, where available):",
        f"  window_class: {h.get('window_class')}   "
        f"(ratio_full_normal: {_fmt(h.get('window_ratio_full_normal'))}, "
        f"ratio_essential: {_fmt(h.get('window_ratio_essential'))}, "
        f"max_essential_organ: {h.get('window_max_essential_organ')})   "
        f"(modality-therapeutic-window: {_card_state('modality-therapeutic-window')})",
        "",
        "sc-NORMAL CELL-TYPE LIABILITY (cell-type-resolved normal RNA — a TCE KILLER axis; the "
        "complement to HPA IHC: it names WHICH normal cell type expresses the antigen):",
        f"  sc_normal_expression_class: {h.get('sc_normal_expression_class')}   "
        f"max_detection_cell_type: {h.get('sc_normal_max_det_cell_type')}   "
        f"max_detection_fraction: {_fmt(h.get('sc_normal_max_det_fraction'))}   "
        f"essential_flags: {h.get('sc_normal_safety_essential_flags')}   "
        f"(sc-normal-celltype-expression: {_card_state('sc-normal-celltype-expression')})",
        "",
        "PEPTIDE-CENTRIC TCE AXIS (pMHC presentation — the ONLY biologics route to an INTRACELLULAR "
        "target, via a TCR-mimetic TCE; broad NORMAL presentation is a liability, restricted is favorable):",
        f"  pmhc_presentation_class: {h.get('pmhc_presentation_class')}   "
        f"n_normal_tissues_presented: {h.get('pmhc_n_normal_tissues')}   "
        f"hla_class: {h.get('pmhc_hla_class')}   "
        f"(pmhc-presentation: {_card_state('pmhc-presentation')})",
        "",
        "CD/IO-ANTIGEN BACKBONE (clinical-precedent class prior — is this a CD/IO-backbone antigen like "
        "the CD19/CD20/BCMA-class validated biologics targets? SUPPORTIVE-ONLY, never a negative):",
        f"  cd_antigen_backbone_class: {h.get('cd_antigen_backbone_class')}   "
        f"(cd-antigen-backbone: {_card_state('cd-antigen-backbone')})",
        "",
        "PATIENT-SELECTION / STATE-CONDITIONED SURFACE ENRICHERS (is the antigen ELEVATED in a "
        "mutation- or pathway-defined tumour subset — a patient-selection handle? + EXON-resolution "
        "window. Additive context, archetype-limited coverage — DATA_UNAVAILABLE off-archetype):",
        f"  mutant_stratified_surface_class: {h.get('mutant_stratified_surface_class')}   "
        f"driver: {h.get('mutant_surface_driver')}   delta_log2: {_fmt(h.get('mutant_surface_delta_log2'))}   "
        f"(mutation-stratified-surface: {_card_state('mutation-stratified-surface')})",
        f"  pathway_stratified_surface_class: {h.get('pathway_stratified_surface_class')}   "
        f"signature: {h.get('pathway_surface_signature')}   delta_log2: {_fmt(h.get('pathway_surface_delta_log2'))}   "
        f"(pathway-stratified-surface: {_card_state('pathway-stratified-surface')})",
        f"  exon_window_class: {h.get('exon_window_class')}   "
        f"best_exon: {h.get('exon_best_exon_id')}   window_ratio: {_fmt(h.get('exon_best_exon_window_ratio'))}   "
        f"heterogeneity_log2: {_fmt(h.get('exon_heterogeneity_log2'))}   "
        f"(modality-exon-window: {_card_state('modality-exon-window')})",
        "",
        "TASK: using emit_surface_modality_synthesis, judge how much the SURFACE-BIOLOGY lens informs "
        f"whether {target} is approachable by a biologics modality (ADC / TCE / antibody) in {indication}. "
        "Reason ACROSS the evidence — do not just restate fit_class. Lead with ACCESSIBILITY: if there is no "
        "bindable extracellular domain, the lens argues AGAINST a surface-binding biologic — BUT check the "
        "PEPTIDE-CENTRIC pMHC axis before foreclosing, since a TCR-mimetic TCE can reach an INTRACELLULAR "
        "target via presented peptide (restricted normal presentation = favorable; broad = liability). Then "
        "DISCRIMINATE ADC vs TCE on the axes that separate them (normal-tissue liability incl. the "
        "cell-type-resolved sc-normal read, within-tumour homogeneity, shed sink, antigen density), and name "
        "the KILLER axis where one fires. Use the CD/IO-backbone class prior as supporting precedent (never "
        "as a negative) and the patient-selection enrichers (mutation-/pathway-stratified surface, exon "
        "window) as context for WHICH patients / WHICH epitope, not as the primary call. If surface "
        "localisation is RNA-only (not protein-confirmed), foreground that caveat. If the surface biology is "
        "insufficient to distinguish the target, say the lens is UNINFORMATIVE and the rationale must come "
        "from other lenses. Do NOT discuss genetic dependency, small-molecule druggability, or mutation as a "
        "driver. Ground every claim in the fields; state DATA_UNAVAILABLE gaps plainly.",
    ]
    return "\n".join(lines)


def synthesize_surface_modality(decision: dict, model_id: Optional[str] = None,
                                subtype_query: Optional[str] = None) -> dict:
    """Run the opt-in surface-modality narration over a composed decision. Returns the provenance-tagged
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
    # Attach the deterministic plain-language metric legend as a sibling key (see synthesis_dependency).
    if isinstance(result, dict) and "_synthesis_error" not in result:
        result.setdefault("metric_legend", METRIC_LEGEND)
    return result
