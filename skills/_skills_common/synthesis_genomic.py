"""synthesis_genomic — opt-in LLM narration for the genomic-alteration lens.

Sibling of _skills_common/synthesis.py (presence), same TWO-SLOT contract:
  SLOT 1 (deterministic, byte-stable): decision["headline"]["genomic_alteration_profile"]
    + every alteration-axis class. Built upstream; this module NEVER writes to it.
  SLOT 2 (llm, provenance-tagged): decision["llm_synthesis"], a SIBLING key attached
    AFTER the decision is composed — structurally impossible to alter the verdict.

The LLM NARRATES the multi-class genomic-alteration verdict + WHICH alteration class
drives (SNV/indel vs copy-number vs fusion) + the additive role / allele-count /
patient-model / subtype-recurrence layers. It NEVER mints or flips the verdict class.

SINGLE-LENS scope: reason across the alteration MIX — is the target genomically altered
in a way that gives a REASON to pursue it (recurrent driver, biomarker-stratified
dependency), or is the alteration a passenger? Do NOT assess modality, expression, or
surface accessibility.
"""
from __future__ import annotations

from _skills_common.llm import EVIDENCE_ONLY_DIRECTIVE as _EVIDENCE_ONLY_DIRECTIVE

from typing import Optional

SYNTHESIS_TOOL_NAME = "emit_genomic_alteration_synthesis"
SYNTHESIS_TOOL_SCHEMA = {
    "type": "object",
    "description": ("Assess, from the GENOMIC-ALTERATION lens ALONE, how much this lens informs whether "
                    "the target is a relevant drug target in this cancer. Reason ACROSS the alteration "
                    "MIX (SNV/indel, copy-number, fusion), which class DRIVES, the driver ROLE, and the "
                    "recurrence context; do NOT restate a different verdict, do NOT assess modality or "
                    "expression."),
    "properties": {
        "alteration_relevance_for_target": {
            "type": "string",
            "enum": ["strongly_supports", "supports_with_caveats", "neutral_uninformative",
                     "argues_against"],
            "description": ("The headline judgment: how much does the GENOMIC-ALTERATION evidence inform "
                            "this target's relevance? strongly_supports = a recurrent driver / biomarker-"
                            "stratified dependency with a clear driving class + functional role. "
                            "supports_with_caveats = altered but qualified (single class, modest "
                            "recurrence, role uncertain). neutral_uninformative = altered as a likely "
                            "passenger, or not recurrently altered — alteration is NOT the reason to "
                            "pursue this target. argues_against = evidence the alteration undercuts the "
                            "hypothesis. A SINGLE-LENS read; it informs confidence, NEVER mints/flips.")},
        "driving_class_rationale": {
            "type": "string",
            "description": ("2-4 sentences REASONING ACROSS the alteration axes: integrate the "
                            "deterministic genomic_alteration_profile verdict, WHICH class drives "
                            "(mutation_landscape_class vs copy_number_class vs fusion), the driver ROLE "
                            "(alteration_role / functional_direction — GoF vs LoF), the "
                            "mutation_stratification_class (is mutant status a dependency biomarker?), "
                            "and the driver-recurrence percentile (is recurrence unusual in-indication, "
                            "or passenger-level?). Say explicitly which class carries the signal. Ground "
                            "every claim in the fields; cite DATA_UNAVAILABLE gaps rather than omitting.")},
        "recurrence_and_role_read": {
            "type": "string",
            "description": ("1-2 sentences on RECURRENCE vs ROLE: is the target recurrently altered "
                            "AND functionally a driver, or recurrent-but-passenger (e.g. a large gene in "
                            "a hypermutated cohort) / functional-but-rare? Use driver_recurrence_class + "
                            "alteration_role. A recurrently-mutated passenger is NOT a driver. If the "
                            "subtype panorama is present, note any per-stratum concentration. Do NOT "
                            "conflate frequency with function.")},
        "confidence_qualifier": {
            "type": "string",
            "enum": ["well_supported", "supported_with_caveats", "weakly_supported",
                     "insufficient_evidence"],
            "description": ("How well the gathered evidence supports the relevance read above (data "
                            "completeness/quality: cohort size, panel coverage, role annotation "
                            "availability, patient-model event match). A CONFIDENCE read — it does not "
                            "change the deterministic verdict.")},
        "key_caveat": {
            "type": "string",
            "description": ("The single most important caveat a reviewer should carry (passenger risk in "
                            "a hypermutated cohort, single-cohort recurrence, role not annotated, fusion "
                            "data absent, uncertain allele-count/two-hit state), or 'none' if none.")},
    },
    "required": ["alteration_relevance_for_target", "driving_class_rationale",
                 "recurrence_and_role_read", "confidence_qualifier", "key_caveat"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You are a computational-oncology target-evaluation assistant. Your PURPOSE here is narrow: reason "
    "ACROSS the GENOMIC-ALTERATION evidence for a (target, indication) and judge HOW MUCH THIS LENS "
    "INFORMS whether the target is a relevant drug target — is it altered in a way (recurrent driver, "
    "biomarker-stratified dependency) that gives a REASON to pursue it, and WHICH alteration class "
    "drives? This is a SINGLE-LENS assessment. You NARRATE and INTEGRATE; you never invent facts and "
    "you never change the deterministic, rule-computed genomic_alteration verdict (it is FIXED "
    "upstream). "
    "FREQUENCY != FUNCTION: a gene can be recurrently mutated without being a driver (a large gene in a "
    "hypermutated MSI-H cohort accumulates passenger mutations). Weigh the driver-recurrence percentile "
    "AGAINST the functional role (alteration_role / functional_direction) — do not read recurrence "
    "alone as a driver signal. "
    "DRIVING CLASS: the same gene can drive via different classes across indications (ERBB2 amp in "
    "gastric vs mutation in a lung subset). Say WHICH class carries the signal here. State "
    "DATA_UNAVAILABLE gaps plainly — a null result is decision-useful. "
    "REGISTER — write to scientific-publication standard: the voice of a methods/results section. "
    "Declarative, precise, and factual; complete sentences; active voice. Report each number with its "
    "scale and direction, never bare. Do NOT use promotional or editorialising language (avoid "
    "'promising', 'exciting', 'compelling', 'robustly', 'clearly'); let the evidence carry the claim. "
    "Concise but readable — a domain biologist who is not a statistician must follow it without a glossary. "
    "PLAIN-LANGUAGE METRICS — on FIRST use of any technical quantity, add a short parenthetical gloss so a "
    "non-computational reader can interpret it, e.g.: mutation frequency (share of tumours in the cohort "
    "carrying a mutation in this gene); driver-recurrence percentile (where that recurrence ranks among "
    "ALL mutated genes in the indication — high = recurrent beyond the passenger background); "
    "alteration_role (a curated GoF/LoF/biomarker/passenger call from OncoKB x IntOGen — FUNCTION, not "
    "frequency); copy_number_class (recurrent amplification vs deletion vs neutral). Gloss once, then "
    "use the term freely. "
    "SCOPE DISCIPLINE: do NOT discuss therapeutic MODALITY, expression level, or surface accessibility. "
    "Those belong to other lenses / the composed target-profile synthesis."
    + _EVIDENCE_ONLY_DIRECTIVE
)

# Deterministic plain-language legend for the metrics this narration cites — attached as a sibling
# key (metric_legend) so a non-computational reader always has an accurate, byte-stable reference,
# independent of the LLM's inline glosses. Mirrors synthesis_dependency.METRIC_LEGEND.
METRIC_LEGEND = {
    "mutation_frequency": ("The share of tumours in the cohort carrying a mutation in this gene "
                           "(0-1). Frequency alone is NOT function — a large gene in a hypermutated "
                           "cohort accumulates passenger mutations at high frequency."),
    "driver_recurrence_percentile": ("Where this gene's mutation recurrence ranks among ALL mutated "
                                     "genes in the indication (0-100). High = recurrent well beyond "
                                     "the passenger background (a driver-like pattern); mid/low = "
                                     "passenger-level. The contextualization of raw frequency."),
    "alteration_role": ("A curated FUNCTIONAL call (OncoKB x IntOGen): gain-of-function (GoF, "
                        "activating oncogene), loss-of-function (LoF, tumour suppressor), "
                        "predictive_biomarker, or passenger. Weigh this AGAINST recurrence — a "
                        "recurrently-mutated passenger is not a driver."),
    "copy_number_class": ("The copy-number alteration pattern: recurrently amplified, recurrently "
                          "deleted, or copy-neutral. An amplification-driven target (e.g. ERBB2) can "
                          "read 'not a driver' on mutation frequency yet be driven by copy number."),
    "mutation_stratification_class": ("Whether mutant status stratifies a dependency — i.e. is the "
                                      "gene's mutation a candidate patient-selection biomarker for a "
                                      "dependency, rather than just recurrent?"),
    "functional_state_class": ("The allele-count / two-hit state: whether the gene is biallelically "
                               "inactivated (completed two-hit -> LoF) or only monoallelically hit."),
}


def _fmt(v, nd=1):
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def _genie_sv_line(h: dict) -> str:
    """One-line GENIE-SV breadth summary for the fusion axis: class + coverage-correct frequency +
    up to 3 recurrent SV partners (EML4 for ALK, etc.). n/a-safe when the facet is absent."""
    cls = h.get("genie_sv_recurrence_class", "n/a")
    freq = _fmt(h.get("genie_sv_frequency"), 4)
    partners = [p.get("partner") for p in (h.get("genie_sv_recurrent_partners") or [])][:3]
    tail = f", partners {partners}" if partners else ""
    return f"{cls} (freq {freq}{tail})"


def _civic_variant_line(variants, class_key: str, with_therapies: bool = False) -> str:
    """Compact 'variant:class[(therapies)]' list (top 4) for the CIViC per-variant axis.
    `variants` is the oncogenic_variants / resistance_variants list from the card. n/a-safe."""
    if not variants:
        return "none"
    parts = []
    for v in variants[:4]:
        s = f"{v.get('variant')}:{v.get(class_key)}"
        if with_therapies:
            ther = (v.get("therapies") or [])[:2]
            if ther:
                s += f"({'/'.join(ther)})"
        parts.append(s)
    return "; ".join(parts)


def build_user_prompt(decision: dict) -> str:
    """Assemble the LLM input from the DETERMINISTIC genomic-alteration decision spine. Narrates the
    multi-class verdict + driving class + role + recurrence, grounded in the actual headline fields the
    skill emits (verified against genomic-alteration-profile/scripts/run.py::headline)."""
    h = decision.get("headline", {}) or {}
    target = decision.get("target"); indication = decision.get("indication")

    from _skills_common.signals_first import render_signal_vector
    lines = [
        f"TARGET: {target}    INDICATION: {indication}",
        "",
        "SIGNAL VECTOR (pre-computed within-lens integration — LEAD your narration with THIS; the "
        "collapsed verdict below is a compressed label, not the headline):",
        render_signal_vector(h.get("claim_vector"),
                             {"SNV": "SNV/indel", "CN": "copy-number", "FUS": "fusion", "DEP": "dependency"}),
        "",
        "COLLAPSED VERDICT (a compressed label — do NOT lead with it or let it mask a disagreeing signal "
        "above; fixed upstream, narrate not change):",
        f"  genomic_alteration_profile: {h.get('genomic_alteration_profile')}  "
        f"(driving_rule: {h.get('driving_rule_id')})",
        "",
        "ALTERATION MIX (which class(es) are present — say which DRIVES):",
        f"  mutation_landscape_class: {h.get('mutation_landscape_class')}",
        f"  mutation_stratification_class: {h.get('mutation_stratification_class')} "
        "(is mutant status a dependency biomarker?)",
        f"  stratified_evidence_scope: {h.get('stratified_evidence_scope', 'n/a')}"
        + (f"  [lineage_context_divergent]" if h.get('stratified_lineage_context_divergent') else ""),
        "  NOTE (scope): the stratified-dependency call is CELL-LINE dependence in DepMap. "
        "within_indication = split ran within the indication's lineage; within_indication_mut_vs_pan_wt "
        "= lineage mutants vs pan-DepMap WT (high-prevalence-driver lineages); pan_lineage_evidence_only "
        "= within-lineage underpowered, pan-DepMap (strong capped to moderate) — treat as a pan-cancer "
        "extrapolation, NOT indication-confirmed. Cell-line dependence != clinical monotherapy response.",
        f"  copy_number_class: {h.get('copy_number_class')}",
        f"  fusion_class (TCGA 3-caller consensus, deep/33 tissues): {h.get('fusion_class', 'n/a')}",
        f"  genie_sv breadth (GENIE panel, 271k tumors, coverage-correct): {_genie_sv_line(h)}",
        "  NOTE: TCGA fusion consensus is DEEP but tissue-limited; GENIE-SV is higher-N BREADTH "
        "(e.g. ALK: ~5 TCGA LUAD vs 774 GENIE NSCLC). Neither drives the verdict — both are display.",
        "",
        "DRIVER ROLE (function, not just frequency — OncoKB x IntOGen):",
        f"  alteration_role: {h.get('alteration_role')}   functional_direction: {h.get('functional_direction')}",
        f"  functional_state_class (allele-count / two-hit): {h.get('functional_state_class')}",
        f"  event_correspondence_class (patient<->model match): {h.get('event_correspondence_class')}",
        "",
        "RECURRENCE CONTEXT (Axis-1 — is recurrence unusual among all mutated genes in-indication?):",
        f"  overall_mutation_frequency: {_fmt(h.get('overall_mutation_frequency'), 3)}",
        f"  driver_recurrence_class (TCGA-MC3, whole-exome ~1k pts): {h.get('driver_recurrence_class')}  "
        f"(percentile {_fmt(h.get('driver_recurrence_percentile'))})",
        f"  genie_driver_recurrence_class (GENIE, panel ~35x pts, coverage-correct): "
        f"{h.get('genie_driver_recurrence_class')}  (freq {_fmt(h.get('genie_mutation_frequency'), 3)})",
        "  NOTE: MC3 + GENIE are independent comparators — agreement = robust; divergence is a "
        "coverage/cohort caveat, not a contradiction. Neither is a functional-driver call.",
        "",
        "PER-VARIANT INTERPRETATION (CIViC — the gene->variant axis: FUNCTION of specific alleles, "
        "not the gene-level role or recurrence):",
        f"  civic_variant_class (strongest oncogenicity among the gene's variants): {h.get('civic_variant_class', 'n/a')}",
        f"  oncogenic variants: {_civic_variant_line(h.get('civic_oncogenic_variants'), 'oncogenicity_class')}",
        f"  resistance variants (therapy-linked): {_civic_variant_line(h.get('civic_resistance_variants'), 'resistance_class', with_therapies=True)}",
        "  NOTE: per-VARIANT, aggregated to the gene — names WHICH alleles are oncogenic (vs the "
        "gene-level role) + which confer therapy resistance. data_unavailable = uncurated by CIViC, "
        "NOT benign. Verdict-inert.",
        "",
        "GENOME-INSTABILITY / PASSENGER-RISK CONTEXT (INDICATION-level cohort context, "
        "target-independent; use to WEIGH the recurrence signal, not as a driver call):",
        f"  aneuploidy_burden_class (CIN): {h.get('aneuploidy_burden_class', 'n/a')}   "
        f"wgd_class (whole-genome-doubling prevalence): {h.get('wgd_class', 'n/a')}",
        f"  msi_class (patient, CRC/STAD only): {h.get('msi_class', 'n/a')}   "
        f"model_msi_class (DepMap, all lineages): {h.get('model_msi_class', 'n/a')}   "
        f"model_mmr_signature_class (SBS, cross-validates MSI): {h.get('model_mmr_signature_class', 'n/a')}",
        "  NOTE: a HYPERMUTATED / MSI-H cohort accumulates PASSENGER mutations — in that context a "
        "large gene's high recurrence is discounted (the passenger-inflation caveat above, now "
        "quantified). High CIN / WGD also inflates copy-number noise (weigh amplification calls "
        "accordingly). data_unavailable = unlabelled cohort, NOT low-instability. Verdict-inert.",
    ]

    # Subtype panorama — only present when --subtypes scoped this run (descriptive; verdict-inert).
    subtype_axis = h.get("subtype_axis")
    if subtype_axis:
        lines += [
            "",
            "SUBTYPE PANORAMA (descriptive per-stratum recurrence — present only when --subtypes scoped):",
            f"  subtype_mutation_pattern: {subtype_axis.get('subtype_mutation_pattern')}",
            f"  cross_subgroup_delta_frequency: {_fmt(subtype_axis.get('cross_subgroup_delta_frequency'), 3)}",
            f"  measured_strata: {subtype_axis.get('measured_strata')}",
        ]
    else:
        lines += [
            "",
            "SUBTYPE PANORAMA: not scoped this run (no --subtypes). Do NOT narrate a subtype pattern.",
        ]

    lines += [
        "",
        "TASK: using emit_genomic_alteration_synthesis, judge how much the GENOMIC-ALTERATION lens "
        f"informs whether {target} is a relevant drug target in {indication}. Reason ACROSS the "
        "alteration mix + role + recurrence — do not just restate the verdict. Say WHICH class drives. "
        "Weigh recurrence AGAINST function (a recurrently-mutated passenger is NOT a driver). If the "
        "target is altered only as a likely passenger, say alteration is UNINFORMATIVE for relevance "
        "and the rationale must come from other lenses. Do NOT discuss modality or expression. Ground "
        "every claim in the fields; state DATA_UNAVAILABLE gaps plainly.",
    ]
    return "\n".join(lines)


def synthesize_genomic_alteration(decision: dict, model_id: Optional[str] = None) -> dict:
    """Run the opt-in genomic-alteration narration over a composed decision. Returns the provenance-
    tagged llm_synthesis block. Raises are the CALLER's to handle (the caller degrades to a note on
    failure — synthesis is never allowed to break the deterministic run)."""
    from _skills_common.llm import synthesize_structured
    user_prompt = build_user_prompt(decision)
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
