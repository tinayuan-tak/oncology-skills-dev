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

OPT-IN: only runs when the caller passes --synthesize. Two-slot: the narration is attached as the
sibling key decision['llm_synthesis'] AFTER the deterministic decision is composed, so it is
structurally impossible for it to alter the verdict spine. The VERDICT SPINE (headline + cards +
fired_rules) is byte-identical with or without --synthesize. NOTE: the full decision.json is NOT
byte-identical run-to-run even without the flag — the dispatcher always stamps `run_health` with
wall-clock timings (read_secs/compute_secs/total_secs), which vary per run. A determinism diff must
exclude the `run_health` sibling (and, when present, `llm_synthesis`); both are verdict-inert.
"""
from __future__ import annotations

from _skills_common.llm import EVIDENCE_ONLY_DIRECTIVE as _EVIDENCE_ONLY_DIRECTIVE

from typing import Optional

# The structured-output contract. Categorical fields use fixed enums so the narration
# stays validatable; free-text fields are bounded. The LLM must call THIS tool.
SYNTHESIS_TOOL_NAME = "emit_presence_synthesis"
SYNTHESIS_TOOL_SCHEMA = {
    "type": "object",
    "description": ("Assess, from the EXPRESSION/PRESENCE lens ALONE, how much this lens informs "
                    "whether the target is a relevant drug target for this cancer — at the "
                    "indication and (where measured) subtype grain. Reason ACROSS the gathered "
                    "presence evidence (RNA + protein, tumor + cell-line, vs adjacent, pan-cancer "
                    "breadth, subtype effect); do NOT restate a different verdict, and do NOT assess "
                    "therapeutic modality (that is the cross-lens target-profile's job, not this "
                    "single-lens skill's)."),
    "properties": {
        "expression_relevance_for_target": {
            "type": "string",
            "enum": ["strongly_supports", "supports_with_caveats", "neutral_uninformative",
                     "argues_against"],
            "description": ("The headline judgment: how much does the EXPRESSION evidence inform this "
                            "target's relevance as a drug target for this cancer? "
                            "strongly_supports = abundant + tumor-elevated/selective, expression is a "
                            "genuine part of the rationale. supports_with_caveats = supportive but "
                            "qualified (purity, proxy, modest fold-change, coverage). "
                            "neutral_uninformative = present but not distinguishing (e.g. broadly "
                            "moderate/ubiquitous, no tumor elevation) — expression is NOT the reason to "
                            "pursue this target; the rationale must come from OTHER lenses (dependency, "
                            "mutation, mechanism). argues_against = low/absent or a presence pattern "
                            "that undercuts the hypothesis. This is a SINGLE-LENS relevance read; it "
                            "informs confidence, it NEVER mints or flips a nomination.")},
        "relevance_rationale": {
            "type": "string",
            "description": ("2-4 sentences REASONING ACROSS the gathered presence evidence to justify "
                            "expression_relevance_for_target: integrate the deterministic verdict, the "
                            "tumor-vs-adjacent / protein / cell-line reads, all-gene percentile, and "
                            "pan-cancer breadth. Say explicitly whether expression IS or IS NOT a "
                            "load-bearing part of the target rationale for this cancer, and if not, that "
                            "the case must rest on other lenses. Ground every claim in the fields; cite "
                            "DATA_UNAVAILABLE gaps rather than omitting them.")},
        "indication_vs_subtype_relevance": {
            "type": "string",
            "description": ("1-2 sentences on GRAIN: is the expression relevance an indication-wide "
                            "read, or does it concentrate in / depend on a molecular subtype "
                            "(patient-selection axis)? Use the across-subtype effect + any queried "
                            "subtype. If the subtype axis is unavailable, say the read is "
                            "indication-grain only. Do NOT invent a subtype pattern.")},
        "confidence_qualifier": {
            "type": "string",
            "enum": ["well_supported", "supported_with_caveats", "weakly_supported",
                     "insufficient_evidence"],
            "description": ("How well the gathered evidence supports the relevance read above "
                            "(data completeness/quality: coverage, purity, RNA-vs-protein "
                            "concordance, subtype power). A CONFIDENCE read — it does not change the "
                            "deterministic verdict.")},
        "key_caveat": {
            "type": "string",
            "description": ("The single most important caveat a reviewer should carry (purity confound, "
                            "coverage gap, proxy-normal, subtype underpowering, etc.), or 'none' if none.")},
    },
    "required": ["expression_relevance_for_target", "relevance_rationale",
                 "indication_vs_subtype_relevance", "confidence_qualifier", "key_caveat"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You are a computational-oncology target-evaluation assistant. Your PURPOSE here is narrow and "
    "specific: reason ACROSS the tumor-presence / expression evidence for a (target, indication) and "
    "judge HOW MUCH THIS LENS INFORMS whether the target is a relevant drug target for this cancer — "
    "at the indication grain, and at the subtype grain where subtypes are measured. This is a "
    "SINGLE-LENS relevance assessment. "
    "You NARRATE and INTEGRATE; you never invent facts, and you never change the deterministic, "
    "rule-computed verdict or class labels (they are FIXED upstream). Ground every claim in the "
    "numeric fields provided. "
    "WHAT 'RELEVANCE' MEANS HERE: does the expression evidence give a REASON to pursue this target in "
    "this cancer? A target that is highly abundant AND tumor-elevated/selective → expression is a "
    "genuine part of the rationale (strongly_supports). A target that is merely present but broadly / "
    "ubiquitously expressed with no tumor elevation → expression is UNINFORMATIVE for target relevance "
    "(neutral_uninformative): say so plainly, and say the rationale must come from OTHER lenses "
    "(dependency, mutation, mechanism) — do NOT dress up mere presence as support. "
    "GRAIN DISCIPLINE: the indication is the anchor; bring in the pan-cancer breadth only if a value is "
    "given; bring in the subtype grain only if the subtype axis is available; foreground a queried "
    "subtype only if it is among the computed strata. State DATA_UNAVAILABLE gaps plainly — a null "
    "result is decision-useful. "
    "REGISTER — write to scientific-publication standard: the voice of a methods/results section. "
    "Declarative, precise, and factual; complete sentences; active voice. Report each number with its "
    "scale and direction, never bare. Do NOT use promotional or editorialising language (avoid "
    "'promising', 'exciting', 'compelling', 'robustly', 'clearly'); let the evidence carry the claim. "
    "Concise but readable — a domain biologist who is not a statistician must follow it without a glossary. "
    "PLAIN-LANGUAGE METRICS — on FIRST use of any technical quantity, add a short parenthetical gloss so a "
    "non-computational reader can interpret it, e.g.: log2(TPM+1) (log-scaled transcript abundance; ~1 = "
    "low/detectable, >=5 ~ highly expressed); all-gene percentile (where this target's abundance ranks "
    "among all genes in the same cohort, 0-100); control-benchmark position (where the target sits vs "
    "curated known-abundant antigens and silent/floor negatives on the same percentile scale); "
    "epsilon-squared / ε² (the fraction of expression variation across molecular subtypes that subtype "
    "explains, 0-1; ~0.06 moderate, ~0.14 large). Gloss once, then use the term freely. "
    "SCOPE DISCIPLINE: do NOT discuss therapeutic MODALITY (small-molecule / degrader / ADC / "
    "T-cell-engager / antibody / CAR) or surface accessibility. Modality reasoning requires holding "
    "multiple evidence lenses together and belongs to the composed target-profile synthesis, not to "
    "this single-lens presence skill. The control benchmarks are only an ABUNDANCE yardstick."
    + _EVIDENCE_ONLY_DIRECTIVE
)

# Deterministic plain-language legend for the metrics this narration cites — attached as a sibling
# key (metric_legend) so a non-computational reader always has an accurate, byte-stable reference,
# independent of the LLM's inline glosses. Mirrors synthesis_dependency.METRIC_LEGEND.
METRIC_LEGEND = {
    "log2_tpm": ("log2(TPM+1): log-scaled transcript abundance. Roughly: ~1 = low but detectable, "
                 "~3.5 = moderate (TPM~10), >=5 = highly expressed (TPM~50+). The ABSOLUTE level, "
                 "distinct from tumour-vs-normal selectivity."),
    "allgene_percentile": ("Where this target's abundance ranks among ALL genes measured in the same "
                           "cohort (0-100). 99th = top-1% most abundant; answers 'abundant relative to "
                           "what?' A lineage-restricted antigen can read high in-tissue yet mid on a "
                           "pan-cancer panel — the two frames are orthogonal."),
    "control_position": ("Where the target's abundance percentile sits relative to curated controls "
                         "on the same scale: known tumour-abundant antigens (positive anchors, e.g. "
                         "CEACAM5/EPCAM) and housekeeping-ceiling / silent-floor negatives. "
                         "'above_all_positives' = antigen-level abundance; 'below_negatives' = low."),
    "subtype_epsilon_squared": ("ε² (epsilon-squared): the fraction of expression variation across "
                                "molecular subtypes that subtype membership explains, 0-1. ~0.06 "
                                "moderate, ~0.14 large. Large = expression concentrates in a subtype "
                                "(a patient-selection axis); negligible = uniform across subtypes."),
    "tumor_vs_adjacent_log2fc": ("log2 fold-change of tumour vs paired adjacent-normal (or GTEx "
                                 "fallback). +1 = 2x higher in tumour. A directional presence signal; "
                                 "the tumour-vs-normal WINDOW itself is the selectivity lens's job."),
}


def _fmt(v, nd=1):
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


# The verdict-BEARING + display cards whose measured values are decision-useful to the
# narration are forwarded by build_user_prompt below (via _card_line). Widened (2026-08-05)
# from the original 2-card read (tumor-rna-distribution + -by-subtype), which dropped the DEG
# card, both protein layers, and the pan-cancer breadth card — i.e. narrated "the signal, not
# the null results." A card present-but-data_unavailable is rendered as DATA_UNAVAILABLE (the
# measured-negative-vs-data_unavailable distinction the narration must preserve).


def make_card_state(present_ids: set, missing: set):
    """Return a `card_state(card_id) -> str` classifier for the per-lens synthesis prompts:
    DATA_UNAVAILABLE for a measured-but-empty card, "not present in this run" for a card not
    resolved in this run, else "measured". Shared by the lens modules
    (synthesis_dependency / _surface_modality / _tractability_sm) so the identical three-state
    closure is not re-defined per lens."""
    def card_state(card_id: str) -> str:
        if card_id in missing:
            return "DATA_UNAVAILABLE (measured, no usable value)"
        if card_id not in present_ids:
            return "not present in this run"
        return "measured"
    return card_state


def _card_line(cards: dict, missing: set, present_ids: set, card_id: str, fields: list) -> str:
    """Render one card's decision-useful fields, or its honest absence. Distinguishes THREE
    states (the measured-gap doctrine): a card READ but data_unavailable (DATA_UNAVAILABLE —
    it was measured, the null is decision-useful), a card never present in this run (not wired),
    and a present card with values."""
    if card_id in missing:
        # measured-but-unavailable: ALWAYS labeled DATA_UNAVAILABLE, even with an empty summary
        # (it was read — that is the distinction from a never-wired card).
        summary = cards.get(card_id) or {}
        shown = "  ".join(f"{f}={summary.get(f)}" for f in fields if f in summary)
        return f"  {card_id}: DATA_UNAVAILABLE (measured, no usable value){(' | ' + shown) if shown else ''}"
    if card_id not in present_ids:
        return f"  {card_id}: not present in this run"
    summary = cards.get(card_id) or {}
    shown = "  ".join(f"{f}={summary.get(f)}" for f in fields if f in summary)
    return f"  {card_id}: {shown if shown else '(no listed fields present)'}"


def _claim_vector_block(cv: Optional[dict]) -> str:
    """Render the pre-computed presence CLAIM VECTOR as grounding substrate for the narration, so the
    relevance enum + confidence derive from the deterministic (signal × corroboration) per claim rather
    than the LLM re-deriving them. Additive / backward-compatible: a no-op note when the decision
    predates claim_vector (spine byte-stable either way)."""
    if not isinstance(cv, dict):
        return "  (claim vector not present in this decision — narrate from the fields above.)"
    rows = []
    for k, name in (("A", "abundance"), ("B", "tumor-elevation"),
                    ("C", "malignant-intrinsic"), ("D", "generality")):
        cl = cv.get(k) or {}
        rows.append(f"    {k} {name}: signal={cl.get('signal')} corroboration={cl.get('corroboration')} "
                    f"— {cl.get('evidence')}" + (f"  CONFLICT: {cl['conflict']}" if cl.get("conflict") else ""))
    if cv.get("homogeneity"):
        rows.append(f"    homogeneity: {cv.get('homogeneity')}")
    rows.append(
        "  DIRECTIVE: your confidence_qualifier MUST track the claim corroboration tiers (a decision-critical "
        "claim of corroboration=low/insufficient cannot yield well_supported). expression_relevance_for_target "
        "MUST reflect claims A (abundance) AND B (tumor-elevation) TOGETHER — a strong B with a weak/mid A is "
        "NOT strongly_supports; do NOT upgrade on fold-change alone. Claims are ORTHOGONAL — a weak C does not "
        "degrade a strong B; never average them.")
    return "\n".join(rows)


def build_user_prompt(decision: dict, subtype_query: Optional[str] = None) -> str:
    """Assemble the LLM input from the DETERMINISTIC decision spine. Narrates the computed
    interpretation (contextualized axes) grounded in the FULL gathered evidence — the verdict-
    bearing DEG + protein + breadth cards, not only the 2 distribution cards. Grain-governed:
    indication is the anchor, pan-cancer breadth is the frame, the across-subtype omnibus is
    narrated only when the subtype axis is available + powered, and a queried subtype
    (subtype_query) is foregrounded only when it is among the computed strata."""
    h = decision.get("headline", {}) or {}
    target = decision.get("target"); indication = decision.get("indication")
    card_list = decision.get("cards", [])
    cards = {c["card_id"]: (c.get("summary") or {}) for c in card_list}
    present_ids = {c["card_id"] for c in card_list}
    # A card is "measured but unavailable" when resolve_cards tagged it _missing. Track it so
    # _card_line renders DATA_UNAVAILABLE (it was READ) distinctly from a card not present at all.
    missing = {c["card_id"] for c in card_list if c.get("_missing")}
    tumor_rna = cards.get("tumor-rna-distribution", {})
    subtype = cards.get("tumor-rna-distribution-by-subtype", {})
    breadth = cards.get("tumor-elevation-breadth", {})

    lines = [
        f"TARGET: {target}    INDICATION: {indication}",
        "",
        "DETERMINISTIC VERDICT (fixed — narrate, do not change):",
        f"  presence_verdict: {h.get('presence_verdict')}  (driving_rule: {h.get('driving_rule_id')})",
        "",
        "GRAIN GOVERNANCE (narrate each grain ONLY where data exists; never invent a grain):",
        f"  indication anchor: {indication} (the run grain — always the primary read)",
        f"  pan-cancer frame available: {'yes' if breadth else 'no'}",
        f"  subtype axis available: {subtype.get('subtype_axis_available', 'unknown')}",
        f"  subtype queried: {subtype_query or 'none'}",
        "",
        "INDICATION-ANCHOR EVIDENCE (the full gathered presence read — cite the measured values):",
        # Field names are the ACTUAL keys each card emits (verified against live decision.json,
        # 2026-08-05). An earlier version guessed names that did not match, so real cards rendered
        # as "no fields present" — a silent version of the drops-nulls failure this module fixes.
        _card_line(cards, missing, present_ids, "tumor-rna-vs-adjacent",
                   ["expression_call_class", "log2_fc", "q_value",
                    "is_upregulated_provider_call", "tumor_mean_tpm", "adjacent_mean_tpm"]),
        _card_line(cards, missing, present_ids, "tumor-protein-abundance-cptac",
                   ["protein_expression_class", "protein_effect_size", "protein_bh_q_value",
                    "cohort", "n_tumor_samples", "n_normal_samples"]),
        _card_line(cards, missing, present_ids, "cellline-protein-abundance",
                   ["protein_expression_class", "protein_effect_size", "median_log2_abundance_panel",
                    "fraction_detected", "n_cell_lines_evaluated"]),
        _card_line(cards, missing, present_ids, "cellline-rna-distribution",
                   ["expression_class", "median_log2tpm_panel", "distribution_pattern",
                    "fraction_expressed"]),
        _card_line(cards, missing, present_ids, "cellline-rna-protein-concordance",
                   ["rna_as_biomarker", "rna_protein_r", "n_paired_models"]),
        "",
        "AXIS 1 — ALL-GENE PERCENTILE (where the target sits among ALL genes IN THIS INDICATION):",
        f"  tumor all-gene percentile: {_fmt(tumor_rna.get('allgene_percentile'))} "
        f"({tumor_rna.get('allgene_percentile_class')})",
        f"  context: {tumor_rna.get('allgene_percentile_context')}",
        "",
        "PAN-CANCER FRAME (tumor-elevation breadth ACROSS indications — the true pan-cancer grain):",
        (f"  tumor_elevation_breadth_class: {breadth.get('tumor_elevation_breadth_class')}  "
         f"n_cohorts_elevated: {breadth.get('n_cohorts_elevated')} / "
         f"{breadth.get('n_cohorts_tested')}  "
         f"most_elevated: {breadth.get('most_elevated_cohorts')}"
         if breadth else "  (pan-cancer breadth card not available this run — do NOT assert a pan-cancer pattern)"),
        "",
        "AXIS 2 — CONTROL-BENCHMARK POSITION (vs known positive/negative antigens, same scale):",
        f"  control_position_class: {tumor_rna.get('control_position_class')}",
        f"  control_position: {tumor_rna.get('control_position')}",
        f"  positive controls (percentile): {tumor_rna.get('control_positives')}",
        f"  negative controls (percentile): {tumor_rna.get('control_negatives')}",
        f"  negatives excluded (lineage-conflict): {tumor_rna.get('control_negatives_excluded_lineage_conflict')}",
        "",
        "AXIS 3 — ACROSS-SUBTYPE OMNIBUS (is subtype a patient-selection axis?):",
    ]
    # Grain governance for the subtype axis: narrate the omnibus ONLY when the axis is available.
    if subtype.get("subtype_axis_available"):
        lines += [
            f"  subtype_effect_size_class: {subtype.get('subtype_effect_size_class')}  "
            f"(variance_explained ε²={_fmt(subtype.get('subtype_variance_explained'), 3)})",
            f"  which_subtypes_separate: {subtype.get('which_subtypes_separate')}",
            f"  subtype_stratification_class: {subtype.get('subtype_stratification_class')}",
            f"  n_subtypes_measured: {subtype.get('n_subtypes_measured')}",
        ]
        # Queried-subtype grain: foreground the named stratum ONLY if it is among the computed
        # strata. "Computed strata" = keys of a per-subtype value map (preferred, carries the
        # position) OR the named strata in which_subtypes_separate (the omnibus extremes).
        if subtype_query:
            per_subtype = subtype.get("per_subtype") or subtype.get("subtype_values") or {}
            wss = subtype.get("which_subtypes_separate") or {}
            named = set(v for v in wss.values() if isinstance(v, str)) if isinstance(wss, dict) else set()
            known_strata = (set(per_subtype) if isinstance(per_subtype, dict) else set()) | named
            if isinstance(per_subtype, dict) and subtype_query in per_subtype:
                lines.append(f"  QUERIED SUBTYPE {subtype_query}: {per_subtype[subtype_query]} "
                             f"— foreground this stratum's position in the narrative.")
            elif subtype_query in named:
                lines.append(f"  QUERIED SUBTYPE {subtype_query}: appears in the omnibus extremes "
                             f"({wss}) but no per-stratum value was emitted — narrate its role from "
                             f"the omnibus (e.g. highest/lowest), do NOT fabricate a numeric position.")
            else:
                avail = ", ".join(sorted(known_strata)) if known_strata else "n/a"
                lines.append(f"  QUERIED SUBTYPE {subtype_query}: NOT among the computed strata "
                             f"(available: {avail}). Say so plainly; do NOT invent a position for it.")
    else:
        lines.append("  subtype axis NOT available for this indication (no landed subtype-assignment "
                     "shard). Do NOT narrate a subtype effect — state the axis is unavailable.")

    # PER-MODALITY sub-verdicts (the deterministic per-(measurement, sample_context) buckets — the
    # narrator should read these directly rather than reconstruct modality-level reads from raw fields).
    per_modality = h.get("presence_verdict_by_modality") or {}
    pm_lines = []
    for _bk, _bv in per_modality.items():
        if isinstance(_bv, dict):
            pm_lines.append(f"    {_bk}: {_bv.get('verdict')} [{_bv.get('evidence_state')}]")
    lines += [
        "",
        "PER-MODALITY SUB-VERDICTS (deterministic; one per measurement/sample_context bucket — "
        "do NOT collapse; a positive bulk_rna/tumor with a data_unavailable sc_rna/tumor is a coverage "
        "statement, not a negative):",
        ("\n".join(pm_lines) if pm_lines else "    (none emitted)"),
        "",
        "SINGLE-CELL (sc_rna/tumor — malignant-vs-microenvironment attribution bulk cannot make; "
        "COADREAD+NSCLC only, else data_unavailable):",
        f"  sc_expression_class: {h.get('sc_expression_class')}  "
        f"malignant_detection_fraction: {_fmt(h.get('sc_malignant_detection_fraction'), 3)}  "
        f"top_microenvironment_compartment: {h.get('sc_top_microenvironment_compartment')}",
        "",
        "RNA→PROTEIN PROXY QUALITY (is the RNA presence claim trustworthy as a stand-in for PROTEIN? "
        "the TUMOR-arm concordance is what a patient-context claim rests on — bulk-tumor purity/stroma/"
        "post-transcriptional regulation degrade it far more than cell lines):",
        f"  bulk_rna_proxy_quality: {h.get('bulk_rna_proxy_quality')} "
        f"(source: {h.get('bulk_rna_proxy_quality_source')})",
        f"  cell-line rna_as_biomarker: {h.get('rna_as_biomarker')} (r={_fmt(h.get('rna_protein_r'), 2)})",
        f"  TUMOR rna_as_biomarker: {h.get('rna_as_biomarker_tumor')} "
        f"(r={_fmt(h.get('rna_protein_r_tumor'), 2)}, n_paired_tumors={h.get('rna_protein_n_paired_tumors')}, "
        f"cohort={h.get('rna_protein_cptac_cohort')})",
        "  → if bulk_rna_proxy_quality is rna_positive_proxy_poor, an RNA-only presence claim needs "
        "PROTEIN confirmation before a biologics/ADC read; surface this as the key_caveat.",
        "",
        "SUPPORTING CONTEXT:",
        f"  tumor_expression_class: {tumor_rna.get('tumor_expression_class')}  "
        f"median_log2tpm: {_fmt(tumor_rna.get('median_log2tpm'), 2)}",
        f"  purity_confound_class: {h.get('purity_confound_class')}",
        "",
        "DETERMINISTIC CLAIM VECTOR (pre-computed within-lens integration; treat as ground truth — "
        "obey its DIRECTIVE on confidence + relevance):",
        _claim_vector_block(h.get("claim_vector")),
        "",
        "TASK: using emit_presence_synthesis, judge how much this EXPRESSION lens informs whether "
        f"{target} is a relevant drug target for {indication} (and, where measured, which subtype). "
        "Reason ACROSS the evidence above — do not just restate the verdict. If the target is merely "
        "present but not tumor-elevated/selective, say expression is UNINFORMATIVE for relevance and "
        "the rationale must come from other lenses. Do NOT discuss therapeutic modality. Ground every "
        "claim in the fields; state DATA_UNAVAILABLE gaps plainly — the null result is decision-useful.",
    ]
    return "\n".join(lines)


def synthesize_presence(decision: dict, model_id: Optional[str] = None,
                        subtype_query: Optional[str] = None) -> dict:
    """Run the opt-in narration over a composed decision. Returns the provenance-tagged
    llm_synthesis block (to be attached as decision['llm_synthesis']). Raises are the
    CALLER's to handle (the dispatcher degrades to a note on failure — synthesis is
    never allowed to break the deterministic run)."""
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
